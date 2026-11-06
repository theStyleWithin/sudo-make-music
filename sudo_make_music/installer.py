"""One-click install of a catalog entry: offline check -> download (hash-verified) -> safety scan -> OS antivirus -> register."""
from __future__ import annotations

import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import downloader, paths, safety
from .backends.base import Cancelled

ROLE_ATTR = {"music": "backend", "speech": "speech_backend", "converter": "converter_backend", "separator": "separator_backend"}


@dataclass
class InstallTask:
    entry_id: str
    name: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    status: str = "running"          # running | done | error | cancelled
    message: str = "starting"
    progress: float = 0.0
    report: str = ""                 # safety report text
    model_id: str = ""
    cancel: threading.Event = field(default_factory=threading.Event)


def start(engine, entry) -> InstallTask:
    task = InstallTask(entry.id, entry.name)
    threading.Thread(target=_run, args=(engine, entry, task), daemon=True, name="smm-install").start()
    return task


def _run(engine, entry, task: InstallTask) -> None:
    final = paths.models_dir() / entry.id
    partial = paths.models_dir() / f"{entry.id}.partial"
    try:
        token = os.environ.get("HF_TOKEN") or None
        if entry.gated and not token:
            raise downloader.DownloadError(
                f"{entry.name} is gated: open {entry.homepage or 'its Hugging Face page'}, accept the licence, then set the "
                "HF_TOKEN environment variable and try again.")
        task.message = "downloading"

        def prog(done, total):
            task.progress = (done / total * 0.9) if total else 0.0
            task.message = f"downloading {done / 1e6:.0f} of {total / 1e6:.0f} MB" if total else f"downloading {done / 1e6:.0f} MB"

        hashes = downloader.install_sources(entry.sources, partial, token, prog, task.cancel.is_set,
                                            engine.hf_base, engine.allow_local_http)
        task.message, task.progress = "checking the files", 0.92
        rep = safety.scan_folder(partial, cancel=task.cancel.is_set)
        task.report = rep.to_text()
        if rep.verdict == "blocked":
            shutil.rmtree(partial, ignore_errors=True)
            raise downloader.DownloadError("the safety check blocked this download, so it was deleted:\n" + rep.to_text(8))
        os_note = ""
        if engine.store.value.scan_after_download:
            task.message, task.progress = "running your antivirus", 0.96
            res = safety.os_scan(partial)
            os_note = f"\n{res.engine}: {res.detail}"
            if res.status == "threat":
                q = paths.models_dir() / "_quarantine" / entry.id
                shutil.rmtree(q, ignore_errors=True)
                q.parent.mkdir(exist_ok=True)
                shutil.move(str(partial), str(q))
                raise downloader.DownloadError(f"{res.engine} reported a threat, so the download was moved to {q} (not usable):\n{res.detail}")
        task.report += os_note
        if final.exists():
            shutil.rmtree(final)
        os.replace(partial, final)
        info = engine.models.register(final, entry.backend, entry.name,
                                      {"catalog_id": entry.id, "files_sha256": hashes, "scan": rep.verdict, "license": entry.license})
        engine.store.value.models[entry.backend] = info.id
        attr = ROLE_ATTR.get(entry.role)
        if attr:                                          # use it right away if the role has no usable model yet
            cur = getattr(engine.store.value, attr)
            try:
                b = engine._backend(cur)
                has_model = b.model_present(engine._find_model(b))
            except Exception:
                has_model = False
            if cur != entry.backend and not has_model:
                setattr(engine.store.value, attr, entry.backend)
        engine.store.save()
        task.model_id, task.progress, task.status = info.id, 1.0, "done"
        task.message = "installed and ready" if entry.backend in _available(engine) else \
            "installed. The engine for it is not installed yet: see Settings > Install ... buttons."
    except Cancelled:
        task.status, task.message = "cancelled", "cancelled (partial download kept so you can resume)"
    except InterruptedError:
        task.status, task.message = "cancelled", "cancelled"
    except Exception as e:
        task.status, task.message = "error", str(e)[:900]


def _available(engine) -> set:
    from .backends import registry
    return {bid for bid, cls in registry().items() if cls.available()[0]}
