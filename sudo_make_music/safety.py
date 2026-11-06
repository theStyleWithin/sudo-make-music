"""Built-in safety checks for model files, with no antivirus engine needed.

What actually goes wrong with downloaded AI models is not classic viruses but:
  * pickle-based weights (.pt .pth .ckpt .bin .th): loading one can run arbitrary code. We read the pickle's opcodes
    WITHOUT executing it and flag imports like os/subprocess/eval.
  * executables or scripts hiding in a model folder or archive.
  * corrupt or truncated files, and archives that try to write outside their folder.
Safe formats (safetensors, GGUF) are checked structurally. The operating system's antivirus (Windows Defender, ClamAV) can
be run on top, and a SHA-256 is computed so the file can be looked up on VirusTotal."""
from __future__ import annotations

import hashlib
import json
import os
import pickletools
import shutil
import struct
import subprocess
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

BLOCK_EXT = {".exe", ".dll", ".bat", ".cmd", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".msi", ".scr", ".com",
             ".jar", ".apk", ".lnk", ".sh", ".so", ".dylib", ".pyd", ".app", ".dmg", ".pkg", ".deb", ".rpm", ".appimage"}
CODE_EXT = {".py", ".pyc"}
PICKLE_EXT = {".pt", ".pth", ".ckpt", ".bin", ".pkl", ".pickle", ".th"}
ARCHIVE_EXT = {".zip", ".tar", ".tgz", ".gz", ".bz2", ".xz", ".7z", ".rar"}

DANGEROUS_MODULES = {"os", "posix", "nt", "subprocess", "sys", "socket", "shutil", "importlib", "runpy", "pty", "webbrowser",
                     "ctypes", "pickle", "marshal", "code", "codeop", "platform", "urllib", "http", "ftplib", "smtplib",
                     "telnetlib", "requests", "asyncio", "multiprocessing", "threading", "signal", "pip", "setuptools",
                     "commands", "tempfile", "glob", "io", "builtins_exec"}
SAFE_BUILTINS = {"set", "frozenset", "slice", "range", "bytearray", "complex", "list", "dict", "tuple", "int", "float",
                 "str", "bytes", "object", "bool", "type"}
SAFE_MODULES = {"torch", "collections", "numpy", "_codecs", "copyreg", "typing", "dataclasses", "omegaconf", "pytorch_lightning"}
MAX_PICKLE_SCAN = 64 * 1024 * 1024
LEVELS = {"info": 0, "warn": 1, "block": 2}


@dataclass
class Finding:
    level: str      # info | warn | block
    file: str
    message: str


@dataclass
class ScanReport:
    root: str
    findings: list = field(default_factory=list)
    files: int = 0
    total_bytes: int = 0
    hashes: dict = field(default_factory=dict)       # relative path -> sha256 (only when requested)

    @property
    def verdict(self) -> str:
        worst = max((LEVELS[f.level] for f in self.findings), default=-1)
        return "blocked" if worst == 2 else "warnings" if worst == 1 else "clean"

    def add(self, level: str, file: str, message: str) -> None:
        self.findings.append(Finding(level, file, message))

    def to_text(self, max_lines: int = 30) -> str:
        head = {"clean": "No problems found.", "warnings": "Some things to be aware of:",
                "blocked": "BLOCKED - do not use this model:"}[self.verdict]
        lines = [f"{head}  ({self.files} files, {self.total_bytes / 1e6:.0f} MB)"]
        for f in sorted(self.findings, key=lambda f: -LEVELS[f.level])[:max_lines]:
            lines.append(f"[{f.level.upper()}] {f.file}: {f.message}")
        if len(self.findings) > max_lines:
            lines.append(f"... and {len(self.findings) - max_lines} more")
        return "\n".join(lines)

    def main_file(self) -> tuple[str, str] | None:
        """(relative path, sha256) of the biggest hashed file: what to look up on VirusTotal."""
        if not self.hashes:
            return None
        root = Path(self.root)
        rel = max(self.hashes, key=lambda r: (root / r).stat().st_size if (root / r).exists() else 0)
        return rel, self.hashes[rel]


# ------------------------------------------------------------------ pickle
def classify_global(module: str, name: str) -> str:
    top = module.split(".")[0]
    if module in ("builtins", "__builtin__"):
        return "ok" if name in SAFE_BUILTINS else "block"
    if top == "numpy" and module.startswith("numpy.testing"):
        return "block"                      # numpy.testing._private.utils.runstring runs exec()
    if top in DANGEROUS_MODULES:
        return "block"
    if top in SAFE_MODULES:
        return "ok"
    return "unknown"


def scan_pickle_stream(fh, limit: int = MAX_PICKLE_SCAN) -> tuple[list, list, bool]:
    """Returns (dangerous 'module.name' list, unknown list, parsed_ok). Never executes the pickle."""
    dangerous, unknown, recent, memo = [], [], [], {}
    start = fh.tell() if hasattr(fh, "tell") else 0
    try:
        for op, arg, pos in pickletools.genops(fh):
            if pos is not None and pos - start > limit:
                return dangerous, unknown, False
            n = op.name
            if n in ("SHORT_BINUNICODE", "BINUNICODE", "UNICODE", "BINUNICODE8"):
                recent.append(arg)
            elif n == "MEMOIZE" and recent:
                memo[len(memo)] = recent[-1]
            elif n in ("PUT", "BINPUT", "LONG_BINPUT") and recent:
                memo[arg] = recent[-1]
            elif n in ("GET", "BINGET", "LONG_BINGET") and arg in memo:
                recent.append(memo[arg])
            elif n in ("GLOBAL", "INST"):
                mod, _, name = str(arg).partition(" ")
                (dangerous if classify_global(mod, name) == "block" else unknown if classify_global(mod, name) == "unknown" else []).append(f"{mod}.{name}")
            elif n == "STACK_GLOBAL" and len(recent) >= 2:
                mod, name = recent[-2], recent[-1]
                c = classify_global(mod, name)
                if c == "block":
                    dangerous.append(f"{mod}.{name}")
                elif c == "unknown":
                    unknown.append(f"{mod}.{name}")
            recent = recent[-8:]
    except Exception:
        return dangerous, unknown, False
    return dangerous, unknown, True


def scan_pickle_file(path: Path, rel: str, report: ScanReport) -> None:
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                pkls = [n for n in z.namelist() if n.endswith(".pkl")]
                if not pkls:
                    report.add("info", rel, "zip archive without a pickle inside (likely tensors only)")
                    return
                for n in pkls:
                    if z.getinfo(n).file_size > MAX_PICKLE_SCAN:
                        report.add("warn", rel, f"{n} is too large to scan")
                        continue
                    with z.open(n) as fh:
                        data = fh.read()
                    from io import BytesIO
                    d, u, ok = scan_pickle_stream(BytesIO(data))
                    _report_pickle(report, rel, d, u, ok)
        else:
            with open(path, "rb") as fh:
                d, u, ok = scan_pickle_stream(fh)
            _report_pickle(report, rel, d, u, ok)
    except (OSError, zipfile.BadZipFile) as e:
        report.add("warn", rel, f"could not read: {e}")


def _report_pickle(report: ScanReport, rel: str, dangerous: list, unknown: list, ok: bool) -> None:
    if dangerous:
        report.add("block", rel, "pickle imports dangerous code: " + ", ".join(sorted(set(dangerous))[:6]))
    elif not ok:
        report.add("warn", rel, "pickle-format weights that could not be fully analysed; load only from a publisher you trust")
    elif unknown:
        report.add("warn", rel, "pickle-format weights importing unusual code: " + ", ".join(sorted(set(unknown))[:6]))
    else:
        report.add("info", rel, "pickle-format weights (analysed: only normal tensor code). Safer formats are safetensors / GGUF.")


# ------------------------------------------------------------------ structural checks
def check_safetensors(path: Path, rel: str, report: ScanReport) -> None:
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            raw = fh.read(8)
            if len(raw) < 8:
                return report.add("block", rel, "safetensors file is truncated")
            (n,) = struct.unpack("<Q", raw)
            if n > 100_000_000 or 8 + n > size:
                return report.add("block", rel, "safetensors header length is impossible (corrupt or malicious)")
            header = json.loads(fh.read(n))
        data_size = size - 8 - n
        for k, v in header.items():
            if k == "__metadata__":
                continue
            a, b = v["data_offsets"]
            if not (0 <= a <= b <= data_size):
                return report.add("block", rel, f"tensor '{k}' points outside the file (corrupt or truncated)")
    except Exception as e:
        report.add("block", rel, f"not a valid safetensors file ({type(e).__name__})")


def check_gguf(path: Path, rel: str, report: ScanReport) -> None:
    try:
        with open(path, "rb") as fh:
            head = fh.read(24)
        if head[:4] != b"GGUF":
            return report.add("block", rel, "not a GGUF file (missing magic bytes)")
        version, tensors, kv = struct.unpack("<IQQ", head[4:24])
        if not (1 <= version <= 3) or tensors > 1_000_000 or kv > 1_000_000:
            report.add("block", rel, "GGUF header values are implausible (corrupt or malicious)")
    except Exception as e:
        report.add("block", rel, f"not a valid GGUF file ({type(e).__name__})")


def check_archive(path: Path, rel: str, report: ScanReport) -> None:
    names: list[str] = []
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
        elif tarfile.is_tarfile(path):
            with tarfile.open(path) as t:
                names = [m.name for m in t.getmembers()]
        else:
            return report.add("warn", rel, "archive format cannot be inspected here; extract and scan it first")
    except Exception as e:
        return report.add("warn", rel, f"could not read archive: {e}")
    for n in names:
        parts = Path(n).parts
        if n.startswith(("/", "\\")) or ".." in parts or (len(n) > 1 and n[1] == ":"):
            return report.add("block", rel, f"archive entry escapes its folder: {n}")
    bad = [n for n in names if Path(n).suffix.lower() in BLOCK_EXT]
    if bad:
        report.add("block", rel, "archive contains executable/script files: " + ", ".join(bad[:5]))


def sha256_file(path: Path, progress=None, cancel=None) -> str:
    h = hashlib.sha256()
    done = 0
    with open(path, "rb") as fh:
        while chunk := fh.read(8 * 1024 * 1024):
            if cancel and cancel():
                raise InterruptedError("cancelled")
            h.update(chunk)
            done += len(chunk)
            if progress:
                progress(done)
    return h.hexdigest()


def scan_folder(root: Path, hash_files: bool = False, cancel=None, max_files: int = 20000) -> ScanReport:
    root = Path(root)
    rep = ScanReport(str(root))
    if not root.is_dir():
        rep.add("block", str(root), "not a folder")
        return rep
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        if cancel and cancel():
            raise InterruptedError("cancelled")
        if p.is_symlink():
            rep.add("block", rel, "symbolic link (could point outside the model folder)")
            continue
        if p.is_dir():
            continue
        rep.files += 1
        if rep.files > max_files:
            rep.add("block", str(root), f"more than {max_files} files")
            break
        size = p.stat().st_size
        rep.total_bytes += size
        ext = p.suffix.lower()
        if ext in BLOCK_EXT:
            rep.add("block", rel, f"executable/native file type ({ext}) has no place in a model")
        elif ext in CODE_EXT:
            rep.add("warn", rel, "Python code file (this app does not run code from model folders)")
        elif ext == ".safetensors":
            check_safetensors(p, rel, rep)
        elif ext == ".gguf":
            check_gguf(p, rel, rep)
        elif ext in PICKLE_EXT:
            scan_pickle_file(p, rel, rep)
        elif ext in ARCHIVE_EXT:
            check_archive(p, rel, rep)
        if hash_files:
            rep.hashes[rel] = sha256_file(p, cancel=cancel)
    return rep


# ------------------------------------------------------------------ operating-system antivirus
@dataclass
class OsScan:
    status: str      # clean | threat | unavailable | error
    engine: str
    detail: str


def _windows_defender() -> str | None:
    cands = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Windows Defender" / "MpCmdRun.exe"]
    plat = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft" / "Windows Defender" / "Platform"
    if plat.is_dir():
        cands = sorted(plat.glob("*/MpCmdRun.exe"), reverse=True) + cands
    return next((str(c) for c in cands if c.is_file()), None)


def os_scan(path: Path, timeout: int = 1800) -> OsScan:
    """Ask the antivirus already on this computer to scan a file or folder. Nothing is uploaded anywhere."""
    path = str(path)
    if os.name == "nt":
        exe = _windows_defender()
        if not exe:
            return OsScan("unavailable", "Windows Defender", "MpCmdRun.exe not found (is another antivirus installed?)")
        cmd, engine = [exe, "-Scan", "-ScanType", "3", "-File", path, "-DisableRemediation"], "Windows Defender"
        threat_codes = {2}
    else:
        clam = shutil.which("clamdscan") or shutil.which("clamscan")
        if not clam:
            return OsScan("unavailable", "ClamAV", "ClamAV is not installed (Arch: sudo pacman -S clamav; Debian/Ubuntu: sudo apt install clamav)")
        cmd = [clam, "--no-summary", path] if clam.endswith("clamdscan") else [clam, "-r", "--no-summary", path]
        engine, threat_codes = "ClamAV", {1}
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return OsScan("error", engine, "scan timed out")
    except OSError as e:
        return OsScan("error", engine, str(e))
    out = (r.stdout + r.stderr).strip()[-600:]
    if r.returncode == 0:
        return OsScan("clean", engine, "no threats found")
    if r.returncode in threat_codes:
        return OsScan("threat", engine, out or "threat found")
    return OsScan("error", engine, out or f"scanner exited with code {r.returncode}")
