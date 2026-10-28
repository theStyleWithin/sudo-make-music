"""Tiny synth backend: no model, no GPU. For tests, UI development and as a
reference implementation of the adapter interface."""
from __future__ import annotations

import time
import zlib

import numpy as np

from ..memory import GenParams
from .base import ModelBackend, SegmentRequest, SegmentResult, Cancelled, register

SR = 44100


@register
class MockBackend(ModelBackend):
    id = "mock"
    name = "Mock synth (no AI)"
    description = "Deterministic chord loop. Verifies chunking/stitching/export without a model."
    max_segment_seconds = 600
    supports_context = True
    uses_gpu = False
    last_request: SegmentRequest | None = None
    oom_unless: callable | None = None   # test hook: raise CUDA OOM while this returns False for params
    seen_params: list = []

    def __init__(self):
        self._loaded = False

    def load(self, params: GenParams, model_path=None) -> None:
        self._loaded = True
        self._params = params

    @property
    def loaded(self) -> bool:
        return self._loaded

    def unload(self) -> None:
        self._loaded = False

    def generate_segment(self, req, params, progress, cancelled):
        self.last_request = req
        self.seen_params = self.seen_params + [params]
        if self.oom_unless and not self.oom_unless(params):
            raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
        rng = np.random.default_rng(req.seed)
        base = 110.0 * 2 ** (zlib.crc32(req.prompt.encode()) % 12 / 12)
        n = int(req.duration * SR)
        t = np.arange(n, dtype=np.float32) / SR
        chord = [1.0, 1.25, 1.5]
        sig = np.zeros(n, dtype=np.float32)
        for i, r in enumerate(chord):
            sig += np.sin(2 * np.pi * base * r * t + rng.uniform(0, 6.28)) / len(chord)
        sig *= 0.5 * (0.6 + 0.4 * np.sin(2 * np.pi * 0.5 * t))
        for step in range(10):
            if cancelled():
                raise Cancelled()
            time.sleep(0.01)
            progress((step + 1) / 10)
        return SegmentResult(np.stack([sig, sig], axis=1), SR)
