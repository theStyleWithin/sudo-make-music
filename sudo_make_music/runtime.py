"""User-space install of the heavy AI libraries (torch, ACE-Step).

Torch+CUDA is multiple GB, so packages (AppImage, Flatpak, AUR, Windows zip) ship only the light
app and install the backend once into a per-user directory. Needs internet that one time; after
that (and after the model download) everything runs offline.
"""
from __future__ import annotations

import os
import site
import subprocess
import sys
import threading
from pathlib import Path

from . import paths

TORCH_INDEXES = {
    "cu126": "https://download.pytorch.org/whl/cu126",
    "cu124": "https://download.pytorch.org/whl/cu124",
    "cu121": "https://download.pytorch.org/whl/cu121",
    "cpu": "https://download.pytorch.org/whl/cpu",
}
ACESTEP_SRC = "https://github.com/ace-step/ACE-Step/archive/refs/heads/main.zip"


def libs_dir() -> Path:
    return paths.home() / f"pylibs-py{sys.version_info.major}{sys.version_info.minor}"


def activate() -> None:
    """Make previously installed backend libs importable. Call once at startup."""
    d = libs_dir()
    if d.is_dir():
        site.addsitedir(str(d))


def install_commands(cuda: str = "cu126", speech: bool = False) -> list[list[str]]:
    if cuda not in TORCH_INDEXES:
        raise ValueError(f"cuda must be one of {sorted(TORCH_INDEXES)}")
    # Frozen (PyInstaller) exe has no `python -m`; the launcher understands --run-module instead.
    py = [sys.executable, "--run-module", "pip"] if getattr(sys, "frozen", False) else [sys.executable, "-m", "pip"]
    base = py + ["install", "--upgrade", "--target", str(libs_dir())]
    cmds = [
        base + ["torch", "torchaudio", "--index-url", TORCH_INDEXES[cuda]],
        base + ["soundfile", "torchao", ACESTEP_SRC],
    ]
    if speech:   # talk mode: Kokoro (presets) + Chatterbox (voice cloning). May re-pin torch versions.
        cmds.append(base + ["kokoro", "chatterbox-tts", "soundfile"])
    return cmds


class Installer:
    """Runs the pip installs in a thread; the UI polls `snapshot()`."""

    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.ok: bool | None = None
        self.log: list[str] = []

    def start(self, cuda: str = "cu126", speech: bool = False) -> None:
        cmds = install_commands(cuda, speech)
        with self.lock:
            if self.running:
                raise RuntimeError("install already running")
            self.running, self.ok, self.log = True, None, []
        threading.Thread(target=self._run, args=(cmds,), daemon=True).start()

    def _run(self, cmds) -> None:
        ok = True
        try:
            libs_dir().mkdir(parents=True, exist_ok=True)
            for cmd in cmds:
                self.log.append("$ " + " ".join(cmd))
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                     env={**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1"})
                for line in p.stdout:
                    self.log.append(line.rstrip())
                if p.wait() != 0:
                    ok = False
                    break
            if ok:
                activate()
        except Exception as e:
            self.log.append(f"error: {e}")
            ok = False
        finally:
            with self.lock:
                self.running, self.ok = False, ok

    def snapshot(self) -> dict:
        return dict(running=self.running, ok=self.ok, log=self.log[-60:])
