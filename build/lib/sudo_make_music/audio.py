"""Streaming WAV output, equal-power crossfade stitching, MP3 export."""
from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np


class WavWriter:
    """Appends float audio to a 16-bit PCM WAV on disk; nothing accumulates in RAM."""

    def __init__(self, path: Path, sample_rate: int, channels: int):
        self.path = Path(path)
        self._w = wave.open(str(self.path), "wb")
        self._w.setnchannels(channels)
        self._w.setsampwidth(2)
        self._w.setframerate(sample_rate)
        self.frames = 0

    def write(self, audio: np.ndarray) -> None:
        pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2")
        self._w.writeframes(pcm.tobytes())
        self.frames += len(pcm)

    def close(self) -> None:
        self._w.close()


def plan_segments(total: float, chunk: float, overlap: float) -> list[float]:
    """Equal-length segments, each <= chunk, whose crossfaded union is `total` seconds."""
    if total <= chunk:
        return [float(total)]
    n = int(np.ceil((total - overlap) / (chunk - overlap)))
    d = (total + (n - 1) * overlap) / n
    return [d] * n


class Stitcher:
    """Crossfades consecutive segments and streams the result to a WavWriter.

    Only the trailing overlap region (a few seconds) is held in memory."""

    def __init__(self, writer: WavWriter, overlap_seconds: float):
        self.w = writer
        self.overlap = overlap_seconds
        self._tail: np.ndarray | None = None

    def add(self, audio: np.ndarray, sample_rate: int) -> None:
        ov = int(self.overlap * sample_rate)
        if self._tail is None:
            keep = min(ov, len(audio))
            self.w.write(audio[: len(audio) - keep])
            self._tail = audio[len(audio) - keep:]
            return
        n = min(len(self._tail), len(audio) // 2)
        if n > 0:
            t = np.linspace(0.0, np.pi / 2, n, dtype=np.float32)[:, None]
            blend = self._tail[-n:] * np.cos(t) + audio[:n] * np.sin(t)
            if len(self._tail) > n:
                self.w.write(self._tail[:-n])
            self.w.write(blend)
        else:
            self.w.write(self._tail)
        rest = audio[n:]
        keep = min(ov, len(rest))
        self.w.write(rest[: len(rest) - keep])
        self._tail = rest[len(rest) - keep:]

    def finish(self) -> None:
        if self._tail is not None and len(self._tail):
            self.w.write(self._tail)
        self._tail = None
        self.w.close()


def export_mp3(wav_path: Path, mp3_path: Path, bitrate: str = "192k") -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(wav_path),
                        "-codec:a", "libmp3lame", "-b:a", bitrate, str(mp3_path)], check=True)
        return mp3_path
    try:
        import lameenc
    except ImportError as e:
        raise RuntimeError("MP3 export needs ffmpeg on PATH or `pip install lameenc`") from e
    enc = lameenc.Encoder()
    with wave.open(str(wav_path), "rb") as w:
        enc.set_bit_rate(int(bitrate.rstrip("k")))
        enc.set_in_sample_rate(w.getframerate())
        enc.set_channels(w.getnchannels())
        enc.set_quality(2)
        with open(mp3_path, "wb") as out:
            while chunk := w.readframes(44100 * 10):
                out.write(enc.encode(chunk))
            out.write(enc.flush())
    return mp3_path
