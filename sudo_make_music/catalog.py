"""The model list behind the Models tab: a bundled JSON file that can be refreshed online, plus hardware fit/recommendation.

GGUF is not required: any format is listed, each entry says which backend (engine) runs it."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

from . import netutil, paths
from .hardware import HardwareInfo

DEFAULT_CATALOG_URL = "https://raw.githubusercontent.com/theStyleWithin/sudo-make-music/main/sudo_make_music/data/catalog.json"
ROLES = ("music", "speech", "converter", "separator")
ROLE_LABELS = {"music": "Music", "speech": "Talk voice", "converter": "Singing voice cloning", "separator": "Vocal separation"}


@dataclass
class Entry:
    id: str
    name: str
    role: str
    backend: str
    description: str = ""
    license: str = ""
    size_mb: int = 0
    quality: int = 3                 # 1-5, for picking the best model that fits
    light: bool = False
    clone: bool = False
    vram_min_mb: int = 0             # smallest GPU memory it runs on (with offload/int8)
    vram_good_mb: int = 0            # comfortable
    ram_min_mb: int = 8000
    cpu_ok: bool = True
    gated: bool = False
    format: str = ""
    homepage: str = ""
    notes: str = ""
    sources: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def validate_entry(d: dict, suffixes=netutil.ALLOWED_HOST_SUFFIXES, allow_local_http: bool = False) -> Entry:
    """Reject anything malformed or pointing at hosts outside the allowlist (a refreshed list is untrusted input)."""
    if not isinstance(d, dict):
        raise ValueError("entry is not an object")
    known = {k for k in Entry.__dataclass_fields__}
    e = Entry(**{k: v for k, v in d.items() if k in known})
    if not (isinstance(e.id, str) and e.id.replace("-", "").replace(".", "").replace("_", "").isalnum() and len(e.id) <= 64):
        raise ValueError(f"bad id {e.id!r}")
    if e.role not in ROLES:
        raise ValueError(f"{e.id}: unknown role {e.role!r}")
    if not isinstance(e.backend, str) or not e.backend:
        raise ValueError(f"{e.id}: missing backend")
    if not e.sources or len(e.sources) > 6:
        raise ValueError(f"{e.id}: needs 1-6 sources")
    for s in e.sources:
        t = s.get("type")
        if t == "hf_repo":
            repo = s.get("repo", "")
            if repo.count("/") != 1 or any(c in repo for c in " \\?#") or ".." in repo:
                raise ValueError(f"{e.id}: bad repo {repo!r}")
        elif t == "url":
            if not netutil.host_allowed(s.get("url", ""), suffixes, allow_local_http):
                raise ValueError(f"{e.id}: download host not allowed: {s.get('url')!r}")
        else:
            raise ValueError(f"{e.id}: unknown source type {t!r}")
        dest = s.get("dest", "")
        if dest.startswith(("/", "\\")) or ".." in Path(dest).parts:
            raise ValueError(f"{e.id}: bad dest {dest!r}")
    if e.homepage and not e.homepage.startswith("https://"):
        e.homepage = ""
    return e


# ------------------------------------------------------------------ hardware fit
@dataclass
class Fit:
    level: str    # great | tight | cpu | no
    label: str


def fit(e: Entry, hw: HardwareInfo) -> Fit:
    if hw.ram_mb is not None and hw.ram_mb < e.ram_min_mb:
        return Fit("no", f"Needs about {e.ram_min_mb // 1000} GB of RAM (this PC has {hw.ram_mb // 1000} GB)")
    if hw.vram_mb is None:
        if e.cpu_ok:
            return Fit("cpu", "No GPU found: runs on the CPU only (slow)")
        return Fit("no", "Needs a GPU")
    if hw.vram_mb >= max(e.vram_good_mb, 1):
        return Fit("great", f"Runs well on your {hw.vram_mb // 1024} GB GPU")
    if hw.vram_mb >= e.vram_min_mb:
        return Fit("tight", f"Fits your {hw.vram_mb // 1024} GB GPU with limits (use Safe memory mode)")
    if e.cpu_ok:
        return Fit("cpu", f"Too big for your {hw.vram_mb // 1024} GB GPU: would run on the CPU (slow)")
    return Fit("no", f"Needs more GPU memory than your {hw.vram_mb // 1024} GB")


def rank(entries: list[Entry], hw: HardwareInfo) -> list[dict]:
    """Entries with their fit plus flags: `best` = highest quality that fits the GPU, `lightest` = smallest, `recommended`."""
    rows = []
    for e in entries:
        f = fit(e, hw)
        rows.append(dict(e.to_dict(), fit=f.level, fit_label=f.label, best=False, lightest=False, recommended=False))
    for role in ROLES:
        group = [r for r in rows if r["role"] == role]
        fits = [r for r in group if r["fit"] in ("great", "tight")]
        cpu = [r for r in group if r["fit"] == "cpu"]
        if fits:
            best = max(fits, key=lambda r: (r["quality"], -r["vram_min_mb"]))
            best["best"] = best["recommended"] = True
            min(fits, key=lambda r: (r["vram_min_mb"], r["size_mb"]))["lightest"] = True
        elif cpu:   # CPU only: a big model would crawl, so point at the lightest one
            light = min(cpu, key=lambda r: (r["size_mb"], r["vram_min_mb"]))
            light["lightest"] = light["recommended"] = True
    order = {"great": 0, "tight": 1, "cpu": 2, "no": 3}
    rows.sort(key=lambda r: (ROLES.index(r["role"]), not r["recommended"], order[r["fit"]], -r["quality"]))
    return rows


# ------------------------------------------------------------------ store
class CatalogStore:
    def __init__(self, bundled: Path | None = None, cache: Path | None = None):
        self.bundled = bundled or Path(__file__).parent / "data" / "catalog.json"
        self.cache = cache or paths.home() / "catalog-cache.json"
        self.updated = ""
        self.source = "built-in list"
        self._entries: list[Entry] = []
        self.load()

    def _parse(self, doc: dict, **kw) -> list[Entry]:
        if doc.get("schema") != 1 or not isinstance(doc.get("entries"), list) or len(doc["entries"]) > 200:
            raise ValueError("not a catalog (schema 1)")
        out, seen = [], set()
        for d in doc["entries"]:
            try:
                e = validate_entry(d, **kw)
            except ValueError:
                continue          # skip bad entries, keep the good ones
            if e.id not in seen:
                seen.add(e.id)
                out.append(e)
        if not out:
            raise ValueError("catalog has no usable entries")
        self.updated = str(doc.get("updated", ""))
        return out

    def load(self) -> None:
        for path, label in ((self.cache, "downloaded list"), (self.bundled, "built-in list")):
            try:
                self._entries = self._parse(json.loads(Path(path).read_text(encoding="utf-8")))
                self.source = label
                return
            except (OSError, ValueError):
                continue
        self._entries = []

    def refresh(self, url: str = DEFAULT_CATALOG_URL, allow_local_http: bool = False) -> int:
        """Fetch the list online; replaces the built-in list only if every check passes. Returns the entry count."""
        doc, _ = netutil.fetch_json(url, allow_local_http=allow_local_http)
        entries = self._parse(doc, allow_local_http=allow_local_http)
        self.cache.write_text(json.dumps(doc), encoding="utf-8")
        self._entries, self.source = entries, "downloaded list"
        return len(entries)

    def entries(self) -> list[Entry]:
        return list(self._entries)

    def get(self, entry_id: str) -> Entry | None:
        return next((e for e in self._entries if e.id == entry_id), None)
