"""Job engine: one generation at a time, memory-safe chunked pipeline."""
from __future__ import annotations

import gc
import logging
import queue
import random
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field

from . import hardware, memory, paths
from .audio import WavWriter, Stitcher, plan_segments, export_mp3
from .backends import registry, SegmentRequest, Cancelled
from .history import History
from .settings import SettingsStore

log = logging.getLogger(__name__)


@dataclass
class Job:
    id: str
    prompt: str
    lyrics: str
    duration: int
    seed: int
    backend: str
    params: memory.GenParams
    steps: int
    fmt: str
    status: str = "queued"      # queued running done error cancelled
    progress: float = 0.0
    message: str = ""
    segment: int = 0
    segments: int = 0
    error: str = ""
    cancel: threading.Event = field(default_factory=threading.Event)
    started: float = 0.0
    finished: float = 0.0

    def to_dict(self) -> dict:
        return dict(id=self.id, status=self.status, progress=self.progress, message=self.message,
                    segment=self.segment, segments=self.segments, error=self.error,
                    duration=self.duration, seed=self.seed, backend=self.backend,
                    mode=self.params.mode, params=self.params.to_dict())


class Engine:
    def __init__(self, store: SettingsStore | None = None, history: History | None = None):
        self.store = store or SettingsStore()
        self.history = history or History()
        self.hw = hardware.detect()
        self.jobs: dict[str, Job] = {}
        self._q: queue.Queue[Job] = queue.Queue()
        self._backends: dict = {}
        self._busy = threading.Lock()
        self._last_used = time.time()
        self._stop = threading.Event()
        threading.Thread(target=self._worker, daemon=True, name="smm-worker").start()
        threading.Thread(target=self._idle_watch, daemon=True, name="smm-idle").start()

    # ---- configuration -------------------------------------------------
    def active_mode(self) -> str:
        return self.store.value.memory_mode or memory.recommend_mode(self.hw)

    def active_params(self) -> memory.GenParams:
        s = self.store.value
        return memory.resolve(self.active_mode(), s.overrides, self.hw.vram_mb)

    def backend_infos(self) -> list[dict]:
        return [cls().info() for cls in registry().values()]

    def _backend(self, bid: str):
        if bid not in registry():
            raise ValueError(f"unknown backend {bid!r}")
        if bid not in self._backends:
            self._backends[bid] = registry()[bid]()
        return self._backends[bid]

    def status(self) -> dict:
        p = self.active_params()
        return dict(hardware=self.hw.to_dict(), mode=self.active_mode(),
                    mode_auto=self.store.value.memory_mode is None,
                    mode_description=memory.describe(p, self.hw), params=p.to_dict(),
                    modes=memory.MODES, backends=self.backend_infos(),
                    model_loaded=any(b.loaded for b in self._backends.values()),
                    free_vram_mb=hardware.free_vram_mb())

    # ---- submit / cancel -----------------------------------------------
    def submit(self, prompt: str, lyrics: str, duration: int) -> Job:
        s = self.store.value
        params = self.active_params()
        backend = self._backend(s.backend)
        ok, why = backend.available()
        if not ok:
            raise RuntimeError(why)
        if not prompt.strip():
            raise ValueError("style prompt is required")
        duration = int(min(max(5, duration), params.max_duration))
        seed = s.seed if s.seed is not None else random.randint(0, 2**31 - 1)
        job = Job(id=uuid.uuid4().hex[:12], prompt=prompt.strip(), lyrics=lyrics.strip(),
                  duration=duration, seed=seed, backend=s.backend, params=params,
                  steps=s.steps, fmt=s.output_format)
        self.jobs[job.id] = job
        self._q.put(job)
        return job

    def cancel(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if job and job.status in ("queued", "running"):
            job.cancel.set()
            return True
        return False

    # ---- worker --------------------------------------------------------
    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            with self._busy:
                self._run(job)
                self._last_used = time.time()

    def _run(self, job: Job) -> None:
        if job.cancel.is_set():
            job.status = "cancelled"
            self._record(job)
            return
        job.status, job.started = "running", time.time()
        wav = paths.outputs_dir() / f"{job.id}.wav"
        writer = None
        try:
            backend = self._backend(job.backend)
            chunk = min(job.params.chunk_seconds, backend.max_segment_seconds)
            overlap = min(job.params.overlap_seconds, chunk / 2 - 0.5) if chunk > 1 else 0
            plan = plan_segments(job.duration, chunk, max(0.0, overlap))
            job.segments = len(plan)
            job.message = "loading model"
            backend.load(job.params)
            stitcher = None
            for i, dur in enumerate(plan):
                if job.cancel.is_set():
                    raise Cancelled()
                job.segment = i + 1
                job.message = f"segment {i + 1}/{len(plan)}"
                base = i / len(plan)

                def prog(f, base=base):
                    job.progress = base + f / len(plan)

                req = SegmentRequest(prompt=job.prompt, lyrics=job.lyrics, duration=dur,
                                     seed=job.seed + i, index=i, total=len(plan), steps=job.steps)
                res = backend.generate_segment(req, job.params, prog, job.cancel.is_set)
                if stitcher is None:
                    writer = WavWriter(wav, res.sample_rate, res.audio.shape[1])
                    stitcher = Stitcher(writer, max(0.0, overlap))
                stitcher.add(res.audio, res.sample_rate)  # streamed to disk
                del res
                self._clear_cuda()
            stitcher.finish()
            writer = None
            if job.fmt == "mp3":
                job.message = "encoding mp3"
                export_mp3(wav, wav.with_suffix(".mp3"))
            job.status, job.progress, job.message = "done", 1.0, "done"
        except Cancelled:
            job.status, job.message = "cancelled", "cancelled"
            self._discard(wav, writer)
        except Exception as e:  # includes CUDA OOM
            log.exception("job failed")
            job.status, job.error = "error", self._explain(e, job)
            self._discard(wav, writer)
        finally:
            job.finished = time.time()
            self._clear_cuda()
            self._record(job)

    @staticmethod
    def _discard(wav, writer) -> None:
        if writer:
            writer.close()
        wav.unlink(missing_ok=True)

    @staticmethod
    def _explain(e: Exception, job: Job) -> str:
        msg = f"{type(e).__name__}: {e}"
        if "out of memory" in msg.lower():
            msg += (" — GPU ran out of memory. Switch Settings to Safe mode, enable offload/quantization, "
                    "or lower chunk length.")
        return msg

    def _record(self, job: Job) -> None:
        self.history.add(id=job.id, backend=job.backend, prompt=job.prompt, lyrics=job.lyrics,
                         duration=job.duration, seed=job.seed, mode=job.params.mode,
                         status=job.status, error=job.error,
                         elapsed=(job.finished - job.started) if job.started else 0,
                         params={**job.params.to_dict(), "steps": job.steps, "format": job.fmt})

    # ---- memory hygiene ------------------------------------------------
    @staticmethod
    def _clear_cuda() -> None:
        gc.collect()
        if "torch" in sys.modules:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def unload_all(self) -> None:
        for b in self._backends.values():
            if b.loaded:
                b.unload()
        self._clear_cuda()

    def _idle_watch(self) -> None:
        while not self._stop.wait(5):
            idle = self.store.value.idle_unload_seconds
            if idle and not self._busy.locked() and time.time() - self._last_used > idle:
                if any(b.loaded for b in self._backends.values()):
                    if self._busy.acquire(blocking=False):
                        try:
                            log.info("idle %ss: unloading models", idle)
                            self.unload_all()
                        finally:
                            self._busy.release()

    def output_path(self, job_id: str, fmt: str):
        p = paths.outputs_dir() / f"{job_id}.{fmt}"
        if fmt == "mp3" and not p.exists() and p.with_suffix(".wav").exists():
            export_mp3(p.with_suffix(".wav"), p)
        return p if p.exists() else None

    def delete(self, job_id: str) -> None:
        for ext in ("wav", "mp3"):
            (paths.outputs_dir() / f"{job_id}.{ext}").unlink(missing_ok=True)
        self.history.delete(job_id)

    def shutdown(self) -> None:
        self._stop.set()
        self.unload_all()
