"""Persisted user settings (JSON). Overrides sit on top of the memory-mode preset."""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field, asdict

from . import paths
from .memory import MODES, OVERRIDABLE


@dataclass
class Settings:
    backend: str = field(default_factory=lambda: "stableaudio_litert" if os.environ.get("ANDROID_ARGUMENT") else "acestep")
    speech_backend: str = "chatterbox"  # talk mode
    separator_backend: str = "demucs"   # re-voice: split vocals from backing
    converter_backend: str = "openvoice"  # re-voice: change the singer
    memory_mode: str | None = None      # None -> auto from detected VRAM
    overrides: dict = field(default_factory=dict)  # max_duration/chunk_seconds/overlap_seconds/offload/quantize
    seed: int | None = None             # None -> random per generation
    steps: int = 60
    idle_unload_seconds: int = 120
    output_format: str = "wav"          # wav | mp3
    models: dict = field(default_factory=dict)   # backend id -> selected model id
    offline_mode: bool = False          # block all network access from model libraries
    ask_on_fallback: bool = True        # hardware warning popup before switching resource
    continuity: bool = False            # condition each chunk on the previous one (experimental)

    def update(self, data: dict) -> None:
        if "backend" in data:
            self.backend = str(data["backend"])
        for k in ("separator_backend", "converter_backend"):
            if k in data:
                setattr(self, k, str(data[k]))
        if "speech_backend" in data:
            self.speech_backend = str(data["speech_backend"])
        if "memory_mode" in data:
            m = data["memory_mode"]
            if m not in (None, "auto") and m not in MODES:
                raise ValueError(f"bad memory_mode {m!r}")
            self.memory_mode = None if m == "auto" else m
        if "overrides" in data:
            self.overrides = {k: v for k, v in (data["overrides"] or {}).items()
                              if k in OVERRIDABLE and v is not None}
        if "seed" in data:
            self.seed = None if data["seed"] in (None, "") else int(data["seed"])
        if "steps" in data:
            self.steps = max(1, min(200, int(data["steps"])))
        if "idle_unload_seconds" in data:
            self.idle_unload_seconds = max(0, int(data["idle_unload_seconds"]))
        if "models" in data:
            self.models = {str(k): str(v) for k, v in (data["models"] or {}).items() if v}
        if "offline_mode" in data:
            self.offline_mode = bool(data["offline_mode"])
        if "ask_on_fallback" in data:
            self.ask_on_fallback = bool(data["ask_on_fallback"])
        if "continuity" in data:
            self.continuity = bool(data["continuity"])
        if "output_format" in data:
            if data["output_format"] not in ("wav", "mp3"):
                raise ValueError("output_format must be wav or mp3")
            self.output_format = data["output_format"]


class SettingsStore:
    def __init__(self, path=None):
        self.path = path or paths.home() / "settings.json"
        self._lock = threading.Lock()
        self.value = Settings()
        try:
            for k, v in json.loads(self.path.read_text()).items():
                if hasattr(self.value, k):
                    setattr(self.value, k, v)
        except (OSError, ValueError):
            pass

    def save(self) -> None:
        with self._lock:
            self.path.write_text(json.dumps(asdict(self.value), indent=2))
