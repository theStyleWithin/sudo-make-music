"""Models used to change the singer of an existing song (all local, all separate downloads):

  1. a vocal-separation model   (mix -> vocals + instrumental)
  2. a voice-conversion model   (vocals + reference clip -> vocals in that voice)

- mock_separator / mock_converter : no models; deterministic filters for tests and UI development.
- demucs     : Meta's Demucs (MIT) vocal separation.
- openvoice  : OpenVoice v2 tone-colour converter (MIT), zero-shot from a short reference clip.

demucs / openvoice adapters follow the libraries' public APIs but have NOT been run in CI (no model
downloads possible there). Verify on real hardware. Model folders are imported in Settings > Models,
so they work with no network at all.
"""
from __future__ import annotations

import gc
import hashlib
import logging
import sys
import tempfile
from pathlib import Path

import numpy as np

from .. import paths
from ..memory import GenParams
from .base import ConverterBackend, SeparatorBackend, SegmentResult, Cancelled, register

log = logging.getLogger(__name__)


def _free_cuda() -> None:
    gc.collect()
    if "torch" in sys.modules:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()


@register
class MockSeparator(SeparatorBackend):
    id = "mock_separator"
    name = "Mock separator (no AI)"
    description = "Low-pass/high-pass split. Verifies the re-voice pipeline without a model."
    uses_gpu = False

    def __init__(self):
        self._loaded = False

    def load(self, params: GenParams, model_path=None) -> None:
        self._loaded = True

    @property
    def loaded(self) -> bool:
        return self._loaded

    def unload(self) -> None:
        self._loaded = False

    def separate(self, audio, sr, progress, cancelled):
        if cancelled():
            raise Cancelled()
        k = max(1, sr // 400)                                   # crude low-pass = "instrumental"
        kernel = np.ones(k, dtype=np.float32) / k
        low = np.stack([np.convolve(audio[:, c], kernel, mode="same") for c in range(audio.shape[1])], axis=1)
        progress(1.0)
        return (audio - low).astype(np.float32), low.astype(np.float32)


@register
class MockConverter(ConverterBackend):
    id = "mock_converter"
    name = "Mock voice converter (no AI)"
    description = "Scales the vocals by a factor derived from the reference clip."
    uses_gpu = False
    last_ref: Path | None = None

    def __init__(self):
        self._loaded = False

    def load(self, params: GenParams, model_path=None) -> None:
        self._loaded = True

    @property
    def loaded(self) -> bool:
        return self._loaded

    def unload(self) -> None:
        self._loaded = False

    def convert(self, audio, sr, voice_ref_path, progress, cancelled):
        if cancelled():
            raise Cancelled()
        self.last_ref = Path(voice_ref_path)
        gain = 0.3 + (int(hashlib.md5(Path(voice_ref_path).read_bytes()).hexdigest()[:4], 16) % 100) / 100
        progress(1.0)
        return SegmentResult((audio * gain).astype(np.float32), sr)


@register
class DemucsBackend(SeparatorBackend):
    id = "demucs"
    name = "Demucs (vocal separation)"
    description = "Splits a song into vocals and backing. Model ~80MB, runs on GPU or CPU."
    needs_model = True
    default_model_name = "demucs"
    can_switch_device_live = True
    max_segment_seconds = 45

    def __init__(self):
        self._model = None
        self._key = None

    @classmethod
    def available(cls):
        try:
            import demucs.pretrained  # noqa: F401
            import torch  # noqa: F401
        except Exception as e:
            return False, f"demucs not installed ({e}). Run: pip install demucs"
        return True, ""

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self, params: GenParams, model_path=None) -> None:
        key = (params.device, str(model_path))
        if self._model is not None and key == self._key:
            return
        self.unload()
        from demucs.pretrained import get_model

        repo = Path(model_path) if model_path and self.model_present(model_path) else None
        self._model = get_model("htdemucs", repo=repo) if repo else get_model("htdemucs")  # repo = local folder
        self._model.to("cuda" if params.device == "cuda" else "cpu").eval()
        self._key = key

    def separate(self, audio, sr, progress, cancelled):
        import torch
        import torchaudio
        from demucs.apply import apply_model

        if cancelled():
            raise Cancelled()
        m = self._model
        dev = next(m.parameters()).device
        x = torch.from_numpy(audio.T.copy())
        if x.shape[0] == 1:
            x = x.repeat(2, 1)
        x = torchaudio.functional.resample(x, sr, m.samplerate)
        with torch.no_grad():
            src = apply_model(m, x[None].to(dev), device=dev, split=True, overlap=0.1, progress=False)[0]
        names = list(m.sources)
        v = src[names.index("vocals")]
        inst = src.sum(0) - v
        back = lambda t: torchaudio.functional.resample(t.cpu(), m.samplerate, sr).numpy().T[: len(audio)]
        progress(1.0)
        vocals, instr = back(v), back(inst)
        if audio.shape[1] == 1:
            vocals, instr = vocals.mean(1, keepdims=True), instr.mean(1, keepdims=True)
        return vocals.astype(np.float32), instr.astype(np.float32)

    def unload(self) -> None:
        self._model = self._key = None
        _free_cuda()


@register
class OpenVoiceBackend(ConverterBackend):
    id = "openvoice"
    name = "OpenVoice v2 (voice conversion)"
    description = "Zero-shot tone-colour conversion from a 5-30s reference clip. Small, CPU-friendly."
    needs_model = True
    default_model_name = "openvoice"
    can_switch_device_live = True
    min_vram_mb = 2000

    def __init__(self):
        self._conv = None
        self._key = None
        self._device = "cpu"
        self._src_se_cache: dict = {}

    @classmethod
    def available(cls):
        try:
            from openvoice.api import ToneColorConverter  # noqa: F401
        except Exception as e:
            return False, f"openvoice not installed ({e}). Run: pip install git+https://github.com/myshell-ai/OpenVoice.git"
        return True, ""

    @property
    def loaded(self) -> bool:
        return self._conv is not None

    def load(self, params: GenParams, model_path=None) -> None:
        key = (params.device, str(model_path))
        if self._conv is not None and key == self._key:
            return
        self.unload()
        from openvoice.api import ToneColorConverter

        if not (model_path and (Path(model_path) / "converter" / "config.json").is_file()):
            raise RuntimeError("OpenVoice model folder missing: import a folder that contains converter/config.json "
                               "and converter/checkpoint.pth (Settings > Models).")
        mp = Path(model_path) / "converter"
        self._device = "cuda" if params.device == "cuda" else "cpu"
        self._conv = ToneColorConverter(str(mp / "config.json"), device=self._device)
        self._conv.load_ckpt(str(mp / "checkpoint.pth"))
        self._key = key
        self._ref_se: dict = {}

    def convert(self, audio, sr, voice_ref_path, progress, cancelled):
        import soundfile as sf
        from openvoice import se_extractor

        if cancelled():
            raise Cancelled()
        tmp = Path(tempfile.mkdtemp(prefix="smm-ov-", dir=paths.work_dir()))
        try:
            src, out = tmp / "src.wav", tmp / "out.wav"
            sf.write(str(src), audio.mean(axis=1) if audio.ndim > 1 else audio, sr)
            key = str(voice_ref_path)
            if key not in self._ref_se:   # embedding of the target voice, computed once per song
                self._ref_se[key], _ = se_extractor.get_se(key, self._conv, vad=False)
            src_se, _ = se_extractor.get_se(str(src), self._conv, vad=False)
            self._conv.convert(audio_src_path=str(src), src_se=src_se, tgt_se=self._ref_se[key],
                               output_path=str(out), message="")
            data, osr = sf.read(str(out), dtype="float32", always_2d=True)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        progress(1.0)
        if audio.ndim > 1 and data.shape[1] != audio.shape[1]:
            data = np.repeat(data[:, :1], audio.shape[1], axis=1)
        return SegmentResult(data, int(osr))

    def unload(self) -> None:
        self._conv = self._key = None
        self._ref_se = {}
        _free_cuda()
