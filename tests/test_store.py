import hashlib
import http.server
import io
import json
import os
import pickle
import struct
import threading
import time
import zipfile
from pathlib import Path

import pytest

from sudo_make_music import catalog, downloader, netutil, safety, virustotal
from sudo_make_music.backends.base import Cancelled
from sudo_make_music.engine import Engine
from sudo_make_music.hardware import HardwareInfo
from sudo_make_music.history import History
from sudo_make_music.settings import SettingsStore


# ---------------------------------------------------------------- a tiny fake Hugging Face / VirusTotal / catalog server
def safetensors_bytes() -> bytes:
    header = json.dumps({"w": {"dtype": "F32", "shape": [2], "data_offsets": [0, 8]}}).encode()
    return struct.pack("<Q", len(header)) + header + b"\x00" * 8


class Evil:
    def __reduce__(self):
        return (os.system, ("echo pwned",))


def make_server(files: dict[str, bytes], extra: dict | None = None):
    """files: path -> bytes for repo 'test/repo'. extra: url path -> (status, body bytes)."""
    extra = extra or {}
    tree = []
    for p, data in files.items():
        item = {"type": "file", "path": p, "size": len(data)}
        if p.endswith(".safetensors") or p.endswith(".pt") or p.endswith(".pth"):
            item["lfs"] = {"oid": hashlib.sha256(data).hexdigest(), "size": len(data)}
        else:
            item["oid"] = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
        tree.append(item)

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in extra:
                code, body = extra[path]
                self.send_response(code); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
                return
            if path == "/api/models/test/repo/tree/main":
                body = json.dumps(tree).encode()
            elif path.startswith("/test/repo/resolve/main/"):
                name = path[len("/test/repo/resolve/main/"):]
                data = files.get(name)
                if data is None:
                    self.send_response(404); self.end_headers(); return
                rng = self.headers.get("Range")
                if rng:
                    start = int(rng.split("=")[1].rstrip("-"))
                    body = data[start:]
                    self.send_response(206)
                else:
                    body = data
                    self.send_response(200)
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
                return
            else:
                self.send_response(404); self.end_headers(); return
            self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


@pytest.fixture
def server():
    srvs = []

    def make(files, extra=None):
        s, base = make_server(files, extra)
        srvs.append(s)
        return base
    yield make
    for s in srvs:
        s.shutdown()


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("SUDO_MAKE_MUSIC_HOME", str(tmp_path))
    e = Engine(SettingsStore(tmp_path / "s.json"), History(tmp_path / "h.db"))
    e.store.value.scan_after_download = False
    e.allow_local_http = True
    yield e
    e.shutdown()


def wait_task(e, timeout=30):
    t = time.time()
    while e.install_task.status == "running" and time.time() - t < timeout:
        time.sleep(0.05)
    return e.install_task


def make_entry(files_repo="test/repo", **kw):
    d = dict(id="test-model", name="Test model", role="music", backend="mock", sources=[{"type": "hf_repo", "repo": files_repo}])
    d.update(kw)
    return catalog.validate_entry(d, allow_local_http=True)


# ---------------------------------------------------------------- catalog + hardware recommendation
def test_bundled_catalog_loads_and_is_valid(tmp_path):
    c = catalog.CatalogStore(cache=tmp_path / "none.json")
    assert len(c.entries()) >= 5 and c.source == "built-in list"
    assert {e.role for e in c.entries()} >= {"music", "speech", "converter"}


def test_validation_rejects_bad_entries():
    bad = [dict(id="x", name="x", role="nonsense", backend="b", sources=[{"type": "hf_repo", "repo": "a/b"}]),
           dict(id="x", name="x", role="music", backend="b", sources=[{"type": "url", "url": "https://evil.example.com/m.bin"}]),
           dict(id="x", name="x", role="music", backend="b", sources=[{"type": "url", "url": "http://huggingface.co/m.bin"}]),
           dict(id="x", name="x", role="music", backend="b", sources=[{"type": "hf_repo", "repo": "../etc/passwd"}]),
           dict(id="x", name="x", role="music", backend="b", sources=[{"type": "hf_repo", "repo": "a/b", "dest": "../../out"}]),
           dict(id="x/../y", name="x", role="music", backend="b", sources=[{"type": "hf_repo", "repo": "a/b"}])]
    for d in bad:
        with pytest.raises(ValueError):
            catalog.validate_entry(d)


def test_recommendations_by_hardware(tmp_path):
    entries = catalog.CatalogStore(cache=tmp_path / "none.json").entries()
    rows = lambda hw: {r["id"]: r for r in catalog.rank(entries, hw)}
    r2060 = rows(HardwareInfo("RTX 2060", 6144, 16384))
    assert r2060["acestep-v1-3.5b"]["fit"] == "tight" and r2060["acestep-v1-3.5b"]["best"]
    assert r2060["stable-audio-open-small"]["fit"] == "great" and r2060["stable-audio-open-small"]["lightest"]
    r5090 = rows(HardwareInfo("RTX 5090", 32768, 65536))
    assert all(r["fit"] == "great" for r in r5090.values()) and r5090["acestep-v1-3.5b"]["recommended"]
    cpu = rows(HardwareInfo(None, None, 16384))
    assert cpu["stable-audio-open-small"]["recommended"] and not cpu["acestep-v1-3.5b"]["recommended"]   # a big model would crawl on CPU
    assert all(r["fit"] == "cpu" for r in cpu.values())
    low_ram = rows(HardwareInfo("RTX 2060", 6144, 4096))
    assert low_ram["acestep-v1-3.5b"]["fit"] == "no"


def test_refresh_catalog_from_server_and_ignores_bad_entries(server, tmp_path):
    good = dict(id="new-model", name="New", role="speech", backend="kokoro", sources=[{"type": "hf_repo", "repo": "a/b"}])
    bad = dict(id="evil", name="Evil", role="music", backend="b", sources=[{"type": "url", "url": "https://evil.example.com/x"}])
    base = server({}, {"/catalog.json": (200, json.dumps({"schema": 1, "updated": "t", "entries": [bad, good]}).encode())})
    c = catalog.CatalogStore(cache=tmp_path / "cache.json")
    assert c.refresh(base + "/catalog.json", allow_local_http=True) == 1
    assert [e.id for e in c.entries()] == ["new-model"] and c.source == "downloaded list"
    again = catalog.CatalogStore(cache=tmp_path / "cache.json")        # cached for the next start
    assert [e.id for e in again.entries()] == ["new-model"]


def test_garbage_catalog_is_rejected(server, tmp_path):
    base = server({}, {"/catalog.json": (200, b'{"schema": 2, "entries": []}')})
    c = catalog.CatalogStore(cache=tmp_path / "cache.json")
    with pytest.raises(ValueError):
        c.refresh(base + "/catalog.json", allow_local_http=True)
    assert len(c.entries()) >= 5                                         # the built-in list is untouched


# ---------------------------------------------------------------- downloader
def test_download_verifies_and_lists_without_hf_website(server, tmp_path):
    files = {"model.safetensors": safetensors_bytes(), "config.json": b'{"a": 1}'}
    base = server(files)
    got = downloader.install_sources([{"type": "hf_repo", "repo": "test/repo"}], tmp_path / "m", hf_base=base, allow_local_http=True)
    assert set(got) == set(files) and (tmp_path / "m" / "config.json").read_bytes() == b'{"a": 1}'
    assert got["model.safetensors"] == hashlib.sha256(files["model.safetensors"]).hexdigest()


def test_tampered_download_is_rejected_and_deleted(server, tmp_path):
    data = safetensors_bytes()
    base = server({"model.safetensors": data})
    # the listing promises the hash of `data`, but the file route serves different bytes of the same size
    real = downloader.list_hf_files("test/repo", hf_base=base, allow_local_http=True)
    bad = bytearray(data); bad[-1] = 1
    base2 = server({"model.safetensors": bytes(bad)})
    url = f"{base2}/test/repo/resolve/main/model.safetensors"
    with pytest.raises(downloader.DownloadError, match="checksum"):
        downloader.download_file(url, tmp_path / "m.safetensors", real[0]["size"], sha256=real[0]["sha256"], allow_local_http=True)
    assert not (tmp_path / "m.safetensors").exists() and not (tmp_path / "m.safetensors.part").exists()


def test_download_resumes_a_partial_file(server, tmp_path):
    data = safetensors_bytes() * 50
    base = server({"model.safetensors": data})
    dest = tmp_path / "x" / "model.safetensors"
    dest.parent.mkdir()
    (tmp_path / "x" / "model.safetensors.part").write_bytes(data[:100])
    digest = downloader.download_file(f"{base}/test/repo/resolve/main/model.safetensors", dest, len(data),
                                      sha256=hashlib.sha256(data).hexdigest(), allow_local_http=True)
    assert dest.read_bytes() == data and digest == hashlib.sha256(data).hexdigest()


def test_download_can_be_cancelled(server, tmp_path):
    base = server({"model.safetensors": safetensors_bytes() * 2000})
    with pytest.raises(Cancelled):
        downloader.download_file(f"{base}/test/repo/resolve/main/model.safetensors", tmp_path / "m", cancel=lambda: True,
                                 allow_local_http=True)


def test_disallowed_hosts_are_refused(tmp_path):
    for url in ("https://evil.example.com/m.bin", "http://huggingface.co/m.bin", "https://huggingface.co.evil.com/m"):
        with pytest.raises(netutil.HostNotAllowed):
            netutil.open_url(url)
    assert netutil.host_allowed("https://cdn-lfs.hf.co/x") and netutil.host_allowed("https://huggingface.co/x")
    assert not netutil.host_allowed("https://nothuggingface.co/x")


def test_redirect_to_another_host_is_blocked(tmp_path):
    class R(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            self.send_response(302); self.send_header("Location", "https://evil.example.com/steal"); self.end_headers()
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), R)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        with pytest.raises(netutil.HostNotAllowed):
            netutil.open_url(f"http://127.0.0.1:{s.server_port}/x", allow_local_http=True)
    finally:
        s.shutdown()


# ---------------------------------------------------------------- safety scanner
def test_malicious_pickles_are_blocked_in_old_and_new_formats(tmp_path):
    for i, proto in enumerate((2, 4)):
        (tmp_path / f"evil{i}.pt").write_bytes(pickle.dumps(Evil(), protocol=proto))
    rep = safety.scan_folder(tmp_path)
    assert rep.verdict == "blocked" and sum(f.level == "block" for f in rep.findings) == 2


def test_torch_style_zip_checkpoint_with_evil_pickle_is_blocked(tmp_path):
    with zipfile.ZipFile(tmp_path / "model.ckpt", "w") as z:
        z.writestr("archive/data.pkl", pickle.dumps(Evil(), protocol=2))
        z.writestr("archive/data/0", b"\x00" * 16)
    assert safety.scan_folder(tmp_path).verdict == "blocked"


def test_normal_weights_pass(tmp_path):
    import collections
    (tmp_path / "ok.pth").write_bytes(pickle.dumps(collections.OrderedDict(a=1), protocol=2))
    (tmp_path / "m.safetensors").write_bytes(safetensors_bytes())
    rep = safety.scan_folder(tmp_path)
    assert rep.verdict == "clean" and rep.files == 2


def test_structural_checks(tmp_path):
    (tmp_path / "trunc.safetensors").write_bytes(safetensors_bytes()[:-4])             # tensor points past the end
    (tmp_path / "huge.safetensors").write_bytes(struct.pack("<Q", 2**40) + b"{}")
    (tmp_path / "bad.gguf").write_bytes(b"NOPE" + b"\x00" * 30)
    (tmp_path / "good.gguf").write_bytes(b"GGUF" + struct.pack("<IQQ", 3, 10, 5) + b"\x00" * 100)
    rep = safety.scan_folder(tmp_path)
    blocked = {f.file for f in rep.findings if f.level == "block"}
    assert blocked == {"trunc.safetensors", "huge.safetensors", "bad.gguf"}


def test_executables_scripts_symlinks_and_zip_slip(tmp_path):
    (tmp_path / "run.exe").write_bytes(b"MZ")
    (tmp_path / "setup.sh").write_text("rm -rf /")
    (tmp_path / "modeling.py").write_text("print('hi')")
    os.symlink("/etc/passwd", tmp_path / "link.bin")
    with zipfile.ZipFile(tmp_path / "pack.zip", "w") as z:
        z.writestr("../../escape.txt", "x")
    levels = {f.file: f.level for f in safety.scan_folder(tmp_path).findings}
    assert levels["run.exe"] == levels["setup.sh"] == levels["link.bin"] == levels["pack.zip"] == "block"
    assert levels["modeling.py"] == "warn"


def test_hashes_and_main_file(tmp_path):
    (tmp_path / "small.json").write_text("{}")
    (tmp_path / "big.safetensors").write_bytes(safetensors_bytes() * 20)
    rep = safety.scan_folder(tmp_path, hash_files=True)
    rel, sha = rep.main_file()
    assert rel == "big.safetensors" and sha == hashlib.sha256((tmp_path / rel).read_bytes()).hexdigest()


def test_os_antivirus_wrapper(tmp_path, monkeypatch):
    for code, want in ((0, "clean"), (1, "threat"), (2, "error")):
        exe = tmp_path / f"clamscan{code}"
        exe.write_text(f"#!/bin/sh\necho result-{code}\nexit {code}\n")
        exe.chmod(0o755)
        monkeypatch.setattr(safety.shutil, "which", lambda name, e=exe: str(e) if name == "clamscan" else None)
        monkeypatch.setattr(safety.os, "name", "posix")
        assert safety.os_scan(tmp_path).status == want
    monkeypatch.setattr(safety.shutil, "which", lambda name: None)
    r = safety.os_scan(tmp_path)
    assert r.status == "unavailable" and "clamav" in r.detail.lower()


# ---------------------------------------------------------------- VirusTotal
def test_virustotal_link_and_lookup(server):
    sha = "a" * 64
    assert virustotal.gui_url(sha) == f"https://www.virustotal.com/gui/file/{sha}"
    with pytest.raises(ValueError):
        virustotal.gui_url("not-a-hash")
    assert virustotal.lookup(sha, api_key="").status == "no_key"            # link only, no network
    ok = json.dumps({"data": {"attributes": {"last_analysis_stats": {"malicious": 0, "suspicious": 1, "harmless": 60, "undetected": 9}}}}).encode()
    base = server({}, {f"/api/v3/files/{sha}": (200, ok), f"/api/v3/files/{'b' * 64}": (404, b"{}"), f"/api/v3/files/{'c' * 64}": (429, b"{}")})
    # point the helper at the local server (host allowlist is bypassed only for localhost in tests)
    from sudo_make_music import netutil as nu
    orig = nu.fetch_json
    nu_fetch = lambda url, **kw: orig(url, **{**kw, "suffixes": ("127.0.0.1",), "allow_local_http": True})
    import sudo_make_music.virustotal as vt
    vt.netutil.fetch_json = nu_fetch
    try:
        r = vt.lookup(sha, "key", api_base=base + "/api/v3")
        assert r.status == "found" and r.suspicious == 1 and "1 suspicious" in r.summary()
        assert vt.lookup("b" * 64, "key", api_base=base + "/api/v3").status == "unknown"
        assert vt.lookup("c" * 64, "key", api_base=base + "/api/v3").status == "rate_limited"
    finally:
        vt.netutil.fetch_json = orig


# ---------------------------------------------------------------- one-click install through the engine
def test_install_end_to_end(engine, server):
    files = {"model.safetensors": safetensors_bytes(), "config.json": b"{}"}
    engine.hf_base = server(files)
    engine.catalog._entries.append(make_entry(backend="mock", role="music"))
    t = engine.start_install("test-model")
    t = wait_task(engine)
    assert t.status == "done", t.message
    assert engine.models.get("test-model") and (Path(engine.models.get("test-model").path) / "model.safetensors").exists()
    meta = engine.models.meta("test-model")
    assert meta["catalog_id"] == "test-model" and meta["scan"] == "clean" and "model.safetensors" in meta["files_sha256"]
    assert engine.store.value.models["mock"] == "test-model"
    rows = {r["id"]: r for r in engine.catalog_rows()}
    assert rows["test-model"]["installed"]
    scan = engine.scan_model("test-model", use_os=False)
    assert scan["verdict"] == "clean" and len(scan["sha256"]) == 64


def test_install_blocks_and_deletes_a_malicious_download(engine, server):
    engine.hf_base = server({"weights.pt": pickle.dumps(Evil(), protocol=2)})
    engine.catalog._entries.append(make_entry(backend="mock", role="music"))
    engine.start_install("test-model")
    t = wait_task(engine)
    assert t.status == "error" and "blocked" in t.message.lower()
    assert engine.models.get("test-model") is None
    assert not (Path(engine.models.root) / "test-model").exists() and not (Path(engine.models.root) / "test-model.partial").exists()


def test_install_quarantines_when_antivirus_finds_a_threat(engine, server, monkeypatch):
    engine.store.value.scan_after_download = True
    monkeypatch.setattr(safety, "os_scan", lambda p, timeout=0: safety.OsScan("threat", "TestAV", "Eicar-Test"))
    engine.hf_base = server({"model.safetensors": safetensors_bytes()})
    engine.catalog._entries.append(make_entry(backend="mock", role="music"))
    engine.start_install("test-model")
    t = wait_task(engine)
    assert t.status == "error" and "TestAV" in t.message
    assert engine.models.get("test-model") is None and (Path(engine.models.root) / "_quarantine" / "test-model").exists()


def test_gated_model_needs_token(engine, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    engine.catalog._entries.append(make_entry(backend="mock", role="music", gated=True, homepage="https://huggingface.co/x/y"))
    engine.start_install("test-model")
    t = wait_task(engine)
    assert t.status == "error" and "HF_TOKEN" in t.message


def test_offline_mode_disables_network_features(engine):
    engine.store.value.update({"offline_mode": True})
    for call in (lambda: engine.refresh_catalog(), lambda: engine.start_install("acestep-v1-3.5b"), lambda: engine.vt_lookup("a" * 64)):
        with pytest.raises(RuntimeError, match="Offline mode"):
            call()
    assert engine.scan_folder_path(str(engine.models.root), use_os=False)["verdict"] == "clean"      # local scan still works


def test_import_refuses_a_booby_trapped_folder(engine, tmp_path):
    bad = tmp_path / "bad-model"
    bad.mkdir()
    (bad / "weights.pt").write_bytes(pickle.dumps(Evil(), protocol=2))
    with pytest.raises(ValueError, match="safety check blocked"):
        engine.import_model(str(bad), "mock", "Bad")
    assert engine.models.list() == []
    engine.import_model(str(bad), "mock", "Bad", force=True)          # an explicit override still exists
    assert len(engine.models.list()) == 1
