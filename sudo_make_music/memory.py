"""Memory modes: presets tuned for GPU size, plus user overrides on top."""
from __future__ import annotations

from dataclasses import dataclass, asdict, fields

from .hardware import HardwareInfo


@dataclass(frozen=True)
class GenParams:
    mode: str
    max_duration: int       # seconds, hard cap for one song
    chunk_seconds: int      # length generated per backend call
    overlap_seconds: float  # crossfade between chunks
    offload: bool           # CPU offload of idle model parts
    quantize: bool          # INT8 weight quantization where backend supports it
    batch_size: int = 1
    device: str = "cuda"    # cuda | cpu (cpu = system RAM, slow)

    def to_dict(self) -> dict:
        return asdict(self)


MODES: dict[str, dict] = {
    # Longest practical on ~6GB: small chunks, everything offloaded/quantized.
    "safe": dict(max_duration=1800, chunk_seconds=60, overlap_seconds=3.0, offload=True, quantize=True),
    "balanced": dict(max_duration=1200, chunk_seconds=120, overlap_seconds=3.0, offload=True, quantize=False),
    # Backend-native chunk size, no offload. May OOM on low VRAM.
    "quality": dict(max_duration=900, chunk_seconds=240, overlap_seconds=4.0, offload=False, quantize=False),
}

OVERRIDABLE = ("max_duration", "chunk_seconds", "overlap_seconds", "offload", "quantize", "device")
MIN_GPU_VRAM_MB = 2000   # below this (or no GPU at all) the app runs on CPU + system RAM


def recommend_mode(hw: HardwareInfo) -> str:
    """Pick the safe default for detected VRAM. Unknown VRAM -> safe."""
    if hw.vram_mb is None or hw.vram_mb < 8000:
        return "safe"
    if hw.vram_mb < 12000:
        return "balanced"
    return "quality"


def pick_device(vram_mb: int | None, requested: str | None = None) -> str:
    """auto/None -> cuda only if a GPU with usable VRAM exists; otherwise fall back to CPU."""
    if requested in ("cpu", "cuda"):
        return requested
    return "cuda" if (vram_mb or 0) >= MIN_GPU_VRAM_MB else "cpu"


def resolve(mode: str, overrides: dict | None = None, vram_mb: int | None = None) -> GenParams:
    if mode not in MODES:
        raise ValueError(f"unknown memory mode {mode!r}")
    ov = {k: v for k, v in (overrides or {}).items() if k in OVERRIDABLE and v is not None}
    device = pick_device(vram_mb, ov.pop("device", None))
    cfg = dict(MODES[mode])
    if device == "cpu":
        # System RAM instead of VRAM: small chunks (RAM + time per call), int8 to shrink weights,
        # no "offload" (the model already lives in RAM).
        cfg.update(chunk_seconds=min(cfg["chunk_seconds"], 30), offload=False, quantize=True)
    cfg.update(ov)
    cfg["max_duration"] = max(5, int(cfg["max_duration"]))
    cfg["chunk_seconds"] = max(5, int(cfg["chunk_seconds"]))
    cfg["overlap_seconds"] = max(0.0, min(float(cfg["overlap_seconds"]), cfg["chunk_seconds"] / 2))
    return GenParams(mode=mode, device=device, **cfg)


def fallback_options(params: GenParams, can_switch_to_cpu: bool) -> list[tuple[str, str, GenParams | None]]:
    """What the user can pick after running out of GPU memory: (id, button label, new params).
    new params None = needs a restart (applied via settings instead)."""
    from dataclasses import replace

    opts: list[tuple[str, str, GenParams | None]] = []
    if params.device == "cuda" and not (params.offload and params.quantize):
        opts.append(("offload", "Keep GPU, offload to RAM + int8 (slower)",
                     replace(params, offload=True, quantize=True)))
    if params.device == "cuda":
        cpu = replace(params, device="cpu", offload=False, quantize=True)
        if can_switch_to_cpu:
            opts.append(("cpu", "Use CPU + system RAM (much slower)", cpu))
        else:
            opts.append(("cpu_restart", "Switch to CPU, then restart the app", None))
    return opts


def degrade(params: GenParams, can_switch_to_cpu: bool) -> tuple[GenParams, str] | None:
    """Automatic step down (used when hardware warnings are off). None = nothing left to try."""
    for oid, label, new in fallback_options(params, can_switch_to_cpu):
        if new is not None:
            return new, "GPU out of memory - " + ("retrying with CPU offload + int8" if oid == "offload"
                                                  else "falling back to CPU / system RAM (slow)")
    return None


def describe(params: GenParams, hw: HardwareInfo) -> str:
    if params.device == "cpu":
        gpu = "CPU + system RAM" + ("" if hw.gpu_name else " (no GPU detected)")
    else:
        gpu = f"{hw.gpu_name} {hw.vram_mb // 1024}GB" if hw.gpu_name and hw.vram_mb else "GPU"
    flags = []
    flags.append("offload" if params.offload else "no offload")
    flags.append("int8" if params.quantize else "fp16/bf16")
    return f"{params.mode.upper()} · {params.chunk_seconds}s chunks · {', '.join(flags)} · {gpu}"
