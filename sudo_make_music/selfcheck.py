"""`sudo-make-music --selfcheck [report.txt]`: prove an installed build can really run, with no GPU, no models, no window.

Runs numpy, the MP3 encoder, a mock song (WAV + MP3), a talk clip, the voice library and a model-folder check,
then prints a report. Exit code 0 = all passed. CI runs this on the built Windows exe, and testers can run it too.
"""
from __future__ import annotations

import os
import platform
import sys
import tempfile
import time
import wave
from pathlib import Path


def _wait(job, timeout=60):
    t = time.time()
    while job.status in ("queued", "running", "needs_input") and time.time() - t < timeout:
        time.sleep(0.05)
    if job.status != "done":
        raise RuntimeError(f"job ended as {job.status}: {job.error}")


def _seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def run() -> tuple[bool, list[str]]:
    from . import __version__

    lines = [f"sudo make music {__version__} selfcheck", f"python {sys.version.split()[0]} on {platform.platform()}",
             f"frozen={getattr(sys, 'frozen', False)}"]
    ok = True
    home = tempfile.mkdtemp(prefix="smm-selfcheck-")
    os.environ["SUDO_MAKE_MUSIC_HOME"] = home          # never touch the user's real data

    def check(name, fn, fatal=True):
        nonlocal ok
        try:
            lines.append(f"[ok]   {name}: {fn()}")
        except BaseException as e:                     # SystemExit included (Kivy quits without OpenGL)
            lines.append(f"[{'FAIL' if fatal else 'skip'}] {name}: {type(e).__name__}: {e}")
            ok = ok and not fatal

    def numpy_ok():
        import numpy as np
        return f"numpy {np.__version__}"

    def mp3_ok():
        import lameenc
        enc = lameenc.Encoder()
        enc.set_bit_rate(128)
        enc.set_in_sample_rate(44100)
        enc.set_channels(1)
        enc.set_quality(2)
        return f"lameenc encoded {len(enc.encode(b'\x00\x00' * 44100) + enc.flush())} bytes"

    def kivy_ok():
        import kivy
        return f"kivy {kivy.__version__}"

    check("numpy", numpy_ok)
    check("mp3 encoder", mp3_ok)
    check("kivy import", kivy_ok)

    engine = None
    try:
        from .engine import Engine
        from .audio import write_wav
        import numpy as np

        engine = Engine()
        engine.store.value.update({"backend": "mock", "speech_backend": "mock_speech", "ask_on_fallback": False,
                                   "output_format": "mp3"})
        engine.store.value.overrides = {"chunk_seconds": 5, "overlap_seconds": 1.0}

        def song():
            job = engine.submit("selfcheck", "", 12)
            _wait(job)
            wav, mp3 = engine.output_path(job.id, "wav"), engine.output_path(job.id, "mp3")
            if abs(_seconds(wav) - 12) > 0.2 or not mp3 or mp3.stat().st_size < 1000:
                raise RuntimeError("song or mp3 has the wrong size")
            return f"{job.segments} chunks stitched to {_seconds(wav):.1f}s, mp3 {mp3.stat().st_size} bytes"

        def voice_and_talk():
            ref = Path(home) / "ref.wav"
            t = np.arange(3 * 24000) / 24000
            write_wav(ref, (0.3 * np.sin(2 * np.pi * 200 * t))[:, None].astype(np.float32), 24000)
            v = engine.voices.create_from_file(ref, "selfcheck voice")
            job = engine.submit_talk("Hello. This is a self check.", v.id)
            _wait(job)
            return f"cloned voice used, {_seconds(engine.output_path(job.id, 'wav')):.1f}s of speech"

        def models():
            return ", ".join(f"{r['role']}: {'ready' if r['installed'] else 'no model yet'}" for r in engine.model_status())

        check("mock song + mp3 export", song)
        check("voice library + talk mode", voice_and_talk)
        check("model status", models)
    except BaseException as e:
        lines.append(f"[FAIL] engine: {type(e).__name__}: {e}")
        ok = False
    finally:
        if engine:
            engine.shutdown()

    def ui_ok():
        import importlib
        importlib.import_module("sudo_make_music.ui.app")
        return "UI modules load"
    check("UI import (needs OpenGL 2+; informational)", ui_ok, fatal=False)
    lines.append("SELFCHECK PASSED" if ok else "SELFCHECK FAILED")
    return ok, lines


def main(report: str | None) -> int:
    ok, lines = run()
    text = "\n".join(lines)
    try:
        print(text)
    except Exception:
        pass
    if report and report != "-":
        Path(report).write_text(text + "\n", encoding="utf-8")
    return 0 if ok else 1
