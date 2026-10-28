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


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    """16-bit PCM WAV -> float32 (samples, channels), sample rate."""
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError("only 16-bit PCM WAV is supported here")
        ch, sr = w.getnchannels(), w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    return data.reshape(-1, ch), sr


def wav_info(path: Path) -> tuple[int, int, int]:
    """(frames, sample_rate, channels)"""
    with wave.open(str(path), "rb") as w:
        return w.getnframes(), w.getframerate(), w.getnchannels()


def read_wav_range(path: Path, start_s: float, dur_s: float) -> tuple[np.ndarray, int]:
    """Read only a window of a 16-bit WAV (keeps long songs out of RAM)."""
    with wave.open(str(path), "rb") as w:
        ch, sr = w.getnchannels(), w.getframerate()
        w.setpos(min(int(start_s * sr), w.getnframes()))
        raw = w.readframes(int(dur_s * sr))
    return (np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0).reshape(-1, ch), sr


def resample_linear(audio: np.ndarray, sr_from: int, sr_to: int) -> np.ndarray:
    if sr_from == sr_to or len(audio) == 0:
        return audio
    n = int(len(audio) * sr_to / sr_from)
    x = np.linspace(0, len(audio) - 1, n)
    return np.stack([np.interp(x, np.arange(len(audio)), audio[:, c]) for c in range(audio.shape[1])], axis=1).astype(np.float32)


def write_wav(path: Path, audio: np.ndarray, sr: int) -> None:
    audio = audio.reshape(len(audio), -1)
    w = WavWriter(path, sr, audio.shape[1])
    w.write(audio)
    w.close()


def to_wav_16bit(src: Path, dst: Path, mono: bool = True, max_seconds: float | None = None) -> None:
    """Convert any audio file to 16-bit WAV via ffmpeg (WAV input works without it)."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", str(src)]
        if max_seconds:
            cmd += ["-t", str(max_seconds)]
        cmd += (["-ac", "1"] if mono else []) + ["-c:a", "pcm_s16le", str(dst)]
        subprocess.run(cmd, check=True)
        return
    try:
        audio, sr = read_wav(src)
    except Exception as e:
        raise RuntimeError("this file needs ffmpeg to read (only 16-bit WAV works without it)") from e
    if mono:
        audio = audio.mean(axis=1, keepdims=True)
    if max_seconds:
        audio = audio[: int(max_seconds * sr)]
    write_wav(dst, audio, sr)


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
