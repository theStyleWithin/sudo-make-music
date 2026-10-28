"""ACE-Step backend (https://github.com/ace-step/ACE-Step).

NOTE: written against ACE-Step's public `ACEStepPipeline` API. It has not been
run on an RTX 2060 in CI - constructor/call kwargs are filtered with
`inspect.signature` so minor version drift degrades gracefully instead of
crashing. Verify on real hardware and tune `Settings` accordingly.

Why ACE-Step first: it is a diffusion model that supports `cpu_offload` and
`overlapped_decode` natively, so VRAM stays bounded for the decoder stage, and
it generates up to ~4 minutes per call.
"""
from __future__ import annotations

import gc
import inspect
import os
import logging
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

from .. import paths
from ..memory import GenParams
from .base import ModelBackend, SegmentRequest, SegmentResult, Cancelled, register

log = logging.getLogger(__name__)


def _filter_kwargs(fn, kwargs: dict) -> dict:
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return kwargs
    if any(p.kind is p.VAR_KEYWORD for p in sig.parameters.values()):
        return kwargs
    dropped = [k for k in kwargs if k not in sig.parameters]
    if dropped:
        log.warning("ACE-Step ignoring unsupported args: %s", dropped)
    return {k: v for k, v in kwargs.items() if k in sig.parameters}


@register
class ACEStepBackend(ModelBackend):
    id = "acestep"
    name = "ACE-Step"
    description = ("Diffusion music model with lyrics support, CPU offload and overlapped decoding. "
                   "Default for 6GB GPUs. Weights (~7GB) download on first load, then run offline.")
    max_segment_seconds = 240
    min_vram_mb = 6000
    needs_model = True
    can_switch_device_live = False   # torch cannot re-pick the GPU after CUDA initialised
    default_model_name = "ace-step"
    supports_context = True

    def __init__(self):
        self._pipe = None
        self._key = None
        self._quant_note = ""

    @classmethod
    def available(cls):
        try:
            import torch  # noqa: F401
            import acestep.pipeline_ace_step  # noqa: F401
        except Exception as e:  # ImportError, or broken CUDA libs
            return False, f"ace-step not installed ({e}). Run: pip install '.[acestep]'"
        return True, ""

    @property
    def loaded(self) -> bool:
        return self._pipe is not None

    def load(self, params: GenParams, model_path=None) -> None:
        ckpt = Path(model_path) if model_path else paths.models_dir() / "ace-step"
        key = (params.offload, params.quantize, params.device, str(ckpt))
        if self._pipe is not None and key == self._key:
            return
        self.unload()
        if params.device == "cpu":
            # Must happen before CUDA is initialised in this process (the app does it at startup).
            os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
        import torch
        from acestep.pipeline_ace_step import ACEStepPipeline

        kwargs = dict(
            checkpoint_dir=str(ckpt),
            dtype="bfloat16",          # pipeline only knows bfloat16/float32
            torch_compile=False,       # compile spikes memory and startup time
            cpu_offload=params.offload and params.device == "cuda",
            overlapped_decode=True,    # bounded-VRAM decoder, essential on 6GB
        )
        self._pipe = ACEStepPipeline(**_filter_kwargs(ACEStepPipeline.__init__, kwargs))
        self._key = key
        self._quant_note = ""
        if params.quantize:
            self._try_quantize()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def _try_quantize(self) -> None:
        """Best-effort INT8 weight-only quantization of the diffusion transformer."""
        try:
            from torchao.quantization import quantize_, int8_weight_only
        except Exception:
            self._quant_note = "quantize requested but torchao missing (pip install '.[quant]')"
            log.warning(self._quant_note)
            return
        # ACE-Step loads weights lazily; make sure the checkpoint is in memory.
        try:
            if hasattr(self._pipe, "load_checkpoint") and getattr(self._pipe, "loaded", False) is False:
                self._pipe.load_checkpoint(self._pipe.checkpoint_dir)
            model = getattr(self._pipe, "ace_step_transformer", None)
            if model is None:
                raise RuntimeError("transformer attribute not found")
            quantize_(model, int8_weight_only())
            self._quant_note = "int8 transformer"
        except Exception as e:
            self._quant_note = f"int8 quantization failed, running unquantized ({e})"
            log.warning(self._quant_note)

    def generate_segment(self, req: SegmentRequest, params: GenParams, progress, cancelled):
        if cancelled():
            raise Cancelled()
        tmp = Path(tempfile.mkdtemp(prefix="smm-ace-", dir=paths.work_dir()))
        try:
            if req.context_audio is not None and len(req.context_audio):
                try:
                    return self._run(req, tmp, progress, extend=True)
                except Cancelled:
                    raise
                except Exception as e:  # experimental path: never lose the song over it
                    log.warning("extend-from-previous failed (%s); generating this segment independently", e)
            return self._run(req, tmp, progress, extend=False)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _run(self, req: SegmentRequest, tmp: Path, progress, extend: bool) -> SegmentResult:
        import soundfile as sf

        call = dict(
            audio_duration=float(req.duration),
            prompt=req.prompt,
            lyrics=req.lyrics or "[instrumental]",
            infer_step=req.steps or 60,
            guidance_scale=15.0,
            scheduler_type="euler",
            cfg_type="apg",
            omega_scale=10.0,
            manual_seeds=str(req.seed),
            guidance_interval=0.5,
            guidance_interval_decay=0.0,
            min_guidance_scale=3.0,
            use_erg_tag=True, use_erg_lyric=True, use_erg_diffusion=True,
            oss_steps="",
            guidance_scale_text=0.0, guidance_scale_lyric=0.0,
            save_path=str(tmp / "out.wav"),
            batch_size=1,                      # always 1 on low VRAM
        )
        ctx_len = 0.0
        if extend:
            # Condition on the end of the previous segment so the music continues instead of restarting.
            ctx = tmp / "context.wav"
            sf.write(str(ctx), req.context_audio, req.context_sr)
            ctx_len = len(req.context_audio) / req.context_sr
            call.update(task="extend", src_audio_path=str(ctx), repaint_start=ctx_len,
                        repaint_end=ctx_len + req.duration, audio_duration=ctx_len + req.duration)
        # Diffusion steps are not interruptible mid-call; cancel lands between segments.
        self._pipe(**_filter_kwargs(self._pipe.__call__, call))
        progress(1.0)
        wavs = [w for w in sorted(tmp.glob("*.wav")) if w.name != "context.wav"]
        if not wavs:
            raise RuntimeError("ACE-Step produced no audio")
        data, sr = sf.read(str(wavs[0]), dtype="float32", always_2d=True)
        if extend:
            data = data[int(ctx_len * sr):]    # drop the context we fed in; keep only the new part
        return SegmentResult(np.ascontiguousarray(data), int(sr))

    def unload(self) -> None:
        self._pipe = None
        self._key = None
        gc.collect()
        if "torch" in sys.modules:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
