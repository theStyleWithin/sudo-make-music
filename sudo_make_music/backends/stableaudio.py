"""Stable Audio Open Small (341M params) - the small-model base, kept swappable like every other backend.

Two backends share the model family:
  stableaudio         PyTorch via `stable-audio-tools` (desktop; GPU or CPU). Official API.
  stableaudio_litert  LiteRT (.tflite) models run with a numpy sampler (phones / no-PyTorch devices).
                      Needs converted model files + a `smm-litert.json` descriptor, see docs/STABLE_AUDIO_LITERT.md.

What this model is: short clips (<= ~11s, stereo 44.1kHz), music loops / instrumental ideas / sound effects,
NO lyrics or vocals control. Longer songs are stitched from independent clips (the engine does that).
Licence: Stability AI Community License (not public domain; check the terms before commercial use).

Neither backend has been run against the real weights in CI (no model downloads possible there);
the sampler and the whole pipeline around them are tested with fake runners.
"""
from __future__ import annotations

import gc
import inspect
import json
import logging
import os
import sys
from pathlib import Path

import numpy as np

from ..memory import GenParams
from .base import ModelBackend, SegmentRequest, SegmentResult, Cancelled, register

log = logging.getLogger(__name__)
NATIVE_STEPS = 8          # the Small model is distilled for 8 pingpong steps (the app's "Steps" setting is ACE-Step's)


def _filter(fn, kwargs):
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return kwargs
    if any(p.kind is p.VAR_KEYWORD for p in sig.parameters.values()):
        return kwargs
    return {k: v for k, v in kwargs.items() if k in sig.parameters}


def _set_key(obj, key: str, value) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                obj[k] = value
            else:
                _set_key(v, key, value)
    elif isinstance(obj, list):
        for v in obj:
            _set_key(v, key, value)


def _free_cuda():
    gc.collect()
    if "torch" in sys.modules:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()


# --------------------------------------------------------------------------- PyTorch
@register
class StableAudioBackend(ModelBackend):
    id = "stableaudio"
    name = "Stable Audio Open Small (PyTorch)"
    description = ("341M-parameter text-to-audio model: 11s stereo clips in a few seconds, tiny VRAM/RAM use. "
                   "No lyrics/vocals. Folder needs model_config.json + model.safetensors (or .ckpt).")
    max_segment_seconds = 11
    needs_model = True
    default_model_name = "stable-audio-open-small"
    min_vram_mb = 1500
    can_switch_device_live = False

    def __init__(self):
        self._model = None
        self._key = None
        self._cfg: dict = {}
        self._device = "cpu"

    @classmethod
    def available(cls):
        try:
            import torch  # noqa: F401
            from stable_audio_tools.inference.generation import generate_diffusion_cond  # noqa: F401
        except Exception as e:
            return False, f"stable-audio-tools not installed ({e}). Run: pip install stable-audio-tools"
        return True, ""

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self, params: GenParams, model_path=None) -> None:
        key = (params.device, params.offload, str(model_path))
        if self._model is not None and key == self._key:
            return
        self.unload()
        mp = Path(model_path) if model_path else None
        cfg_file = mp / "model_config.json" if mp else None
        weights = next((mp / n for n in ("model.safetensors", "model.ckpt") if mp and (mp / n).is_file()), None)
        if not (cfg_file and cfg_file.is_file() and weights):
            raise RuntimeError("Stable Audio model folder needs model_config.json and model.safetensors "
                               "(download with tools/fetch_stable_audio_small.py, then import the folder).")
        if params.device == "cpu":
            os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
        cache = mp / "hf-cache"                      # T5 text encoder weights for fully offline use
        if cache.is_dir():
            os.environ["HF_HUB_CACHE"] = str(cache)
        import torch
        from stable_audio_tools.models.factory import create_model_from_config
        from stable_audio_tools.models.utils import copy_state_dict, load_ckpt_state_dict

        self._cfg = json.loads(cfg_file.read_text())
        t5 = mp / "t5-base"
        if t5.is_dir():                              # local T5 text encoder: no hub lookup, works fully offline
            _set_key(self._cfg, "t5_model_name", str(t5))
        model = create_model_from_config(self._cfg)
        copy_state_dict(model, load_ckpt_state_dict(str(weights)))
        self._device = "cuda" if params.device == "cuda" and torch.cuda.is_available() else "cpu"
        if self._device == "cuda":
            model = model.to(torch.float16)           # Turing (RTX 20xx) has fast fp16; bf16 is emulated
        model = model.eval().requires_grad_(False)
        self._model = model if params.offload else model.to(self._device)
        self._key = key

    def generate_segment(self, req: SegmentRequest, params: GenParams, progress, cancelled):
        import torch
        from stable_audio_tools.inference.generation import generate_diffusion_cond

        if cancelled():
            raise Cancelled()
        sr = int(self._cfg["sample_rate"])
        size = int(self._cfg["sample_size"])
        dev = self._device
        if params.offload and dev == "cuda":
            self._model.to(dev)                       # only on the GPU while generating
        steps = NATIVE_STEPS

        def cb(d):
            if cancelled():
                raise Cancelled()
            progress(min(1.0, (d.get("i", 0) + 1) / steps))

        try:
            kwargs = _filter(generate_diffusion_cond, dict(
                model=self._model, steps=steps, cfg_scale=1.0, sample_size=size, sampler_type="pingpong",
                device=dev, seed=int(req.seed) % (2**31 - 1), batch_size=1, callback=cb,
                conditioning=[{"prompt": req.prompt, "seconds_total": float(req.duration)}]))
            with torch.no_grad():
                out = generate_diffusion_cond(**kwargs)       # (batch, channels, samples)
        finally:
            if params.offload and dev == "cuda":
                self._model.to("cpu")
                _free_cuda()
        audio = out[0].float().cpu().numpy().T                # (samples, channels)
        audio = audio[: int(req.duration * sr)]
        peak = float(np.max(np.abs(audio))) or 1.0
        return SegmentResult(np.clip(audio / peak, -1, 1).astype(np.float32), sr)

    def unload(self) -> None:
        self._model = self._key = None
        _free_cuda()


# --------------------------------------------------------------------------- LiteRT / numpy
def pingpong_sample(dit, noise: np.ndarray, t: np.ndarray, rng: np.random.Generator,
                    progress=None, cancelled=None) -> np.ndarray:
    """Stable Audio's `sample_flow_pingpong`, in numpy:
         denoised = x - t_i * v(x, t_i);   x = (1 - t_{i+1}) * denoised + t_{i+1} * fresh_noise
    `t` runs from sigma_max (1.0) to 0 over steps+1 points, so the last step returns `denoised`."""
    x = noise
    for i in range(len(t) - 1):
        if cancelled and cancelled():
            raise Cancelled()
        v = dit(x, float(t[i]))
        denoised = x - np.float32(t[i]) * v
        x = (np.float32(1 - t[i + 1]) * denoised
             + np.float32(t[i + 1]) * rng.standard_normal(x.shape).astype(np.float32))
        if progress:
            progress((i + 1) / (len(t) - 1))
    return x


class LiteRTRunner:
    """Runs one .tflite model: run({tensor_name: array}) -> {output_name: array}."""

    def __init__(self, path: Path, threads: int = 4):
        self.path = Path(path)
        self.threads = threads

    def run(self, inputs: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        raise NotImplementedError

    def close(self) -> None:
        pass


def _match(names: list[str], wanted: str) -> int:
    """Find a tensor by exact name, or by the usual 'serving_default_<name>:0' decoration."""
    for i, n in enumerate(names):
        if n == wanted:
            return i
    for i, n in enumerate(names):
        base = n.split(":")[0].replace("serving_default_", "")
        if base == wanted or base.endswith("/" + wanted):
            return i
    raise KeyError(f"tensor '{wanted}' not found in model (has: {names}); fix tensor names in smm-litert.json")


class PythonLiteRTRunner(LiteRTRunner):
    """Desktop/Linux/Windows: `ai-edge-litert` (or tflite_runtime / tensorflow) interpreter."""

    def __init__(self, path, threads=4):
        super().__init__(path, threads)
        try:
            from ai_edge_litert.interpreter import Interpreter
        except ImportError:
            try:
                from tflite_runtime.interpreter import Interpreter
            except ImportError:
                from tensorflow.lite.python.interpreter import Interpreter
        self.it = Interpreter(model_path=str(path), num_threads=threads)
        self.it.allocate_tensors()
        self.ins, self.outs = self.it.get_input_details(), self.it.get_output_details()

    def run(self, inputs):
        names = [d["name"] for d in self.ins]
        for name, arr in inputs.items():
            d = self.ins[_match(names, name)]
            a = np.asarray(arr).astype(d["dtype"])
            if list(a.shape) != list(d["shape"]):
                if a.size != int(np.prod(d["shape"])):
                    self.it.resize_tensor_input(d["index"], list(a.shape))
                    self.it.allocate_tensors()
                    self.ins, self.outs = self.it.get_input_details(), self.it.get_output_details()
                    d = self.ins[_match([x["name"] for x in self.ins], name)]
                else:
                    a = a.reshape(d["shape"])
            self.it.set_tensor(d["index"], a)
        self.it.invoke()
        return {d["name"]: self.it.get_tensor(d["index"]).copy() for d in self.outs}


class AndroidLiteRTRunner(LiteRTRunner):
    """Android: Java `org.tensorflow.lite.Interpreter` through pyjnius (needs the litert gradle dependency).
    NOT run on a device yet - treat as a starting point."""

    def __init__(self, path, threads=4):
        super().__init__(path, threads)
        from jnius import autoclass

        self.J = {n: autoclass(c) for n, c in dict(
            Interpreter="org.tensorflow.lite.Interpreter", Options="org.tensorflow.lite.Interpreter$Options",
            File="java.io.File", ByteBuffer="java.nio.ByteBuffer", ByteOrder="java.nio.ByteOrder",
            HashMap="java.util.HashMap", Integer="java.lang.Integer", Array="java.lang.reflect.Array",
            Object="java.lang.Object").items()}
        opts = self.J["Options"]()
        opts.setNumThreads(threads)
        self.it = self.J["Interpreter"](self.J["File"](str(path)), opts)
        self.in_names = [self.it.getInputTensor(i).name() for i in range(self.it.getInputTensorCount())]
        self.out_names = [self.it.getOutputTensor(i).name() for i in range(self.it.getOutputTensorCount())]

    def _buf(self, arr: np.ndarray):
        raw = np.ascontiguousarray(arr).tobytes()
        b = self.J["ByteBuffer"].allocateDirect(len(raw)).order(self.J["ByteOrder"].nativeOrder())
        b.put(raw)
        b.rewind()
        return b

    def run(self, inputs):
        J = self.J
        arr = J["Array"].newInstance(J["Object"], len(self.in_names))
        shapes = {}
        for name, a in inputs.items():
            i = _match(self.in_names, name)
            t = self.it.getInputTensor(i)
            dt = str(t.dataType()).upper()
            a = np.asarray(a).astype(np.int32 if "INT32" in dt else np.int64 if "INT64" in dt else np.float32)
            J["Array"].set(arr, i, self._buf(a))
        outs = J["HashMap"]()
        bufs = {}
        for i in range(len(self.out_names)):
            t = self.it.getOutputTensor(i)
            shape = list(t.shape())
            shapes[i] = shape
            bufs[i] = J["ByteBuffer"].allocateDirect(int(t.numBytes())).order(J["ByteOrder"].nativeOrder())
            outs.put(J["Integer"](i), bufs[i])
        self.it.runForMultipleInputsOutputs(arr, outs)
        result = {}
        for i, n in enumerate(self.out_names):
            bufs[i].rewind()
            raw = bytes(bytearray(bufs[i].array())) if bufs[i].hasArray() else self._drain(bufs[i])
            result[n] = np.frombuffer(raw, dtype=np.float32).reshape(shapes[i]).copy()
        return result

    @staticmethod
    def _drain(buf) -> bytes:
        out = bytearray(buf.remaining())
        for k in range(len(out)):
            out[k] = buf.get() & 0xFF
        return bytes(out)

    def close(self):
        self.it.close()


def default_runner_factory(path: Path, threads: int = 4) -> LiteRTRunner:
    if os.environ.get("ANDROID_ARGUMENT"):
        return AndroidLiteRTRunner(path, threads)
    return PythonLiteRTRunner(path, threads)


@register
class StableAudioLiteRTBackend(ModelBackend):
    id = "stableaudio_litert"
    name = "Stable Audio Open Small (LiteRT, phones)"
    description = ("Same model family on LiteRT .tflite files: no PyTorch, small RAM, runs on phones. "
                   "Needs converted model files + smm-litert.json (docs/STABLE_AUDIO_LITERT.md).")
    max_segment_seconds = 11
    needs_model = True
    default_model_name = "stable-audio-open-small-litert"
    uses_gpu = False
    can_switch_device_live = True

    runner_factory = staticmethod(default_runner_factory)   # tests/other runtimes replace this
    tokenizer_factory = None                                 # (folder, descriptor) -> callable(text) -> ids

    def __init__(self):
        self._d: dict = {}
        self._r: dict[str, LiteRTRunner] = {}
        self._tok = None
        self._key = None

    @classmethod
    def available(cls):
        if cls.tokenizer_factory is not None:
            return True, ""
        try:
            import sentencepiece  # noqa: F401
        except Exception as e:
            return False, f"sentencepiece not installed ({e}); needed to tokenize prompts for the T5 conditioner"
        if os.environ.get("ANDROID_ARGUMENT"):
            try:
                import jnius  # noqa: F401
            except Exception as e:
                return False, f"pyjnius missing ({e})"
            return True, ""
        for mod in ("ai_edge_litert", "tflite_runtime", "tensorflow"):
            try:
                __import__(mod)
                return True, ""
            except Exception:
                continue
        return False, "no LiteRT runtime. Run: pip install ai-edge-litert"

    @property
    def loaded(self) -> bool:
        return bool(self._r)

    def model_present(self, model_path) -> bool:
        p = Path(model_path) if model_path else None
        return bool(p and (p / "smm-litert.json").is_file())

    def load(self, params: GenParams, model_path=None) -> None:
        key = str(model_path)
        if self._r and key == self._key:
            return
        self.unload()
        mp = Path(model_path) if model_path else None
        if not (mp and (mp / "smm-litert.json").is_file()):
            raise RuntimeError("LiteRT model folder needs smm-litert.json next to the .tflite files "
                               "(see docs/STABLE_AUDIO_LITERT.md).")
        d = json.loads((mp / "smm-litert.json").read_text())
        for part in ("conditioner", "dit", "autoencoder"):
            if part not in d or not (mp / d[part]["file"]).is_file():
                raise RuntimeError(f"smm-litert.json: missing '{part}' entry or file in {mp}")
        self._d = d
        self._r = {p: type(self).runner_factory(mp / d[p]["file"]) for p in ("conditioner", "dit", "autoencoder")}
        if self.tokenizer_factory:
            self._tok = self.tokenizer_factory(mp, d)
        else:
            import sentencepiece as spm

            sp = spm.SentencePieceProcessor(model_file=str(mp / d.get("tokenizer", "spiece.model")))
            n = int(d.get("max_tokens", 64))
            self._tok = lambda text: (sp.encode(text)[: n - 1] + [1] + [0] * n)[:n]     # T5: ids + </s>, pad 0
        self._key = key

    def _run(self, part: str, role_inputs: dict) -> dict:
        spec = self._d[part]
        raw = self._r[part].run({spec["inputs"][role]: arr for role, arr in role_inputs.items()})
        names = list(raw)
        return {role: raw[names[_match(names, tensor)]] for role, tensor in spec["outputs"].items()}

    def generate_segment(self, req: SegmentRequest, params: GenParams, progress, cancelled):
        if cancelled():
            raise Cancelled()
        d = self._d
        sr, size = int(d["sample_rate"]), int(d["sample_size"])
        ids = np.asarray([self._tok(req.prompt)], dtype=np.int32)
        mask = (ids != 0).astype(np.int32)
        mask[:, 0] = 1
        cond = self._run("conditioner", {"ids": ids, "mask": mask,
                                              "seconds": np.asarray([[float(req.duration)]], dtype=np.float32)})
        steps = int(d.get("steps", NATIVE_STEPS))
        t = np.asarray(d.get("t_schedule") or np.linspace(1.0, 0.0, steps + 1), dtype=np.float32)
        rng = np.random.default_rng(int(req.seed))
        shape = (1, int(d["latent_channels"]), int(d.get("latent_length", size // int(d["downsample"]))))
        dit_spec = d["dit"]

        def dit(x, ti):
            roles = {"x": x, "t": np.asarray([ti], dtype=np.float32), "cross": cond["cross"], "global": cond["global"]}
            if "cross_mask" in dit_spec["inputs"] and "cross_mask" in cond:
                roles["cross_mask"] = cond["cross_mask"]
            return self._run("dit", roles)["v"].reshape(x.shape).astype(np.float32)

        x = pingpong_sample(dit, rng.standard_normal(shape).astype(np.float32), t, rng,
                            lambda f: progress(0.9 * f), cancelled)
        audio = self._run("autoencoder", {"latent": x})["audio"]               # (1, ch, samples)
        audio = np.asarray(audio).reshape(-1, audio.shape[-1]).T[: int(req.duration * sr)]
        peak = float(np.max(np.abs(audio))) or 1.0
        progress(1.0)
        return SegmentResult(np.clip(audio / peak, -1, 1).astype(np.float32), sr)

    def unload(self) -> None:
        for r in self._r.values():
            try:
                r.close()
            except Exception:
                pass
        self._r, self._tok, self._key = {}, None, None
        gc.collect()
