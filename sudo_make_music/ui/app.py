"""Native Kivy UI (same code runs on Linux, Windows and Android)."""
from __future__ import annotations

import os
import shutil
import time
from dataclasses import asdict
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.core.audio import SoundLoader
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import StringProperty, NumericProperty, BooleanProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.utils import platform

from .. import memory, runtime
from ..engine import Engine

KV = r"""
#:import dp kivy.metrics.dp
<Label>:
    color: 0.91, 0.91, 0.93, 1
<Field@TextInput>:
    multiline: False
    size_hint_y: None
    height: dp(40)
    background_color: 0.11, 0.12, 0.15, 1
    foreground_color: 0.91, 0.91, 0.93, 1
    cursor_color: 0.49, 0.61, 1, 1
    padding: dp(10), dp(10)
<Cap@Label>:
    size_hint_y: None
    height: dp(20)
    font_size: '12sp'
    color: 0.55, 0.57, 0.64, 1
    halign: 'left'
    text_size: self.size
<Btn@Button>:
    size_hint_y: None
    height: dp(44)
    background_normal: ''
    background_color: 0.17, 0.18, 0.23, 1
<Primary@Btn>:
    background_color: 0.49, 0.61, 1, 1
    color: 0, 0, 0, 1
    bold: True
<Pick@Spinner>:
    size_hint_y: None
    height: dp(40)
    background_normal: ''
    background_color: 0.17, 0.18, 0.23, 1

<Root>:
    orientation: 'vertical'
    canvas.before:
        Color:
            rgba: 0.08, 0.08, 0.10, 1
        Rectangle:
            pos: self.pos
            size: self.size
    Label:
        text: root.badge
        size_hint_y: None
        height: dp(32)
        font_size: '12sp'
        color: 0.55, 0.57, 0.64, 1
        text_size: self.width - dp(16), None
        halign: 'left'
        valign: 'middle'
    ScreenManager:
        id: sm
        Screen:
            name: 'create'
            ScrollView:
                BoxLayout:
                    orientation: 'vertical'
                    size_hint_y: None
                    height: self.minimum_height
                    padding: dp(12)
                    spacing: dp(6)
                    Cap:
                        text: 'Style / genre / mood'
                    Field:
                        id: prompt
                        hint_text: 'lo-fi hip hop, mellow, rainy night, piano'
                    Cap:
                        text: 'Lyrics (optional - empty = instrumental)'
                    TextInput:
                        id: lyrics
                        size_hint_y: None
                        height: dp(110)
                        hint_text: '[verse]\n...'
                        background_color: 0.11, 0.12, 0.15, 1
                        foreground_color: 0.91, 0.91, 0.93, 1
                    Cap:
                        text: 'Duration: %d s' % dur.value
                    Slider:
                        id: dur
                        min: 10
                        max: root.max_duration
                        value: 60
                        step: 5
                        size_hint_y: None
                        height: dp(36)
                    Cap:
                        text: 'Model backend'
                    Pick:
                        id: backend
                        on_text: root.on_backend(self.text)
                    BoxLayout:
                        size_hint_y: None
                        height: dp(44)
                        spacing: dp(8)
                        Primary:
                            id: go
                            text: 'Generate'
                            disabled: root.busy
                            on_release: root.generate()
                        Btn:
                            text: 'Cancel'
                            disabled: not root.busy
                            on_release: root.cancel()
                    ProgressBar:
                        max: 1
                        value: root.progress
                        size_hint_y: None
                        height: dp(10)
                    Label:
                        text: root.message
                        size_hint_y: None
                        height: dp(44)
                        text_size: self.width, None
                        halign: 'left'
                        valign: 'top'
                        color: (1, 0.42, 0.42, 1) if root.is_error else (0.55, 0.57, 0.64, 1)
                    BoxLayout:
                        size_hint_y: None
                        height: dp(44) if root.result_id else 0
                        opacity: 1 if root.result_id else 0
                        spacing: dp(8)
                        Btn:
                            text: 'Stop' if root.playing else 'Play'
                            on_release: root.toggle_play(root.result_id)
                        Btn:
                            text: 'Save WAV'
                            on_release: root.save(root.result_id, 'wav')
                        Btn:
                            text: 'Save MP3'
                            on_release: root.save(root.result_id, 'mp3')
        Screen:
            name: 'library'
            ScrollView:
                BoxLayout:
                    id: hist
                    orientation: 'vertical'
                    size_hint_y: None
                    height: self.minimum_height
                    padding: dp(12)
                    spacing: dp(8)
        Screen:
            name: 'settings'
            ScrollView:
                BoxLayout:
                    orientation: 'vertical'
                    size_hint_y: None
                    height: self.minimum_height
                    padding: dp(12)
                    spacing: dp(6)
                    Cap:
                        text: 'Memory mode'
                    Pick:
                        id: s_mode
                        values: ['auto', 'safe', 'balanced', 'quality']
                    Cap:
                        text: 'Seed (blank = random)'
                    Field:
                        id: s_seed
                        input_filter: 'int'
                    Cap:
                        text: 'Steps'
                    Field:
                        id: s_steps
                        input_filter: 'int'
                    Cap:
                        text: 'Max duration (s, blank = mode default)'
                    Field:
                        id: s_max
                        input_filter: 'int'
                    Cap:
                        text: 'Chunk length (s, blank = mode default)'
                    Field:
                        id: s_chunk
                        input_filter: 'int'
                    Cap:
                        text: 'Crossfade (s, blank = mode default)'
                    Field:
                        id: s_ov
                        input_filter: 'float'
                    Cap:
                        text: 'CPU offload'
                    Pick:
                        id: s_off
                        values: ['mode default', 'on', 'off']
                    Cap:
                        text: 'INT8 quantization'
                    Pick:
                        id: s_q
                        values: ['mode default', 'on', 'off']
                    Cap:
                        text: 'Compute device (auto = GPU if it has VRAM, else CPU + system RAM; restart after changing)'
                        height: dp(36)
                    Pick:
                        id: s_dev
                        values: ['auto', 'gpu', 'cpu']
                    Cap:
                        text: 'Unload model when idle (s, 0 = never)'
                    Field:
                        id: s_idle
                        input_filter: 'int'
                    Cap:
                        text: 'Local models for the selected backend (stored on this device, used offline)'
                    Pick:
                        id: s_model
                        on_text: root.on_model(self.text)
                    BoxLayout:
                        size_hint_y: None
                        height: dp(44)
                        spacing: dp(8)
                        Btn:
                            text: 'Import model folder...'
                            on_release: root.pick_folder()
                        Btn:
                            text: 'Delete selected'
                            on_release: root.delete_model()
                    BoxLayout:
                        size_hint_y: None
                        height: dp(40)
                        Cap:
                            text: 'Offline mode: block all network access'
                            height: dp(40)
                        Switch:
                            id: s_offline
                            size_hint_x: None
                            width: dp(90)
                    BoxLayout:
                        size_hint_y: None
                        height: dp(56)
                        Cap:
                            text: 'Continue each chunk from the previous one (experimental; helps long songs hang together)'
                            height: dp(56)
                            valign: 'middle'
                        Switch:
                            id: s_cont
                            size_hint_x: None
                            width: dp(90)
                    Cap:
                        text: root.effective
                        height: dp(36)
                    BoxLayout:
                        size_hint_y: None
                        height: dp(44)
                        spacing: dp(8)
                        Primary:
                            text: 'Save settings'
                            on_release: root.save_settings()
                        Btn:
                            text: 'Unload model now'
                            on_release: root.unload()
                    BoxLayout:
                        id: install_box
                        orientation: 'vertical'
                        size_hint_y: None
                        height: self.minimum_height
                        spacing: dp(6)
                        Cap:
                            text: 'AI backend install (desktop, one-time download, needs internet)'
                        Pick:
                            id: s_cuda
                            values: ['cu126', 'cu124', 'cu121', 'cpu']
                            text: 'cu126'
                        Btn:
                            text: 'Install PyTorch + ACE-Step'
                            on_release: root.install_backend(s_cuda.text)
                        Label:
                            text: root.install_log
                            size_hint_y: None
                            height: dp(120)
                            font_size: '11sp'
                            text_size: self.size
                            halign: 'left'
                            valign: 'top'
                            color: 0.55, 0.57, 0.64, 1
    BoxLayout:
        size_hint_y: None
        height: dp(48)
        Btn:
            text: 'Create'
            on_release: root.show('create')
        Btn:
            text: 'Library'
            on_release: root.show('library')
        Btn:
            text: 'Settings'
            on_release: root.show('settings')
"""


class Root(BoxLayout):
    badge = StringProperty("")
    message = StringProperty("")
    is_error = BooleanProperty(False)
    progress = NumericProperty(0)
    busy = BooleanProperty(False)
    playing = BooleanProperty(False)
    result_id = StringProperty("")
    max_duration = NumericProperty(300)
    effective = StringProperty("")
    install_log = StringProperty("")

    def __init__(self, engine: Engine, **kw):
        super().__init__(**kw)
        self.engine = engine
        self.installer = runtime.Installer()
        self.job = None
        self.sound = None
        self.sound_id = None
        Clock.schedule_once(lambda dt: self._init_ui(), 0)
        Clock.schedule_interval(self._tick, 0.5)

    # ---- setup / refresh -------------------------------------------------
    def _init_ui(self):
        if platform == "android":
            self.ids.install_box.height = 0
            self.ids.install_box.opacity = 0
            self.ids.install_box.disabled = True
        self.refresh_status()
        self.load_settings()
        self.refresh_library()

    def refresh_status(self):
        st = self.engine.status()
        self.badge = st["mode_description"] + ("  |  model loaded" if st["model_loaded"] else "")
        self.max_duration = st["params"]["max_duration"]
        p = st["params"]
        self.effective = (f"Effective: max {p['max_duration']}s, chunk {p['chunk_seconds']}s, "
                          f"offload {p['offload']}, int8 {p['quantize']}")
        avail = [b for b in st["backends"] if b["available"]]
        names = {b["id"]: b["name"] for b in st["backends"]}
        self._backend_by_name = {names[b["id"]] + ("" if b["available"] else " (not installed)"): b["id"]
                                 for b in st["backends"]}
        self.ids.backend.values = list(self._backend_by_name)
        cur = self.engine.store.value.backend
        for label, bid in self._backend_by_name.items():
            if bid == cur:
                self.ids.backend.text = label
        self._avail = bool(avail)

    def on_backend(self, label):
        bid = getattr(self, "_backend_by_name", {}).get(label)
        if bid and bid != self.engine.store.value.backend:
            self.engine.store.value.update({"backend": bid})
            self.engine.store.save()
            self.refresh_models()

    def load_settings(self):
        s, o = self.engine.store.value, self.engine.store.value.overrides
        i = self.ids
        i.s_mode.text = s.memory_mode or "auto"
        i.s_seed.text = "" if s.seed is None else str(s.seed)
        i.s_steps.text = str(s.steps)
        i.s_max.text = str(o.get("max_duration", ""))
        i.s_chunk.text = str(o.get("chunk_seconds", ""))
        i.s_ov.text = str(o.get("overlap_seconds", ""))
        tri = lambda k: "mode default" if o.get(k) is None else ("on" if o[k] else "off")
        i.s_off.text, i.s_q.text = tri("offload"), tri("quantize")
        i.s_dev.text = {None: "auto", "cuda": "gpu", "cpu": "cpu"}[o.get("device")]
        i.s_idle.text = str(s.idle_unload_seconds)
        i.s_offline.active, i.s_cont.active = s.offline_mode, s.continuity
        self.refresh_models()

    def save_settings(self):
        i = self.ids
        num = lambda w, f=int: f(w.text) if w.text.strip() else None
        tri = lambda w: None if w.text == "mode default" else w.text == "on"
        try:
            self.engine.store.value.update(dict(
                memory_mode=i.s_mode.text, seed=i.s_seed.text, steps=num(i.s_steps) or 60,
                idle_unload_seconds=num(i.s_idle) if i.s_idle.text.strip() else 120,
                offline_mode=i.s_offline.active, continuity=i.s_cont.active,
                overrides=dict(max_duration=num(i.s_max), chunk_seconds=num(i.s_chunk),
                               overlap_seconds=num(i.s_ov, float), offload=tri(i.s_off), quantize=tri(i.s_q),
                               device={"auto": None, "gpu": "cuda", "cpu": "cpu"}[i.s_dev.text])))
            self.engine.store.save()
        except Exception as e:
            self._say(str(e), True)
            return
        self.refresh_status()
        self._say("Settings saved.")

    # ---- local models ----------------------------------------------------
    def refresh_models(self):
        bid = self.engine.store.value.backend
        self._model_by_label = {f"{m.name} ({m.size_mb} MB)": m.id for m in self.engine.models.list(bid)}
        sp = self.ids.s_model
        sp.values = list(self._model_by_label)
        sel = self.engine.store.value.models.get(bid)
        label = next((l for l, i in self._model_by_label.items() if i == sel), None)
        sp.text = label or (sp.values[0] if sp.values else "none installed (ACE-Step downloads once when online)")

    def on_model(self, label):
        mid = getattr(self, "_model_by_label", {}).get(label)
        if mid:
            self.engine.select_model(self.engine.store.value.backend, mid)

    def pick_folder(self):
        from kivy.uix.filechooser import FileChooserListView
        from kivy.uix.popup import Popup
        from kivy.factory import Factory
        box = BoxLayout(orientation="vertical", spacing=dp(6))
        chooser = FileChooserListView(dirselect=True, path=str(Path.home()))
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        ok, no = Factory.Primary(text="Import this folder"), Factory.Btn(text="Cancel")
        row.add_widget(ok)
        row.add_widget(no)
        box.add_widget(chooser)
        box.add_widget(row)
        pop = Popup(title="Choose a model folder", content=box, size_hint=(0.95, 0.9))
        no.bind(on_release=pop.dismiss)

        def go(*_):
            sel = chooser.selection[0] if chooser.selection else chooser.path
            pop.dismiss()
            self.import_model(sel)
        ok.bind(on_release=go)
        pop.open()

    def import_model(self, path):
        import threading
        self._say(f"Importing {path} ... (large models take a while)")

        def work():
            try:
                info = self.engine.import_model(path)
                Clock.schedule_once(lambda dt: (self.refresh_models(), self._say(f"Imported {info.name}")))
            except Exception as e:
                Clock.schedule_once(lambda dt, e=e: self._say(f"Import failed: {e}", True))
        threading.Thread(target=work, daemon=True).start()

    def delete_model(self):
        mid = getattr(self, "_model_by_label", {}).get(self.ids.s_model.text)
        if not mid:
            return self._say("No model selected.", True)
        self.engine.delete_model(mid)
        self.refresh_models()
        self._say("Model deleted.")

    def unload(self):
        self.engine.unload_all()
        self.refresh_status()

    def show(self, name):
        self.ids.sm.current = name
        if name == "library":
            self.refresh_library()

    def _say(self, msg, err=False):
        self.message, self.is_error = msg, err

    # ---- generation ------------------------------------------------------
    def generate(self):
        self.stop_audio()
        self.result_id = ""
        try:
            self.job = self.engine.submit(self.ids.prompt.text, self.ids.lyrics.text, int(self.ids.dur.value))
        except Exception as e:
            self._say(str(e), True)
            return
        self.busy, self.progress = True, 0
        self._say("starting…")

    def cancel(self):
        if self.job:
            self.engine.cancel(self.job.id)

    def _tick(self, dt):
        if self.install_log or self.installer.running:
            snap = self.installer.snapshot()
            self.install_log = "\n".join(snap["log"][-8:]) + ("\nDONE - restart the app." if snap["ok"] else "")
        j = self.job
        if not j:
            return
        self.progress = j.progress
        if j.status in ("queued", "running"):
            self._say(f"{j.status} - {j.message} (seed {j.seed})")
            return
        self.busy = False
        self.job = None
        if j.status == "done":
            self.progress = 1
            self._say(f"Done. Seed {j.seed}.")
            self.result_id = j.id
        elif j.status == "error":
            self._say(j.error, True)
        else:
            self._say("Cancelled.")
        self.refresh_status()
        self.refresh_library()

    # ---- playback / export ----------------------------------------------
    def stop_audio(self):
        if self.sound:
            self.sound.stop()
            self.sound = None
        self.playing = False

    def toggle_play(self, job_id):
        if self.playing:
            return self.stop_audio()
        p = self.engine.output_path(job_id, "wav")
        if not p:
            return self._say("audio file missing", True)
        self.sound = SoundLoader.load(str(p))
        if not self.sound:
            return self._say("could not play this file", True)
        self.sound.bind(on_stop=lambda *_: setattr(self, "playing", False))
        self.sound.play()
        self.playing = True

    @staticmethod
    def export_dir() -> Path:
        if platform == "android":
            from android.storage import primary_external_storage_path  # type: ignore
            d = Path(primary_external_storage_path()) / "Music" / "sudo-make-music"
        else:
            d = Path.home() / "Music" / "sudo-make-music"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(self, job_id, fmt):
        try:
            src = self.engine.output_path(job_id, fmt)
            if not src:
                return self._say("file not found", True)
            dst = self.export_dir() / f"song-{job_id}.{fmt}"
            shutil.copyfile(src, dst)
            self._say(f"Saved {dst}")
        except Exception as e:
            self._say(f"Save failed: {e}", True)

    # ---- library ---------------------------------------------------------
    def refresh_library(self):
        box = self.ids.hist
        box.clear_widgets()
        from kivy.uix.label import Label
        from kivy.factory import Factory
        rows = self.engine.history.list()
        if not rows:
            box.add_widget(Label(text="Nothing yet.", size_hint_y=None, height=dp(40)))
        for r in rows:
            card = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(96), spacing=dp(4))
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["created"]))
            title = Label(text=r["prompt"], size_hint_y=None, height=dp(24), halign="left", shorten=True)
            title.bind(size=lambda w, s: setattr(w, "text_size", s))
            meta = Label(text=f"{when} · {r['duration']:.0f}s · {r['mode']} · seed {r['seed']} · {r['status']}",
                         size_hint_y=None, height=dp(20), font_size="12sp", color=(0.55, 0.57, 0.64, 1),
                         halign="left", shorten=True)
            meta.bind(size=lambda w, s: setattr(w, "text_size", s))
            btns = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
            done = r["status"] == "done"
            def add(text, cb, enabled=True):
                b = Factory.Btn(text=text, disabled=not enabled)
                b.bind(on_release=lambda *_: cb())
                btns.add_widget(b)
            add("Play", lambda i=r["id"]: self.toggle_play(i), done)
            add("WAV", lambda i=r["id"]: self.save(i, "wav"), done)
            add("MP3", lambda i=r["id"]: self.save(i, "mp3"), done)
            add("Reuse", lambda r=r: self.reuse(r))
            add("Delete", lambda i=r["id"]: self.delete(i))
            for w in (title, meta, btns):
                card.add_widget(w)
            box.add_widget(card)

    def reuse(self, r):
        self.ids.prompt.text, self.ids.lyrics.text = r["prompt"], r["lyrics"] or ""
        self.ids.s_seed.text = str(r["seed"])
        self.save_settings()
        self.show("create")

    def delete(self, job_id):
        self.stop_audio()
        self.engine.delete(job_id)
        self.refresh_library()

    # ---- backend install -------------------------------------------------
    def install_backend(self, cuda):
        try:
            self.installer.start(cuda)
            self.install_log = "starting…"
        except Exception as e:
            self.install_log = str(e)


class SudoMakeMusicApp(App):
    title = "sudo make music"

    def build(self):
        if platform == "android":
            os.environ.setdefault("SUDO_MAKE_MUSIC_HOME", self.user_data_dir)
        Builder.load_string(KV)
        self.engine = Engine()
        self.root_widget = Root(self.engine)
        return self.root_widget

    def on_stop(self):
        self.engine.shutdown()


def run() -> None:
    runtime.activate()
    SudoMakeMusicApp().run()
