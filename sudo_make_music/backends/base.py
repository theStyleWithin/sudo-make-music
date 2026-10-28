"""The model adapter interface. Everything model-specific lives behind this."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from ..memory import GenParams


class Cancelled(Exception):
    """Raised by a backend (or the pipeline) when the user cancels."""


@dataclass
class SegmentRequest:
    prompt: str              # style / genre / mood tags
    lyrics: str              # may be empty -> instrumental
    duration: float          # seconds to generate for this segment
    seed: int
    index: int = 0           # segment number within the song
    total: int = 1
    steps: int | None = None
    context_audio: np.ndarray | None = None   # tail of the previous segment (float32, samples x ch)
    context_sr: int = 0
    extra: dict = field(default_factory=dict)


@dataclass
class SegmentResult:
    audio: np.ndarray        # float32, shape (samples, channels), range [-1, 1]
    sample_rate: int


ProgressFn = Callable[[float], None]   # 0..1 within the segment
CancelFn = Callable[[], bool]


class ModelBackend(ABC):
    """Contract for a music model.

    Lifecycle: load(params) -> generate_segment()* -> unload().
    The pipeline calls load() lazily and unload() when idle, so backends must
    release GPU memory in unload() and be re-loadable afterwards.
    """

    id: str = ""
    name: str = ""
    description: str = ""
    max_segment_seconds: int = 240   # longest single call the model handles
    min_vram_mb: int = 0             # informational, shown in UI
    needs_model: bool = False        # True -> a folder from the ModelStore must be selected
    default_model_name: str = ""      # backends with a downloadable default get an empty folder registered
    can_switch_device_live: bool = True   # False if CUDA<->CPU only works from a fresh process
    supports_context: bool = False   # can condition on the previous segment's tail

    @classmethod
    def available(cls) -> tuple[bool, str]:
        """(usable, reason-if-not). Must not import heavy deps at module import."""
        return True, ""

    @abstractmethod
    def load(self, params: GenParams, model_path: Path | None = None) -> None:
        """Load weights from `model_path` (a ModelStore folder) honouring params.offload /
        params.quantize. Idempotent for identical arguments; reload if they changed."""

    @abstractmethod
    def generate_segment(self, req: SegmentRequest, params: GenParams,
                         progress: ProgressFn, cancelled: CancelFn) -> SegmentResult:
        """Generate one segment. Poll `cancelled()` and raise Cancelled."""

    @abstractmethod
    def unload(self) -> None:
        """Free all GPU memory (and clear the CUDA cache)."""

    @property
    def loaded(self) -> bool:
        return False

    def info(self) -> dict:
        ok, why = self.available()
        return dict(id=self.id, name=self.name, description=self.description,
                    available=ok, unavailable_reason=why,
                    max_segment_seconds=self.max_segment_seconds, needs_model=self.needs_model,
                    supports_context=self.supports_context,
                    min_vram_mb=self.min_vram_mb)


_REGISTRY: dict[str, type[ModelBackend]] = {}


def register(cls: type[ModelBackend]) -> type[ModelBackend]:
    if not cls.id:
        raise ValueError("backend needs an id")
    _REGISTRY[cls.id] = cls
    return cls


def registry() -> dict[str, type[ModelBackend]]:
    return dict(_REGISTRY)
