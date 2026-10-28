"""Headless UI smoke test: run with  xvfb-run -a python tests/ui_smoke.py <outdir>
Drives the real Kivy window with the mock backend and saves screenshots."""
import os
import sys
import tempfile
import time
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
steps = []


def shot(name):
    Window.screenshot(name=str(out / f"{name}.png"))


def step(dt):
    r = app.root_widget
    s = len(steps)
    steps.append(1)
    if s == 0:
        app.engine.store.value.update({"backend": "mock", "ask_on_fallback": False})
        r.refresh_status()
        r.ids.prompt.text = "lofi chill"
        r.ids.dur.value = 20
        r.generate()
    elif s > 0 and r.busy:
        return
    elif r.result_id and "done" not in steps:
        steps.append("done")
        print("RESULT", r.message, r.result_id)
        Clock.schedule_once(lambda d: (shot("create_done"), r.show("library")), 0.3)
        Clock.schedule_once(lambda d: (shot("library"), r.show("settings")), 0.8)
        Clock.schedule_once(lambda d: (shot("settings"), app.stop()), 1.3)
    elif not r.busy and s > 3 and "done" not in steps:
        print("FAILED", r.message)
        app.stop()


Clock.schedule_interval(step, 0.5)
app.run()
