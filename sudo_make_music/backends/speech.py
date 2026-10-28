"""Talk-mode (text-to-speech) backends.

- mock_speech : no model; deterministic tones whose pitch depends on the voice. For tests / UI development.
- kokoro      : tiny (82M) fast TTS with built-in preset voices, no cloning. Apache-2.0.
- chatterbox  : zero-shot voice cloning from a few seconds of reference audio. MIT.

kokoro / chatterbox adapters are written against the libraries' public APIs and have NOT been run in CI
(no model downloads possible there): verify them on real hardware. Argument names are filtered
with inspect so small version differences do not crash.
"""
from __future__ import annotations

import gc
import hashlib
import inspect
import logging
import sys
import time
from pathlib import Path

import numpy as np

from ..memory import GenParams
from .base import SpeechBackend, SpeechRequest, SegmentResult, Cancelled, register

log = logging.getLogger(__name__)


def _filter(fn, kwargs: dict) -> dict:
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return kwargs
    if any(p.kind is p.VAR_KEYWORD for p in sig.parameters.values()):
        return kwargs
    return {k: v for k, v in kwargs.items() if k in sig.parameters}


def _free_cuda() -> None:
    gc.collect()
    if "torch" in sys.modules:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def _to_mono_np(wav) -> np.ndarray:
    """torch tensor / array of shape (n,) or (1,n) -> float32 (n,1)."""
    if hasattr(wav, "detach"):
        wav = wav.detach().cpu().float().numpy()
    wav = np.asarray(wav, dtype=np.float32).reshape(-1)
    return wav[:, None]


@register
class MockSpeechBackend(SpeechBackend):
    id = "mock_speech"
    name = "Mock voice (no AI)"
    description = "Beeps shaped by the chosen voice. Verifies talk mode and the voice library without a model."
    supports_cloning = True
    preset_voices = ("low", "high")
    uses_gpu = False
    last_request: SpeechRequest | None = None
    sr = 24000

    def __init__(self):
        self._loaded = False

    def load(self, params: GenParams, model_path=None) -> None:
        self._loaded = True

    @property
    def loaded(self) -> bool:
        return self._loaded

    def unload(self) -> None:
        self._loaded = False

    def synthesize(self, req, params, progress, cancelled):
        self.last_request = req
        if cancelled():
            raise Cancelled()
        if req.voice_ref_path:
            h = int(hashlib.md5(Path(req.voice_ref_path).read_bytes()).hexdigest()[:6], 16)
            base = 100 + h % 200
        else:
            base = {"low": 110, "high": 220}.get(req.preset or "low", 140)
        words = max(1, len(req.text.split()))
        dur = words * 0.25 / max(0.25, req.speed)
        t = np.arange(int(dur * self.sr), dtype=np.float32) / self.sr
        sig = 0.3 * np.sin(2 * np.pi * base * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 4 * t) ** 2)
        time.sleep(0.01)
        progress(1.0)
        return SegmentResult(sig[:, None].astype(np.float32), self.sr)


@register
class KokoroBackend(SpeechBackend):
    id = "kokoro"
    name = "Kokoro (fast, preset voices)"
    description = "82M-parameter TTS, runs on any GPU or on CPU. Preset voices only (no cloning)."
    needs_model = True
    default_model_name = "kokoro"
    can_switch_device_live = True
    preset_voices = ("af_heart", "af_bella", "af_nicole", "am_michael", "am_fenrir", "bf_emma", "bm_george")
    min_vram_mb = 0

    def __init__(self):
        self._pipe = None
        self._key = None
        self._model_path: Path | None = None

    @classmethod
    def available(cls):
        try:
            import kokoro  # noqa: F401
        except Exception as e:
            return False, f"kokoro not installed ({e}). Run: pip install kokoro soundfile"
        return True, ""

    @property
    def loaded(self) -> bool:
        return self._pipe is not None

    def load(self, params: GenParams, model_path=None) -> None:
        key = (params.device, str(model_path))
        if self._pipe is not None and key == self._key:
            return
        self.unload()
        from kokoro import KModel, KPipeline

        self._model_path = Path(model_path) if model_path else None
        device = "cuda" if params.device == "cuda" else "cpu"
        model = None
        if self._model_path and (self._model_path / "kokoro-v1_0.pth").is_file():   # fully local files
            model = KModel(config=str(self._model_path / "config.json"),
                           model=str(self._model_path / "kokoro-v1_0.pth")).to(device).eval()
        kwargs = _filter(KPipeline.__init__, dict(lang_code="a", model=model if model is not None else True,
                                                 device=device))
        self._pipe, self._key = KPipeline(**kwargs), key

    def synthesize(self, req, params, progress, cancelled):
        if cancelled():
            raise Cancelled()
        name = req.preset or self.preset_voices[0]
        local = self._model_path / "voices" / f"{name}.pt" if self._model_path else None
        voice = str(local) if local and local.is_file() else name
        parts = [np.asarray(a.detach().cpu().numpy() if hasattr(a, "detach") else a, dtype=np.float32)
                 for _, _, a in self._pipe(req.text, voice=voice, speed=req.speed) if a is not None]
        if not parts:
            raise RuntimeError("Kokoro produced no audio")
        progress(1.0)
        return SegmentResult(np.concatenate(parts)[:, None], 24000)

    def unload(self) -> None:
        self._pipe = self._key = None
        _free_cuda()


@register
class ChatterboxBackend(SpeechBackend):
    id = "chatterbox"
    name = "Chatterbox (voice cloning)"
    description = ("Zero-shot cloning: speaks in the voice of a 5-15 second reference clip. "
                   "Needs a few GB of VRAM; falls back to CPU (slow).")
    needs_model = True
    default_model_name = "chatterbox"
    supports_cloning = True
    preset_voices = ("default",)
    min_vram_mb = 6000
    can_switch_device_live = False

    def __init__(self):
        self._model = None
        self._key = None

    @classmethod
    def available(cls):
        try:
            import torch  # noqa: F401
            from chatterbox.tts import ChatterboxTTS  # noqa: F401
        except Exception as e:
            return False, f"chatterbox-tts not installed ({e}). Run: pip install chatterbox-tts"
        return True, ""

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self, params: GenParams, model_path=None) -> None:
        key = (params.device, str(model_path))
        if self._model is not None and key == self._key:
            return
        self.unload()
        import os
        if params.device == "cpu":
            os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
        from chatterbox.tts import ChatterboxTTS

        device = "cuda" if params.device == "cuda" else "cpu"
        mp = Path(model_path) if model_path else None
        if mp and mp.is_dir() and any(mp.glob("*.safetensors")):      # fully local checkpoint folder
            self._model = ChatterboxTTS.from_local(mp, device)
        else:
            self._model = ChatterboxTTS.from_pretrained(device=device)  # downloads once, needs internet
        self._key = key

    def synthesize(self, req, params, progress, cancelled):
        import torch

        if cancelled():
            raise Cancelled()
        torch.manual_seed(req.seed)
        kwargs = _filter(self._model.generate, dict(
            text=req.text, audio_prompt_path=str(req.voice_ref_path) if req.voice_ref_path else None))
        wav = self._model.generate(**kwargs)
        progress(1.0)
        return SegmentResult(_to_mono_np(wav), int(getattr(self._model, "sr", 24000)))

    def unload(self) -> None:
        self._model = self._key = None
        _free_cuda()
