"""Where things live on disk. Override the root with SUDO_MAKE_MUSIC_HOME."""
import os
from pathlib import Path


def home() -> Path:
    root = os.environ.get("SUDO_MAKE_MUSIC_HOME")
    if root:
        p = Path(root)
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        p = Path(base) / "sudo-make-music"
    p.mkdir(parents=True, exist_ok=True)
    return p


def outputs_dir() -> Path:
    p = home() / "outputs"
    p.mkdir(exist_ok=True)
    return p


def models_dir() -> Path:
    p = home() / "models"
    p.mkdir(exist_ok=True)
    return p


def work_dir() -> Path:
    p = home() / "work"
    p.mkdir(exist_ok=True)
    return p
