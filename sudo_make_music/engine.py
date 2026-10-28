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

import numpy as np
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import hardware, memory, paths
from .audio import (WavWriter, Stitcher, plan_segments, export_mp3, read_wav, read_wav_range, wav_info,
                    resample_linear)
from .backends import registry, SegmentRequest, SpeechRequest, Cancelled
from .history import History
from .models import ModelStore
from .textsplit import split_text
from .voices import VoiceStore
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
    kind: str = "song"                      # song | talk
    voice_id: str | None = None
    speed: float = 1.0
    voice_tags: str = ""
    source_id: str | None = None             # revoice: the song being re-voiced
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
                    mode=self.params.mode, params=self.params.to_dict(), decision=self.decision,
                    kind=self.kind, voice_id=self.voice_id)


class Engine:
    def __init__(self, store: SettingsStore | None = None, history: History | None = None):
        self.store = store or SettingsStore()
        self.history = history or History()
        self.hw = hardware.detect()
        self.models = ModelStore()
        self.voices = VoiceStore()
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
                    selected_models=self.store.value.models, model_status=self.model_status(), speech_backend=self.store.value.speech_backend,
                    offline_mode=self.store.value.offline_mode)

    # ---- models --------------------------------------------------------
    def _find_model(self, backend) -> "Path | None":
        """Selected model > first imported model > the backend's default folder (may be empty)."""
        if not backend.needs_model:
            return None
        picked = self.models.get(self.store.value.models.get(backend.id, ""))
        if picked and picked.backend == backend.id:
            return Path(picked.path)
        installed = self.models.list(backend.id)
        if installed:
            return Path(installed[0].path)
        return paths.models_dir() / backend.default_model_name

    def resolve_model(self, backend) -> "Path | None":
        """Model folder for a backend. In offline mode a missing local model is an error, never a download."""
        path = self._find_model(backend)
        if path is not None and self.store.value.offline_mode and not backend.model_present(path):
            raise RuntimeError(f"No local {backend.name} model installed and offline mode is on. "
                               "Import a model folder in Settings > Models, or turn offline mode off to download once.")
        return path

    ROLES = (("backend", "Music model"), ("speech_backend", "Talk voice model"),
             ("converter_backend", "Singing voice-cloning model"), ("separator_backend", "Vocal-separation model"))

    def model_status(self) -> list[dict]:
        """Which separate local models each feature needs, and whether they are on disk right now."""
        out = []
        for attr, label in self.ROLES:
            bid = getattr(self.store.value, attr)
            if bid not in registry():
                out.append(dict(role=label, backend=bid, name=bid, library=False, installed=False, path=None))
                continue
            b = self._backend(bid)
            path = self._find_model(b)
            lib, _ = b.available()
            out.append(dict(role=label, backend=bid, name=b.name, library=lib, installed=b.model_present(path),
                            needs_model=b.needs_model, path=str(path) if path else None))
        return out

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
    def submit(self, prompt: str, lyrics: str, duration: int, voice_id: str | None = None) -> Job:
        s = self.store.value
        params = self.active_params()
        backend = self._backend(s.backend)
        ok, why = backend.available()
        if not ok:
            raise RuntimeError(why)
        if not prompt.strip():
            raise ValueError("style prompt is required")
        voice = self.voices.get(voice_id) if voice_id else None
        if voice_id and not voice:
            raise ValueError("that voice no longer exists")
        self.resolve_model(backend)   # fail fast (e.g. offline mode with no local model)
        duration = int(min(max(5, duration), params.max_duration))
        # A saved voice makes the result repeatable: its seed is reused unless the user pinned another one.
        seed = s.seed if s.seed is not None else (voice.seed if voice and voice.seed is not None
                                                   else random.randint(0, 2**31 - 1))
        job = Job(id=uuid.uuid4().hex[:12], prompt=prompt.strip(), lyrics=lyrics.strip(),
                  duration=duration, seed=seed, backend=s.backend, params=params,
                  steps=s.steps, fmt=s.output_format, continuity=s.continuity and backend.supports_context,
                  voice_id=voice.id if voice else None, voice_tags=voice.tags if voice else "")
        self.jobs[job.id] = job
        self._q.put(job)
        return job

    def submit_talk(self, text: str, voice_id: str | None = None, speed: float = 1.0) -> Job:
        """Talk mode: speak typed text in a saved voice (cloned reference clip or built-in preset)."""
        s = self.store.value
        backend = self._backend(s.speech_backend)
        if backend.kind != "speech":
            raise ValueError(f"{backend.name} is not a speech backend")
        ok, why = backend.available()
        if not ok:
            raise RuntimeError(why)
        if not text.strip():
            raise ValueError("type something for the voice to say")
        voice = self.voices.get(voice_id) if voice_id else None
        if voice_id and not voice:
            raise ValueError("that voice no longer exists")
        if voice and voice.has_ref and not backend.supports_cloning and not voice.preset:
            raise ValueError(f"{backend.name} cannot clone voices. Switch the speech backend in Settings "
                             "or pick a preset voice.")
        if voice and voice.preset and voice.preset not in backend.preset_voices and not voice.has_ref:
            raise ValueError(f"preset '{voice.preset}' does not exist in {backend.name}; pick another voice or backend")
        self.resolve_model(backend)
        seed = s.seed if s.seed is not None else random.randint(0, 2**31 - 1)
        job = Job(id=uuid.uuid4().hex[:12], prompt=text.strip(), lyrics="", duration=0, seed=seed,
                  backend=s.speech_backend, params=self.active_params(), steps=0, fmt=s.output_format,
                  kind="talk", voice_id=voice.id if voice else None, speed=min(2.0, max(0.5, float(speed))))
        self.jobs[job.id] = job
        self._q.put(job)
        return job

    def submit_revoice(self, source_id: str, voice_id: str) -> Job:
        """Change the singer of an existing song: separate vocals -> convert to the saved voice -> remix.
        Needs two separate local models (vocal separation + voice conversion) and a voice with a reference clip."""
        s = self.store.value
        row = self.history.get(source_id)
        if not row or not (paths.outputs_dir() / f"{source_id}.wav").is_file() or (row.get("kind") or "song") == "talk":
            raise ValueError("pick a finished song to re-voice")
        voice = self.voices.get(voice_id) if voice_id else None
        if not voice or not voice.has_ref:
            raise ValueError("choose a saved voice that has a reference clip (cloned or saved from a song), not a preset")
        conv, sep = self._backend(s.converter_backend), self._backend(s.separator_backend)
        for b in (conv, sep):
            ok, why = b.available()
            if not ok:
                raise RuntimeError(why)
            self.resolve_model(b)          # fail fast in offline mode
        job = Job(id=uuid.uuid4().hex[:12], prompt=f"{row['prompt']} (re-voiced: {voice.name})", lyrics=row.get("lyrics") or "",
                  duration=int(row["duration"] or 0), seed=row["seed"], backend=conv.id, params=self.active_params(),
                  steps=0, fmt=s.output_format, kind="revoice", voice_id=voice.id, source_id=source_id)
        self.jobs[job.id] = job
        self._q.put(job)
        return job

    def save_voice_from_job(self, job_id: str, name: str, start: float = 0.0, length: float = 15.0, tags: str = ""):
        """Keep the voice of a generated song in the (separate) voice library."""
        row = self.history.get(job_id)
        wav = paths.outputs_dir() / f"{job_id}.wav"
        if not row or not wav.is_file() or (row.get("kind") or "song") != "song":
            raise ValueError("that song is not available")
        return self.voices.create_from_song(wav, name, start, length, tags, seed=row["seed"],
                                            origin_prompt=row["prompt"])

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
            self._record(job, "cancelled")
            job.status = "cancelled"
            return
        job.status, job.started = "running", time.time()
        wav = paths.outputs_dir() / f"{job.id}.wav"
        hold: dict = {}
        try:
            backend = self._backend(job.backend)
            self._preflight_device(job, backend)
            job.message = "loading model"
            if job.params.device == "cpu" and backend.uses_gpu and not backend.can_switch_device_live and self._cuda_initialised():
                raise RuntimeError("CPU was selected after the GPU was already in use. Restart the app to run on CPU.")
            self._set_device_env(job.params.device)
            self._apply_offline(self.store.value.offline_mode)
            model_path = self.resolve_model(backend)
            self._unload_others(backend)      # one model in memory at a time (VRAM!)
            self._with_fallback(job, backend, lambda: backend.load(job.params, model_path), model_path)
            if job.kind == "talk":
                self._make_speech(job, backend, model_path, wav, hold)
            elif job.kind == "revoice":
                self._make_revoice(job, backend, model_path, wav, hold)
            else:
                self._make_song(job, backend, model_path, wav, hold)
            if job.fmt == "mp3":
                job.message = "encoding mp3"
                export_mp3(wav, wav.with_suffix(".mp3"))
            job.progress, job.message = 1.0, "done"
            outcome = "done"
        except Cancelled:
            job.message, outcome = "cancelled", "cancelled"
            self._discard(wav, hold.get("writer"))
        except Exception as e:  # includes CUDA OOM
            log.exception("job failed")
            job.error, outcome = self._explain(e, job), "error"
            self._discard(wav, hold.get("writer"))
        job.finished = time.time()
        self._clear_cuda()
        self._record(job, outcome)       # history row first ...
        job.status = outcome             # ... then expose the final status (callers may use the row at once)

    def _unload_others(self, keep) -> None:
        for b in self._backends.values():
            if b is not keep and b.loaded:
                b.unload()
        self._clear_cuda()

    def _make_song(self, job: Job, backend, model_path, wav, hold: dict) -> None:
        chunk = min(job.params.chunk_seconds, backend.max_segment_seconds)
        overlap = max(0.0, min(job.params.overlap_seconds, chunk / 2 - 0.5) if chunk > 1 else 0)
        plan = plan_segments(job.duration, chunk, overlap)
        job.segments = len(plan)
        prompt = f"{job.voice_tags}, {job.prompt}" if job.voice_tags else job.prompt
        voice_ctx = None                 # saved voice: its reference clip conditions every chunk (best effort)
        if job.voice_id and backend.supports_context:
            ref = self.voices.ref_audio(job.voice_id)
            if ref is not None:
                a, sr = ref
                voice_ctx = (np.repeat(a[: int(10 * sr)], 2, axis=1) if a.shape[1] == 1 else a[: int(10 * sr)], sr)
        stitcher = None
        prev_tail, prev_sr = None, 0
        for i, dur in enumerate(plan):
            if job.cancel.is_set():
                raise Cancelled()
            job.segment = i + 1
            job.message = f"segment {i + 1}/{len(plan)}"
            base = i / len(plan)

            def prog(f, base=base):
                job.progress = base + f / len(plan)

            ctx, ctx_sr = (prev_tail, prev_sr) if prev_tail is not None else (voice_ctx or (None, 0))
            req = SegmentRequest(prompt=prompt, lyrics=job.lyrics, duration=dur,
                                 seed=job.seed + i, index=i, total=len(plan), steps=job.steps,
                                 context_audio=ctx, context_sr=ctx_sr)
            res = self._with_fallback(job, backend, lambda: backend.generate_segment(
                req, job.params, prog, job.cancel.is_set), model_path)
            if stitcher is None:
                hold["writer"] = WavWriter(wav, res.sample_rate, res.audio.shape[1])
                stitcher = Stitcher(hold["writer"], overlap)
            stitcher.add(res.audio, res.sample_rate)  # streamed to disk
            if job.continuity:   # keep only ~10s of the previous segment as context
                n = int(10 * res.sample_rate)
                prev_tail, prev_sr = res.audio[-n:].copy(), res.sample_rate
            del res
            self._clear_cuda()
        stitcher.finish()
        hold["writer"] = None

    def _make_revoice(self, job: Job, conv, conv_model, wav, hold: dict) -> None:
        sep = self._backend(self.store.value.separator_backend)
        sep_model = self.resolve_model(sep)
        job.message = "loading vocal separation model"
        self._with_fallback(job, sep, lambda: sep.load(job.params, sep_model), sep_model)
        src = paths.outputs_dir() / f"{job.source_id}.wav"
        ref = self.voices.ref_path(job.voice_id)
        frames, sr, ch = wav_info(src)
        total = frames / sr
        win, ov = 45.0, 2.0                               # windows keep RAM bounded for long songs
        n = 1 if total <= win else int(np.ceil((total - ov) / (win - ov)))
        stitcher = None
        for i in range(n):
            if job.cancel.is_set():
                raise Cancelled()
            job.segment, job.segments = i + 1, n
            job.message = f"re-voicing part {i + 1}/{n}"
            audio, _ = read_wav_range(src, i * (win - ov), win)
            if len(audio) < int(0.5 * sr):
                break
            noop = lambda f: None
            vocals, inst = self._with_fallback(job, sep, lambda: sep.separate(audio, sr, noop, job.cancel.is_set), sep_model)
            res = self._with_fallback(job, conv, lambda: conv.convert(vocals, sr, ref, noop, job.cancel.is_set), conv_model)
            new = resample_linear(res.audio, res.sample_rate, sr)
            if new.shape[1] != inst.shape[1]:
                new = np.repeat(new[:, :1], inst.shape[1], axis=1)
            m = min(len(new), len(inst))
            mix = new[:m] + inst[:m]
            peak = float(np.max(np.abs(mix))) if m else 0.0
            if peak > 1.0:                                # avoid clipping after summing the stems
                mix = mix / peak
            if stitcher is None:
                hold["writer"] = WavWriter(wav, sr, mix.shape[1])
                stitcher = Stitcher(hold["writer"], ov if n > 1 else 0.0)
            stitcher.add(mix, sr)
            job.progress = (i + 1) / n
            del audio, vocals, inst, res, new, mix
            self._clear_cuda()
        if stitcher is None:
            raise ValueError("the song is too short to re-voice")
        stitcher.finish()
        hold["writer"] = None

    def _make_speech(self, job: Job, backend, model_path, wav, hold: dict) -> None:
        chunks = split_text(job.prompt)
        if not chunks:
            raise ValueError("nothing to say")
        job.segments = len(chunks)
        voice = self.voices.get(job.voice_id) if job.voice_id else None
        ref = self.voices.ref_path(voice.id) if voice and voice.has_ref and backend.supports_cloning else None
        preset = (voice.preset if voice and voice.preset else None) or (backend.preset_voices[0] if backend.preset_voices else None)
        writer = None
        for i, text in enumerate(chunks):
            if job.cancel.is_set():
                raise Cancelled()
            job.segment, job.message = i + 1, f"sentence {i + 1}/{len(chunks)}"
            base = i / len(chunks)

            def prog(f, base=base):
                job.progress = base + f / len(chunks)

            req = SpeechRequest(text=text, voice_ref_path=ref, preset=preset, speed=job.speed,
                                seed=job.seed + i, index=i, total=len(chunks))
            res = self._with_fallback(job, backend, lambda: backend.synthesize(
                req, job.params, prog, job.cancel.is_set), model_path)
            if writer is None:
                writer = hold["writer"] = WavWriter(wav, res.sample_rate, res.audio.shape[1])
            writer.write(res.audio)
            if i < len(chunks) - 1:   # short natural pause between sentences
                writer.write(np.zeros((int(0.3 * res.sample_rate), res.audio.shape[1]), dtype=np.float32))
            del res
            self._clear_cuda()
        writer.close()
        hold["writer"] = None

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

    def _record(self, job: Job, status: str | None = None) -> None:
        self.history.add(id=job.id, backend=job.backend, prompt=job.prompt, lyrics=job.lyrics,
                         duration=job.duration, seed=job.seed, mode=job.params.mode,
                         status=status or job.status, error=job.error, kind=job.kind, voice_id=job.voice_id,
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
