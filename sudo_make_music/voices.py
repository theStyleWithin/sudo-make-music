"""Voice library. Kept separate from songs: <data>/voices/<id>/{voice.json, ref.wav}.

A voice is a reusable identity: a short mono reference clip (cloned from an uploaded file, taken from a
generated song, or empty for a built-in preset) plus tags, the seed it came from and an optional preset name.
- Talk mode: the reference clip is handed to a cloning speech backend, or `preset` picks a built-in voice.
- Songs: tags + seed + reference clip are used as best-effort conditioning (music models have no true voice id).
"""
from __future__ import annotations

import json
import shutil
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np

from . import paths
from .audio import read_wav, write_wav, to_wav_16bit

MAX_REF_SECONDS = 30.0


@dataclass
class Voice:
    id: str
    name: str
    source: str                 # song | upload | preset
    tags: str = ""              # e.g. "female vocal, warm alto"
    seed: int | None = None     # seed of the song it was taken from
    origin_prompt: str = ""
    preset: str | None = None   # built-in voice name of a speech backend
    has_ref: bool = False
    ref_seconds: float = 0.0
    created: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class VoiceStore:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else paths.home() / "voices"
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, vid: str) -> Path:
        if not vid.isalnum():
            raise ValueError("bad voice id")
        return self.root / vid

    def list(self) -> list[Voice]:
        out = []
        for d in self.root.iterdir():
            try:
                out.append(Voice(**json.loads((d / "voice.json").read_text())))
            except (OSError, ValueError, TypeError):
                continue
        return sorted(out, key=lambda v: v.created, reverse=True)

    def get(self, vid: str) -> Voice | None:
        try:
            return Voice(**json.loads((self._dir(vid) / "voice.json").read_text()))
        except (OSError, ValueError, TypeError):
            return None

    def ref_path(self, vid: str) -> Path | None:
        p = self._dir(vid) / "ref.wav"
        return p if p.is_file() else None

    def ref_audio(self, vid: str) -> tuple[np.ndarray, int] | None:
        p = self.ref_path(vid)
        return read_wav(p) if p else None

    def _save(self, v: Voice) -> Voice:
        d = self._dir(v.id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "voice.json").write_text(json.dumps(v.to_dict(), indent=2))
        return v

    def _new(self, name: str, source: str, **kw) -> Voice:
        name = name.strip()
        if not name:
            raise ValueError("a voice needs a name")
        return Voice(id=uuid.uuid4().hex[:10], name=name, source=source, created=time.time(), **kw)

    def create_from_song(self, wav: Path, name: str, start: float = 0.0, length: float = 15.0,
                         tags: str = "", seed: int | None = None, origin_prompt: str = "") -> Voice:
        audio, sr = read_wav(wav)
        length = min(max(1.0, length), MAX_REF_SECONDS)
        a, b = int(max(0.0, start) * sr), int((max(0.0, start) + length) * sr)
        clip = audio[a:b].mean(axis=1, keepdims=True)
        if len(clip) < sr:
            raise ValueError("that part of the song is shorter than 1 second")
        v = self._new(name, "song", tags=tags.strip(), seed=seed, origin_prompt=origin_prompt,
                      has_ref=True, ref_seconds=len(clip) / sr)
        self._save(v)
        write_wav(self._dir(v.id) / "ref.wav", clip, sr)
        return v

    def create_from_file(self, src: Path, name: str, tags: str = "") -> Voice:
        """Clone source: any audio file (WAV without ffmpeg). Trimmed to MAX_REF_SECONDS, mono."""
        src = Path(src).expanduser()
        if not src.is_file():
            raise ValueError(f"file not found: {src}")
        v = self._new(name, "upload", tags=tags.strip(), has_ref=True)
        d = self._dir(v.id)
        d.mkdir(parents=True, exist_ok=True)
        try:
            to_wav_16bit(src, d / "ref.wav", mono=True, max_seconds=MAX_REF_SECONDS)
            audio, sr = read_wav(d / "ref.wav")
        except Exception:
            shutil.rmtree(d, ignore_errors=True)
            raise
        if len(audio) < sr:
            shutil.rmtree(d, ignore_errors=True)
            raise ValueError("the reference audio must be at least 1 second long (5-15 seconds works best)")
        v.ref_seconds = len(audio) / sr
        return self._save(v)

    def create_preset(self, name: str, preset: str, tags: str = "") -> Voice:
        return self._save(self._new(name, "preset", tags=tags.strip(), preset=preset))

    def update(self, vid: str, name: str | None = None, tags: str | None = None) -> Voice:
        v = self.get(vid)
        if not v:
            raise ValueError("no such voice")
        if name is not None and name.strip():
            v.name = name.strip()
        if tags is not None:
            v.tags = tags.strip()
        return self._save(v)

    def delete(self, vid: str) -> None:
        shutil.rmtree(self._dir(vid), ignore_errors=True)
