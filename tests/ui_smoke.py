"""Headless UI smoke test: run with  xvfb-run -a python tests/ui_smoke.py <outdir>
Drives the real Kivy window with the mock backends and saves screenshots."""
import os
import sys
import tempfile
from pathlib import Path

out = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
out.mkdir(parents=True, exist_ok=True)
os.environ["SUDO_MAKE_MUSIC_HOME"] = str(out / "home")
os.environ["KIVY_NO_ARGS"] = "1"
os.environ["KIVY_AUDIO"] = "sdl2"

from kivy.config import Config
Config.set("graphics", "width", "420")
Config.set("graphics", "height", "800")
from kivy.clock import Clock
from kivy.core.window import Window

from sudo_make_music.ui.app import SudoMakeMusicApp

app = SudoMakeMusicApp()
state = {"n": 0, "phase": "song"}
fail = []


def shot(name):
    Window.screenshot(name=str(out / f"{name}.png"))


def expect(cond, msg):
    if not cond:
        fail.append(msg)
        print("FAIL", msg)


def step(dt):
    r = app.root_widget
    state["n"] += 1
    ph = state["phase"]
    if ph == "song" and state["n"] == 1:
        app.engine.store.value.update({"backend": "mock", "speech_backend": "mock_speech", "ask_on_fallback": False})
        r.refresh_status()
        r.ids.prompt.text, r.ids.dur.value = "lofi chill", 20
        r.generate()
    elif ph == "song" and not r.busy and r.result_id:
        print("SONG", r.message)
        shot("song_done")
        song = r.result_id
        r.save_voice_dialog(song)                     # open the form, then fill and submit it like a user
        pop = [w for w in Window.children if w.__class__.__name__ == "Popup"][0]
        shot("save_voice_form")
        pop.dismiss()
        r.engine.save_voice_from_job(song, "Singer A", 1, 8, "warm alto")
        r.refresh_voices()
        expect(len(r.engine.voices.list()) == 1, "voice saved")
        expect(len(r.engine.history.list()) == 1, "songs untouched")
        r.show("voices")
        state["phase"] = "voices"
        state["n"] = 0
        r.result_id = ""
    elif ph == "voices" and state["n"] == 2:
        shot("voices")
        vid = r.engine.voices.list()[0].id
        r.use_voice(vid, "talk")
        expect(r.mode == "talk" and r.selected_voice_id() == vid, "voice selected for talk")
        r.ids.talk_text.text = "Hello there. This is my saved voice speaking."
        r.generate()
        state["phase"] = "talk"
        state["n"] = 0
    elif ph == "talk" and not r.busy and state["n"] > 2 and r.result_id:
        print("TALK", r.message, r.result_kind)
        expect(r.result_kind == "talk", "talk result")
        shot("talk_done")
        r.show("library")
        state["phase"] = "end"
        state["n"] = 0
    elif ph == "end" and state["n"] == 2:
        shot("library")
        r.show("settings")
    elif ph == "end" and state["n"] == 4:
        shot("settings")
        print("RESULT", "FAIL" if fail else "OK")
        app.stop()
    elif state["n"] > 60:
        print("TIMEOUT", ph, r.message)
        app.stop()


Clock.schedule_interval(step, 0.5)
app.run()
sys.exit(1 if fail else 0)
