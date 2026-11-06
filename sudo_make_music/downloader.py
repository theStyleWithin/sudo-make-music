"""Download a catalog entry into a model folder: resumable, cancellable, size-capped, hash-verified, host-allowlisted.

Hugging Face repos are listed through its public API (so you never have to navigate the website); file hashes come from
that API (LFS sha256, or the git blob sha1 for small files) and every file is verified against them."""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
import urllib.parse
from pathlib import Path

from . import netutil
from .backends.base import Cancelled

HF_BASE = "https://huggingface.co"
MAX_TOTAL_BYTES = 60 * 1024**3


class DownloadError(Exception):
    pass


def _hf_headers(token: str | None) -> dict:
    return {"Authorization": f"Bearer {token}"} if token else {}


def list_hf_files(repo: str, revision: str = "main", token: str | None = None, hf_base: str = HF_BASE,
                  allow: list | None = None, allow_local_http: bool = False) -> list[dict]:
    """[{path, size, sha256|None, sha1|None}] for the files of a repo, filtered by glob patterns."""
    url = f"{hf_base}/api/models/{repo}/tree/{urllib.parse.quote(revision)}?recursive=true"
    out: list[dict] = []
    for _ in range(50):                                   # follow pagination
        try:
            with netutil.open_url(url, secret_headers=_hf_headers(token), allow_local_http=allow_local_http) as r:
                items = json.loads(r.read(50_000_000).decode("utf-8"))
                link = r.headers.get("Link", "")
        except netutil.HTTPError as e:
            if e.code in (401, 403):
                raise DownloadError("This model is gated: accept its licence on the model page and set the HF_TOKEN environment variable") from e
            if e.code == 404:
                raise DownloadError(f"repository {repo} was not found") from e
            raise DownloadError(f"the model list could not be read (HTTP {e.code})") from e
        for it in items:
            if it.get("type") != "file":
                continue
            path = it["path"]
            if allow and not any(fnmatch.fnmatch(path, g) for g in allow):
                continue
            lfs = it.get("lfs") or {}
            out.append(dict(path=path, size=int(lfs.get("size") or it.get("size") or 0),
                            sha256=lfs.get("oid") if lfs else None,
                            sha1=None if lfs else (it.get("oid") if len(it.get("oid", "")) == 40 else None)))
        nxt = [p for p in link.split(",") if 'rel="next"' in p]
        if not nxt:
            break
        url = nxt[0].split(";")[0].strip(" <>")
    if not out:
        raise DownloadError(f"{repo}: no files matched")
    return out


def _safe_rel(path: str) -> Path:
    p = Path(path)
    if p.is_absolute() or ".." in p.parts or not p.parts:
        raise DownloadError(f"unsafe file path in listing: {path!r}")
    return p


def download_file(url: str, dest: Path, expected_size: int = 0, sha256: str | None = None, sha1_blob: str | None = None,
                  headers: dict | None = None, secret_headers: dict | None = None, progress=None, cancel=None,
                  allow_local_http: bool = False, max_bytes: int = MAX_TOTAL_BYTES) -> str:
    """Stream to dest (via dest.part, resumable). Returns the file's sha256."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    h = hashlib.sha256()
    have = 0
    if part.exists():
        have = part.stat().st_size
        if expected_size and have > expected_size:
            part.unlink()
            have = 0
        else:
            with open(part, "rb") as fh:                  # re-hash what we already have
                while chunk := fh.read(8 * 1024 * 1024):
                    h.update(chunk)
    hd = dict(headers or {})
    if have:
        hd["Range"] = f"bytes={have}-"
    try:
        r = netutil.open_url(url, headers=hd, secret_headers=secret_headers, timeout=60, allow_local_http=allow_local_http)
    except netutil.HTTPError as e:
        if e.code == 416 and expected_size and have == expected_size:   # already complete
            r = None
        elif e.code in (401, 403):
            raise DownloadError("access denied (a gated model needs an accepted licence and the HF_TOKEN environment variable)") from e
        else:
            raise DownloadError(f"download failed (HTTP {e.code})") from e
    if r is not None:
        with r:
            if have and r.status != 206:                  # server ignored Range: start over
                have, h = 0, hashlib.sha256()
                part.unlink(missing_ok=True)
            total = expected_size or (have + int(r.headers.get("Content-Length") or 0))
            if total > max_bytes:
                raise DownloadError("file is larger than the safety limit")
            with open(part, "ab" if have else "wb") as out:
                while chunk := r.read(1024 * 1024):
                    if cancel and cancel():
                        raise Cancelled()
                    out.write(chunk)
                    h.update(chunk)
                    have += len(chunk)
                    if have > max_bytes:
                        raise DownloadError("file is larger than the safety limit")
                    if progress:
                        progress(len(chunk))
    if expected_size and part.stat().st_size != expected_size:
        raise DownloadError(f"{dest.name}: incomplete download ({part.stat().st_size} of {expected_size} bytes)")
    digest = h.hexdigest()
    if sha256 and digest != sha256.lower():
        part.unlink(missing_ok=True)
        raise DownloadError(f"{dest.name}: checksum mismatch (file was damaged or tampered with); it was deleted")
    if sha1_blob:                                         # git blob hash for small non-LFS files
        data = part.read_bytes()
        if hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest() != sha1_blob:
            part.unlink(missing_ok=True)
            raise DownloadError(f"{dest.name}: checksum mismatch; it was deleted")
    os.replace(part, dest)
    return digest


def install_sources(sources: list, dest_dir: Path, token: str | None = None, progress=None, cancel=None,
                    hf_base: str = HF_BASE, allow_local_http: bool = False) -> dict:
    """Download every source of an entry into dest_dir. progress(done_bytes, total_bytes). Returns {relpath: sha256}."""
    plan: list[tuple[str, Path, dict]] = []     # (url, target, info)
    for s in sources:
        sub = _safe_rel(s["dest"]) if s.get("dest") else Path()
        if s["type"] == "hf_repo":
            rev = s.get("revision", "main")
            for f in list_hf_files(s["repo"], rev, token, hf_base, s.get("allow"), allow_local_http):
                rel = sub / _safe_rel(f["path"])
                url = f"{hf_base}/{s['repo']}/resolve/{urllib.parse.quote(rev)}/{urllib.parse.quote(f['path'])}"
                plan.append((url, dest_dir / rel, dict(f, token=token, rel=str(rel).replace("\\", "/"))))
        else:
            name = s.get("filename") or Path(urllib.parse.urlparse(s["url"]).path).name
            rel = sub / _safe_rel(name)
            plan.append((s["url"], dest_dir / rel, dict(size=int(s.get("size", 0)), sha256=s.get("sha256"), sha1=None,
                                                         token=None, rel=str(rel).replace("\\", "/"))))
    total = sum(i["size"] for _, _, i in plan)
    if total > MAX_TOTAL_BYTES:
        raise DownloadError("this download is larger than the safety limit")
    dest_dir.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(dest_dir).free
    if total and free < total * 1.05 + 200 * 1024 * 1024:
        raise DownloadError(f"not enough disk space: needs about {total / 1e9:.1f} GB, {free / 1e9:.1f} GB free")
    done = 0
    hashes: dict[str, str] = {}

    def bump(n):
        nonlocal done
        done += n
        if progress:
            progress(done, total)

    for url, target, info in plan:
        if target.exists() and info["size"] and target.stat().st_size == info["size"]:
            hashes[info["rel"]] = _sha(target)           # already there from an earlier attempt
            bump(info["size"])
            continue
        hashes[info["rel"]] = download_file(
            url, target, info["size"], info.get("sha256"), info.get("sha1"),
            secret_headers=_hf_headers(info.get("token")) if "huggingface" in urllib.parse.urlparse(url).netloc or allow_local_http else None,
            progress=bump, cancel=cancel, allow_local_http=allow_local_http)
    return hashes


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(8 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()
