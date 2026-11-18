"""Safe audio playback.

Kivy's own sound loader decodes the whole file inside the app and talks to the sound card from the
UI thread, so a sound-system problem on someone's PC can freeze or crash the entire app. This player
hands the sound to the operating system instead, in a way the app can always stop:

* Windows: the system's own player (winsound), asynchronous, built into Python.
* Linux / macOS: a small separate player program (pw-play, paplay, aplay, ffplay, sox, afplay).
  It runs in its own process, so if it hangs or crashes the app carries on.
* Anything else (Android): Kivy's sound loader, as a last resort.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path


class PlayerError(RuntimeError):
    pass


def wav_seconds(path) -> float:
    try:
        with wave.open(str(path)) as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except (OSError, EOFError, wave.Error):
        return 0.0


def _tools(path: str) -> list:
    """Candidate command lines for this OS, best first."""
    if sys.platform == "darwin":
        names = [["afplay", path]]
    else:
        names = [["pw-play", path], ["paplay", path], ["aplay", "-q", path],
                 ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path], ["play", "-q", path]]
    return [c for c in names if shutil.which(c[0])]


class AudioPlayer:
    def __init__(self):
        self._proc = None
        self._kv = None
        self._winsound = False
        self._t0 = 0.0
        self.length = 0.0
        self.path = ""
        self.method = ""

    # ---- control ---------------------------------------------------------
    def play(self, path) -> None:
        self.stop()
        path = str(path)
        if not Path(path).is_file():
            raise PlayerError("the audio file is missing")
        self.length = wav_seconds(path)
        self.path = path
        errors = []
        if sys.platform == "win32":
            try:
                import winsound
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                self._winsound, self.method = True, "winsound"
                self._t0 = time.time()
                return
            except Exception as e:                        # not a PCM wav, or no sound device
                errors.append(f"winsound: {e}")
        for cmd in _tools(path):
            try:
                p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    code = p.wait(timeout=0.4)            # most failures (no sound card) show up at once
                except subprocess.TimeoutExpired:
                    code = None
                if code is None or code == 0:
                    self._proc, self.method, self._t0 = p, cmd[0], time.time()
                    return
                errors.append(f"{cmd[0]} exited with code {code}")
            except OSError as e:
                errors.append(f"{cmd[0]}: {e}")
        try:                                              # last resort (Android, or nothing else installed)
            from kivy.core.audio import SoundLoader
            snd = SoundLoader.load(path)
            if snd:
                snd.play()
                self._kv, self.method, self._t0 = snd, "kivy", time.time()
                return
            errors.append("kivy: could not open the file")
        except Exception as e:
            errors.append(f"kivy: {e}")
        raise PlayerError("could not play sound on this computer (" + "; ".join(errors[-3:]) + ")")

    def stop(self) -> None:
        if self._winsound:
            try:
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass
            self._winsound = False
        if self._proc is not None:
            try:
                if self._proc.poll() is None:
                    self._proc.terminate()
                    try:
                        self._proc.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        self._proc.kill()
            except OSError:
                pass
            self._proc = None
        if self._kv is not None:
            try:
                self._kv.stop()
            except Exception:
                pass
            self._kv = None
        self.method = ""

    # ---- state -----------------------------------------------------------
    @property
    def playing(self) -> bool:
        if self._proc is not None:
            return self._proc.poll() is None
        if self._winsound:
            return (time.time() - self._t0) < self.length
        if self._kv is not None:
            return getattr(self._kv, "state", "") == "play"
        return False

    @property
    def position(self) -> float:
        if not self.method:
            return 0.0
        e = time.time() - self._t0
        return min(e, self.length) if self.length else e

    @property
    def fraction(self) -> float:
        return min(1.0, self.position / self.length) if self.length else 0.0
