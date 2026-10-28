"""Local model store. Every model is a folder under <data>/models/<id>/ containing
`smm-model.json` ({"backend": "...", "name": "..."}) plus the backend's own files.
Models are plain folders: copy one in, delete one, or import from anywhere on disk. No network needed."""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, asdict
from pathlib import Path

from . import paths

MANIFEST = "smm-model.json"


@dataclass
class ModelInfo:
    id: str
    name: str
    backend: str
    path: str
    size_mb: int

    def to_dict(self) -> dict:
        return asdict(self)


def _size_mb(p: Path) -> int:
    return int(sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 1e6)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", s.lower()).strip("-") or "model"


class ModelStore:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else paths.models_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    def list(self, backend: str | None = None) -> list[ModelInfo]:
        out = []
        for d in sorted(self.root.iterdir()):
            m = d / MANIFEST
            if not (d.is_dir() and m.is_file()):
                continue
            try:
                meta = json.loads(m.read_text())
                info = ModelInfo(d.name, meta.get("name", d.name), meta["backend"], str(d), _size_mb(d))
            except (OSError, ValueError, KeyError):
                continue
            if backend in (None, info.backend):
                out.append(info)
        return out

    def get(self, model_id: str) -> ModelInfo | None:
        return next((m for m in self.list() if m.id == model_id), None)

    def register(self, folder: Path, backend: str, name: str) -> ModelInfo:
        """Mark an existing folder under the store as a model (used for auto-created default dirs)."""
        folder.mkdir(parents=True, exist_ok=True)
        (folder / MANIFEST).write_text(json.dumps({"backend": backend, "name": name}))
        return self.get(folder.name)  # type: ignore[return-value]

    def import_folder(self, src: Path, backend: str, name: str | None = None, link: bool = False) -> ModelInfo:
        """Import a model folder from anywhere on disk (USB stick, another drive...).
        link=True symlinks instead of copying, to save disk space on big models."""
        src = Path(src).expanduser().resolve()
        if not src.is_dir():
            raise ValueError(f"not a folder: {src}")
        manifest = src / MANIFEST
        if manifest.is_file():
            meta = json.loads(manifest.read_text())
            backend = meta.get("backend", backend)
            name = name or meta.get("name")
        name = name or src.name
        dst = self.root / _slug(name)
        n = 2
        while dst.exists():
            dst = self.root / f"{_slug(name)}-{n}"
            n += 1
        if link:
            dst.symlink_to(src, target_is_directory=True)
            if not (dst / MANIFEST).exists():  # cannot write into the user's original folder
                dst.unlink()
                raise ValueError("linking needs the source folder to already contain smm-model.json; import by copy instead")
        else:
            shutil.copytree(src, dst)
            (dst / MANIFEST).write_text(json.dumps({"backend": backend, "name": name}))
        return self.get(dst.name)  # type: ignore[return-value]

    def delete(self, model_id: str) -> None:
        m = self.get(model_id)
        if not m:
            raise ValueError("no such model")
        p = Path(m.path)
        if p.is_symlink():
            p.unlink()
        else:
            shutil.rmtree(p)
