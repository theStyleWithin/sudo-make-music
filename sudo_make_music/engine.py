"""Job engine: one generation at a time, memory-safe chunked pipeline."""
from __future__ import annotations

import gc
import logging
import os
import queue
import random
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import hardware, memory, paths
from .audio import WavWriter, Stitcher, plan_segments, export_mp3
from .backends import registry, SegmentRequest, Cancelled
from .history import History
from .models import ModelStore
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
    continuity: bool = False
    decision: dict | None = None            # pending hardware warning shown to the user
    choice: str | None = None
    decided: threading.Event = field(default_factory=threading.Event)
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
                    mode=self.params.mode, params=self.params.to_dict(), decision=self.decision)


class Engine:
    def __init__(self, store: SettingsStore | None = None, history: History | None = None):
        self.store = store or SettingsStore()
        self.history = history or History()
        self.hw = hardware.detect()
        self.models = ModelStore()
        self._hid_cuda = False
        self._set_device_env(self.active_params().device)
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
                    mode_auto=self.store.value.memory_mode is None, device=p.device,
                    mode_description=memory.describe(p, self.hw), params=p.to_dict(),
                    modes=memory.MODES, backends=self.backend_infos(),
                    model_loaded=any(b.loaded for b in self._backends.values()),
                    free_vram_mb=hardware.free_vram_mb(),
                    models=[m.to_dict() for m in self.models.list()],
                    selected_models=self.store.value.models,
                    offline_mode=self.store.value.offline_mode)

    # ---- models --------------------------------------------------------
    def resolve_model(self, backend) -> "Path | None":
        """Pick the model folder for a backend: selected > first installed > its downloadable default."""
        if not backend.needs_model:
            return None
        s = self.store.value
        picked = self.models.get(s.models.get(backend.id, ""))
        if picked and picked.backend == backend.id:
            return Path(picked.path)
        installed = self.models.list(backend.id)
        if installed:
            return Path(installed[0].path)
        folder = paths.models_dir() / backend.default_model_name
        if s.offline_mode:
            raise RuntimeError(f"No local {backend.name} model installed and offline mode is on. "
                               "Import a model folder in Settings > Models, or turn offline mode off to download once.")
        return folder

    def import_model(self, path: str, backend: str | None = None, name: str | None = None, link: bool = False):
        b = self._backend(backend or self.store.value.backend)
        info = self.models.import_folder(Path(path), b.id, name, link)
        self.store.value.models[info.backend] = info.id
        self.store.save()
        return info

    def select_model(self, backend: str, model_id: str) -> None:
        m = self.models.get(model_id)
        if not m or m.backend != backend:
            raise ValueError("model does not belong to that backend")
        self.store.value.models[backend] = model_id
        self.store.save()

    def delete_model(self, model_id: str) -> None:
        self.models.delete(model_id)
        self.store.value.models = {k: v for k, v in self.store.value.models.items() if v != model_id}
        self.store.save()
        self.unload_all()

    @staticmethod
    def _apply_offline(on: bool) -> None:
        for k in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
            if on:
                os.environ[k] = "1"
            else:
                os.environ.pop(k, None)

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
        self.resolve_model(backend)   # fail fast (e.g. offline mode with no local model)
        duration = int(min(max(5, duration), params.max_duration))
        seed = s.seed if s.seed is not None else random.randint(0, 2**31 - 1)
        job = Job(id=uuid.uuid4().hex[:12], prompt=prompt.strip(), lyrics=lyrics.strip(),
                  duration=duration, seed=seed, backend=s.backend, params=params,
                  steps=s.steps, fmt=s.output_format, continuity=s.continuity and backend.supports_context)
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
            self._preflight_device(job, backend)
            chunk = min(job.params.chunk_seconds, backend.max_segment_seconds)
            overlap = min(job.params.overlap_seconds, chunk / 2 - 0.5) if chunk > 1 else 0
            plan = plan_segments(job.duration, chunk, max(0.0, overlap))
            job.segments = len(plan)
            job.message = "loading model"
            if job.params.device == "cpu" and backend.uses_gpu and not backend.can_switch_device_live and self._cuda_initialised():
                raise RuntimeError("CPU was selected after the GPU was already in use. Restart the app to run on CPU.")
            self._set_device_env(job.params.device)
            self._apply_offline(self.store.value.offline_mode)
            model_path = self.resolve_model(backend)
            self._with_fallback(job, backend, lambda: backend.load(job.params, model_path), model_path)
            stitcher = None
            ctx_tail, ctx_sr = None, 0
            for i, dur in enumerate(plan):
                if job.cancel.is_set():
                    raise Cancelled()
                job.segment = i + 1
                job.message = f"segment {i + 1}/{len(plan)}"
                base = i / len(plan)

                def prog(f, base=base):
                    job.progress = base + f / len(plan)

                req = SegmentRequest(prompt=job.prompt, lyrics=job.lyrics, duration=dur,
                                     seed=job.seed + i, index=i, total=len(plan), steps=job.steps,
                                     context_audio=ctx_tail, context_sr=ctx_sr)
                res = self._with_fallback(job, backend, lambda: backend.generate_segment(
                    req, job.params, prog, job.cancel.is_set), model_path)
                if stitcher is None:
                    writer = WavWriter(wav, res.sample_rate, res.audio.shape[1])
                    stitcher = Stitcher(writer, max(0.0, overlap))
                stitcher.add(res.audio, res.sample_rate)  # streamed to disk
                if job.continuity:   # keep only ~10s of the previous segment as context
                    n = int(10 * res.sample_rate)
                    ctx_tail, ctx_sr = res.audio[-n:].copy(), res.sample_rate
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

    def _set_device_env(self, device: str) -> None:
        """Hide CUDA for CPU runs (only possible before CUDA initialises); unhide if we hid it."""
        if device == "cpu":
            os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
            self._hid_cuda = True
        elif self._hid_cuda and not self._cuda_initialised():
            os.environ.pop("CUDA_VISIBLE_DEVICES", None)
            self._hid_cuda = False

    def ask(self, job: Job, title: str, reason: str, options: list[tuple[str, str]]) -> str:
        """Pause the job and show a hardware warning; returns the id of the button the user pressed."""
        job.decided.clear()
        job.choice = None
        job.decision = dict(title=title, reason=reason,
                            options=[dict(id=i, label=l) for i, l in options] + [dict(id="cancel", label="Cancel generation")])
        prev, job.status, job.message = job.status, "needs_input", title
        while not job.decided.wait(0.25):
            if job.cancel.is_set():
                break
        choice = job.choice or "cancel"
        job.decision, job.status, job.message = None, prev, "continuing"
        if job.cancel.is_set() or choice == "cancel":
            raise Cancelled()
        return choice

    def resolve_decision(self, job_id: str, choice: str) -> None:
        job = self.jobs.get(job_id)
        if not job or not job.decision or choice not in [o["id"] for o in job.decision["options"]]:
            raise ValueError("no such pending choice")
        job.choice = choice
        job.decided.set()

    def _preflight_device(self, job: Job, backend) -> None:
        """No GPU / too little VRAM and the user did not pick CPU themselves: warn and let them choose."""
        s = self.store.value
        auto = s.overrides.get("device") is None
        if not (backend.uses_gpu and auto and job.params.device == "cpu" and s.ask_on_fallback):
            return
        hw = self.hw
        why = ("No GPU was detected." if not hw.gpu_name else
               f"{hw.gpu_name} has only {hw.vram_mb} MB of VRAM (needs at least {memory.MIN_GPU_VRAM_MB} MB).")
        opts = [("cpu", "Continue on CPU + system RAM (slow)")]
        if hw.gpu_name:
            opts.append(("gpu", "Try the GPU anyway (may fail)"))
        choice = self.ask(job, "Hardware warning: no usable GPU memory",
                          why + " Generation on the CPU uses system RAM and can be many times slower.", opts)
        if choice == "gpu":
            job.params = replace(job.params, device="cuda", offload=True, quantize=True)

    @staticmethod
    def _is_oom(e: BaseException) -> bool:
        return "out of memory" in str(e).lower() or type(e).__name__ == "OutOfMemoryError"

    @staticmethod
    def _cuda_initialised() -> bool:
        if "torch" not in sys.modules:
            return False
        import torch
        return bool(torch.cuda.is_available() and torch.cuda.is_initialized())

    def _with_fallback(self, job: Job, backend, fn, model_path):
        """Run fn(); on out-of-memory step down: offload+int8 on GPU, then CPU/system RAM, and retry."""
        while True:
            try:
                return fn()
            except Cancelled:
                raise
            except Exception as e:
                if not self._is_oom(e):
                    raise
                can_cpu = backend.can_switch_device_live or not self._cuda_initialised()
                opts = memory.fallback_options(job.params, can_cpu)
                if not opts:
                    raise
                if self.store.value.ask_on_fallback:
                    choice = self.ask(job, "Hardware warning: GPU out of memory",
                                      f"{job.params.device.upper()} memory ran out while generating. Choose which resource to use instead.",
                                      [(i, l) for i, l, _ in opts])
                    new = next(n for i, _, n in opts if i == choice)
                    if new is None:   # needs a restart: persist the setting and stop this job
                        self.store.value.overrides["device"] = "cpu"
                        self.store.save()
                        raise RuntimeError("Compute device set to CPU. Restart the app and generate again.")
                    job.params, note = new, "switching resource"
                else:
                    step = memory.degrade(job.params, can_cpu)
                    if step is None:
                        raise
                    job.params, note = step
                log.warning(note)
                job.message = note
                self._set_device_env(job.params.device)
                backend.unload()
                self._clear_cuda()
                backend.load(job.params, model_path)

    @staticmethod
    def _discard(wav, writer) -> None:
        if writer:
            writer.close()
        wav.unlink(missing_ok=True)

    @staticmethod
    def _explain(e: Exception, job: Job) -> str:
        msg = f"{type(e).__name__}: {e}"
        if "out of memory" in msg.lower():
            msg += (" — out of memory even after offload/int8. Set Settings > Compute device to CPU and restart "
                    "the app (uses system RAM, slow), or lower the chunk length.")
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
