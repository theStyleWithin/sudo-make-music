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

    def to_dict(self) -> dict:
        return asdict(self)


MODES: dict[str, dict] = {
    # Longest practical on ~6GB: small chunks, everything offloaded/quantized.
    "safe": dict(max_duration=600, chunk_seconds=60, overlap_seconds=3.0, offload=True, quantize=True),
    "balanced": dict(max_duration=480, chunk_seconds=120, overlap_seconds=3.0, offload=True, quantize=False),
    # Backend-native chunk size, no offload. May OOM on low VRAM.
    "quality": dict(max_duration=300, chunk_seconds=240, overlap_seconds=4.0, offload=False, quantize=False),
}

OVERRIDABLE = ("max_duration", "chunk_seconds", "overlap_seconds", "offload", "quantize")


def recommend_mode(hw: HardwareInfo) -> str:
    """Pick the safe default for detected VRAM. Unknown VRAM -> safe."""
    if hw.vram_mb is None or hw.vram_mb < 8000:
        return "safe"
    if hw.vram_mb < 12000:
        return "balanced"
    return "quality"


def resolve(mode: str, overrides: dict | None = None, vram_mb: int | None = None) -> GenParams:
    if mode not in MODES:
        raise ValueError(f"unknown memory mode {mode!r}")
    cfg = dict(MODES[mode])
    for k, v in (overrides or {}).items():
        if k in OVERRIDABLE and v is not None:
            cfg[k] = v
    cfg["max_duration"] = max(5, int(cfg["max_duration"]))
    cfg["chunk_seconds"] = max(5, int(cfg["chunk_seconds"]))
    cfg["overlap_seconds"] = max(0.0, min(float(cfg["overlap_seconds"]), cfg["chunk_seconds"] / 2))
    return GenParams(mode=mode, **cfg)


def describe(params: GenParams, hw: HardwareInfo) -> str:
    gpu = f"{hw.gpu_name} {hw.vram_mb // 1024}GB" if hw.gpu_name and hw.vram_mb else "no GPU detected"
    flags = []
    flags.append("offload" if params.offload else "no offload")
    flags.append("int8" if params.quantize else "fp16/bf16")
    return f"{params.mode.upper()} · {params.chunk_seconds}s chunks · {', '.join(flags)} · {gpu}"
