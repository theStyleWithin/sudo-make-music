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
<Tog@ToggleButton>:
    size_hint_y: None
    height: dp(44)
    background_normal: ''
    background_down: ''
    background_color: (0.49, 0.61, 1, 1) if self.state == 'down' else (0.17, 0.18, 0.23, 1)
    color: (0, 0, 0, 1) if self.state == 'down' else (0.91, 0.91, 0.93, 1)
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
                    BoxLayout:
                        size_hint_y: None
                        height: dp(44)
                        spacing: dp(8)
                        Tog:
                            id: tog_song
                            text: 'Song'
                            group: 'mode'
                            state: 'down'
                            allow_no_selection: False
                            on_release: root.set_mode('song')
                        Tog:
                            id: tog_talk
                            text: 'Talk'
                            group: 'mode'
                            allow_no_selection: False
                            on_release: root.set_mode('talk')
                    BoxLayout:
                        id: song_box
                        orientation: 'vertical'
                        size_hint_y: None
                        height: self.minimum_height if root.mode == 'song' else 0
                        opacity: 1 if root.mode == 'song' else 0
                        disabled: root.mode != 'song'
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
                            text: 'Duration: %d:%02d' % (dur.value // 60, dur.value % 60)
                        Slider:
                            id: dur
                            min: 10
                            max: root.max_duration
                            value: 60
                            step: 5
                            size_hint_y: None
                            height: dp(36)
                        Cap:
                            text: 'Music model backend'
                        Pick:
                            id: backend
                            on_text: root.on_backend(self.text)
                    BoxLayout:
                        id: talk_box
                        orientation: 'vertical'
                        size_hint_y: None
                        height: self.minimum_height if root.mode == 'talk' else 0
                        opacity: 1 if root.mode == 'talk' else 0
                        disabled: root.mode != 'talk'
                        spacing: dp(6)
                        Cap:
                            text: 'What should the voice say?'
                        TextInput:
                            id: talk_text
                            size_hint_y: None
                            height: dp(150)
                            hint_text: 'Type or paste the text to speak...'
                            background_color: 0.11, 0.12, 0.15, 1
                            foreground_color: 0.91, 0.91, 0.93, 1
                        Cap:
                            text: 'Speed: %.2fx' % speed.value
                        Slider:
                            id: speed
                            min: 0.6
                            max: 1.5
                            value: 1.0
                            step: 0.05
                            size_hint_y: None
                            height: dp(36)
                        Cap:
                            text: 'Speech backend'
                        Pick:
                            id: sbackend
                            on_text: root.on_sbackend(self.text)
                    Cap:
                        text: 'Voice (from your voice library)'
                    Pick:
                        id: voice
                    Cap:
                        text: 'Resource: ' + root.device_note
                    Pick:
                        id: resource
                        values: ['Auto', 'GPU', 'CPU + system RAM']
                        on_text: root.on_resource(self.text)
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
                        Btn:
                            text: 'Re-voice'
                            size_hint_x: 1 if root.result_kind in ('song', 'revoice') else 0
                            opacity: 1 if root.result_kind in ('song', 'revoice') else 0
                            disabled: root.result_kind not in ('song', 'revoice')
                            on_release: root.revoice(root.result_id)
                        Btn:
                            text: 'Save voice'
                            size_hint_x: 1 if root.result_kind == 'song' else 0
                            opacity: 1 if root.result_kind == 'song' else 0
                            disabled: root.result_kind != 'song'
                            on_release: root.save_voice_dialog(root.result_id)
        Screen:
            name: 'voices'
            ScrollView:
                BoxLayout:
                    orientation: 'vertical'
                    size_hint_y: None
                    height: self.minimum_height
                    padding: dp(12)
                    spacing: dp(8)
                    Cap:
                        text: 'Voice library - kept separate from your songs. Only clone voices you have the right to use.'
                        height: dp(36)
                    Label:
                        text: root.model_report
                        markup: True
                        size_hint_y: None
                        height: self.texture_size[1] + dp(8)
                        text_size: self.width, None
                        halign: 'left'
                        font_size: '12sp'
                    Btn:
                        text: 'Clone a voice from an audio file...'
                        on_release: root.pick_voice_file()
                    BoxLayout:
                        size_hint_y: None
                        height: dp(44)
                        spacing: dp(8)
                        Pick:
                            id: preset_pick
                            size_hint_y: None
                            height: dp(44)
                        Btn:
                            text: 'Add preset voice'
                            on_release: root.add_preset()
                    BoxLayout:
                        id: voice_list
                        orientation: 'vertical'
                        size_hint_y: None
                        height: self.minimum_height
                        spacing: dp(8)
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
                        text: 'Speech backend (talk mode)'
                    Pick:
                        id: s_speech
                    Cap:
                        text: 'Singing voice-cloning model backend (re-voice)'
                    Pick:
                        id: s_conv
                    Cap:
                        text: 'Vocal-separation backend (re-voice)'
                    Pick:
                        id: s_sep
                    Cap:
                        text: 'Local models (stored on this device, used offline)'
                    Pick:
                        id: s_model
                        on_text: root.on_model(self.text)
                    BoxLayout:
                        size_hint_y: None
                        height: dp(44)
                        spacing: dp(8)
                        Pick:
                            id: s_imp
                            values: ['as music model', 'as talk-voice model', 'as singing-clone model', 'as vocal-separation model']
                            text: 'as music model'
                            size_hint_y: None
                            height: dp(44)
                        Btn:
                            text: 'Import folder...'
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
                        height: dp(40)
                        Cap:
                            text: 'Hardware warning popup before switching resource'
                            height: dp(40)
                        Switch:
                            id: s_warn
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
                        Btn:
                            text: 'Install voice libraries (Kokoro, Chatterbox)'
                            on_release: root.install_backend(s_cuda.text, True)
                        Btn:
                            text: 'Install singing-clone libraries (Demucs, OpenVoice)'
                            on_release: root.install_backend(s_cuda.text, False, True)
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
            text: 'Voices'
            on_release: root.show('voices')
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
    device_note = StringProperty("")
    mode = StringProperty("song")          # song | talk
    result_kind = StringProperty("")
    model_report = StringProperty("")

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
        self.device_note = {"cuda": "using GPU", "cpu": "using CPU + system RAM"}[st["device"]]
        avail = [b for b in st["backends"] if b["available"]]
        def labels(kind):
            return {b["name"] + ("" if b["available"] else " (not installed)"): b["id"]
                    for b in st["backends"] if b["kind"] == kind}
        self._backend_by_name, self._sbackend_by_name = labels("music"), labels("speech")
        self._conv_by_name, self._sep_by_name = labels("converter"), labels("separator")
        stg = self.engine.store.value
        for spinner, table, cur in ((self.ids.s_conv, self._conv_by_name, stg.converter_backend),
                                    (self.ids.s_sep, self._sep_by_name, stg.separator_backend)):
            spinner.values = list(table)
            for label, bid in table.items():
                if bid == cur:
                    spinner.text = label
        for spinner, table, cur in ((self.ids.backend, self._backend_by_name, self.engine.store.value.backend),
                                    (self.ids.sbackend, self._sbackend_by_name, self.engine.store.value.speech_backend),
                                    (self.ids.s_speech, self._sbackend_by_name, self.engine.store.value.speech_backend)):
            spinner.values = list(table)
            for label, bid in table.items():
                if bid == cur:
                    spinner.text = label
        self._avail = bool(avail)

    def on_backend(self, label):
        bid = getattr(self, "_backend_by_name", {}).get(label)
        if bid and bid != self.engine.store.value.backend:
            self.engine.store.value.update({"backend": bid})
            self.engine.store.save()
            self.refresh_models()

    def on_sbackend(self, label):
        bid = getattr(self, "_sbackend_by_name", {}).get(label)
        if bid and bid != self.engine.store.value.speech_backend:
            self.engine.store.value.update({"speech_backend": bid})
            self.engine.store.save()
            self.ids.s_speech.text = label
            self.refresh_models()
            self.refresh_voices()

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
        i.s_warn.active = s.ask_on_fallback
        i.resource.text = {None: "Auto", "cuda": "GPU", "cpu": "CPU + system RAM"}[o.get("device")]
        self.refresh_models()
        self.refresh_voices()

    def save_settings(self):
        i = self.ids
        num = lambda w, f=int: f(w.text) if w.text.strip() else None
        tri = lambda w: None if w.text == "mode default" else w.text == "on"
        try:
            self.engine.store.value.update(dict(
                memory_mode=i.s_mode.text, seed=i.s_seed.text, steps=num(i.s_steps) or 60,
                idle_unload_seconds=num(i.s_idle) if i.s_idle.text.strip() else 120,
                offline_mode=i.s_offline.active, continuity=i.s_cont.active, ask_on_fallback=i.s_warn.active,
                speech_backend=getattr(self, "_sbackend_by_name", {}).get(i.s_speech.text, self.engine.store.value.speech_backend),
                converter_backend=getattr(self, "_conv_by_name", {}).get(i.s_conv.text, self.engine.store.value.converter_backend),
                separator_backend=getattr(self, "_sep_by_name", {}).get(i.s_sep.text, self.engine.store.value.separator_backend),
                overrides=dict(max_duration=num(i.s_max), chunk_seconds=num(i.s_chunk),
                               overlap_seconds=num(i.s_ov, float), offload=tri(i.s_off), quantize=tri(i.s_q),
                               device={"auto": None, "gpu": "cuda", "cpu": "cpu"}[i.s_dev.text])))
            self.engine.store.save()
        except Exception as e:
            self._say(str(e), True)
            return
        self.refresh_status()
        self._say("Settings saved.")

    # ---- resource selection / hardware warning ---------------------------
    def on_resource(self, label):
        dev = {"Auto": None, "GPU": "cuda", "CPU + system RAM": "cpu"}.get(label, "?")
        if dev == "?" or "resource" not in self.ids or self.engine.store.value.overrides.get("device", None) == dev:
            return
        ov = dict(self.engine.store.value.overrides)
        ov["device"] = dev
        self.engine.store.value.update({"overrides": ov})
        self.engine.store.save()
        self.ids.s_dev.text = {None: "auto", "cuda": "gpu", "cpu": "cpu"}[dev]
        self.refresh_status()
        self._say("Resource changed. If the GPU was already used this session, restart the app to switch." if dev else "Resource: auto.")

    _warn_popup = None

    def _sync_warning(self, job):
        """Show/hide the hardware-warning popup that mirrors job.decision."""
        d = job.decision if job and job.status == "needs_input" else None
        if d and not self._warn_popup:
            from kivy.factory import Factory
            from kivy.uix.label import Label
            from kivy.uix.popup import Popup
            box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))
            msg = Label(text=d["reason"], text_size=(dp(300), None), halign="left", valign="top")
            box.add_widget(msg)
            pop = Popup(title=d["title"], content=box, size_hint=(0.92, None), auto_dismiss=False,
                        height=dp(150 + 54 * len(d["options"])), title_color=(1, 0.8, 0.3, 1))
            for o in d["options"]:
                b = (Factory.Btn if o["id"] == "cancel" else Factory.Primary)(text=o["label"])
                b.bind(on_release=lambda _w, oid=o["id"]: self._answer(job, oid))
                box.add_widget(b)
            self._warn_popup = pop
            pop.open()
        elif not d and self._warn_popup:
            self._warn_popup.dismiss()
            self._warn_popup = None

    def _answer(self, job, choice):
        try:
            self.engine.resolve_decision(job.id, choice)
        except ValueError:
            pass
        if self._warn_popup:
            self._warn_popup.dismiss()
            self._warn_popup = None

    # ---- voice library ---------------------------------------------------
    NO_VOICE = "Random voice (none)"

    def selected_voice_id(self):
        return getattr(self, "_voice_by_label", {}).get(self.ids.voice.text)

    def pick_voice(self, vid):
        label = next((l for l, i in getattr(self, "_voice_by_label", {}).items() if i == vid), self.NO_VOICE)
        self.ids.voice.text = label

    def refresh_voices(self):
        from kivy.factory import Factory
        from kivy.uix.label import Label
        voices = self.engine.voices.list()
        prev = self.selected_voice_id()
        self._voice_by_label = {}
        for v in voices:
            label = v.name + (" (cloned)" if v.source == "upload" else " (preset)" if v.preset and not v.has_ref else "")
            while label in self._voice_by_label:
                label += "'"
            self._voice_by_label[label] = v.id
        self.ids.voice.values = [self.NO_VOICE] + list(self._voice_by_label)
        self.pick_voice(prev)
        try:
            self.ids.preset_pick.values = list(self.engine._backend(self.engine.store.value.speech_backend).preset_voices)
            if self.ids.preset_pick.text not in self.ids.preset_pick.values and self.ids.preset_pick.values:
                self.ids.preset_pick.text = self.ids.preset_pick.values[0]
        except Exception:
            pass
        lines = []
        for r in self.engine.model_status():
            if not r["library"]:
                state = "[color=ff9966]library not installed[/color]"
            elif r.get("needs_model") and not r["installed"]:
                state = "[color=ff6b6b]model missing[/color] - Settings > Models > Import folder (works offline)"
            else:
                state = "[color=5fd38d]ready[/color]"
            lines.append(f"{r['role']}: {r['name']} - {state}")
        self.model_report = "\n".join(lines)
        box = self.ids.voice_list
        box.clear_widgets()
        if not voices:
            box.add_widget(Label(text="No saved voices yet. Save one after a song, or clone one from an audio file.",
                                 size_hint_y=None, height=dp(60), text_size=(dp(300), None)))
        for v in voices:
            card = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(100), spacing=dp(4))
            title = Label(text=v.name, size_hint_y=None, height=dp(24), halign="left", shorten=True, bold=True)
            title.bind(size=lambda w, sz: setattr(w, "text_size", sz))
            how = {"song": "from a song", "upload": "cloned from audio", "preset": "preset"}[v.source]
            meta = Label(text=" · ".join(x for x in (how, v.tags, f"{v.ref_seconds:.0f}s reference" if v.has_ref else "") if x),
                         size_hint_y=None, height=dp(20), font_size="12sp", color=(0.55, 0.57, 0.64, 1),
                         halign="left", shorten=True)
            meta.bind(size=lambda w, sz: setattr(w, "text_size", sz))
            btns = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))

            def add(text, cb, enabled=True):
                b = Factory.Btn(text=text, disabled=not enabled)
                b.bind(on_release=lambda *_: cb())
                btns.add_widget(b)
            add("Hear", lambda i=v.id: self.play_file(self.engine.voices.ref_path(i)), v.has_ref)
            add("Use in song", lambda i=v.id: self.use_voice(i, "song"))
            add("Use in talk", lambda i=v.id: self.use_voice(i, "talk"))
            add("Delete", lambda i=v.id: self.delete_voice(i))
            for w in (title, meta, btns):
                card.add_widget(w)
            box.add_widget(card)

    def use_voice(self, vid, mode):
        self.pick_voice(vid)
        self.set_mode(mode)
        self.show("create")

    def delete_voice(self, vid):
        self.stop_audio()
        self.engine.voices.delete(vid)
        self.refresh_voices()

    def form_popup(self, title, fields, on_ok, ok_text="Save"):
        """fields: [(key, label, default)] -> on_ok({key: text})."""
        from kivy.factory import Factory
        from kivy.uix.label import Label
        from kivy.uix.popup import Popup
        box = BoxLayout(orientation="vertical", spacing=dp(6), padding=dp(10))
        inputs = {}
        for key, label, default in fields:
            box.add_widget(Factory.Cap(text=label))
            inputs[key] = Factory.Field(text=str(default))
            box.add_widget(inputs[key])
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        ok, no = Factory.Primary(text=ok_text), Factory.Btn(text="Cancel")
        row.add_widget(ok)
        row.add_widget(no)
        box.add_widget(row)
        pop = Popup(title=title, content=box, size_hint=(0.92, None), height=dp(120 + 76 * len(fields)))
        no.bind(on_release=pop.dismiss)

        def go(*_):
            vals = {k: w.text for k, w in inputs.items()}
            try:
                on_ok(vals)
                pop.dismiss()
            except Exception as e:
                self._say(str(e), True)
                pop.dismiss()
        ok.bind(on_release=go)
        pop.open()

    def save_voice_dialog(self, job_id):
        def done(v):
            voice = self.engine.save_voice_from_job(job_id, v["name"], float(v["start"] or 0),
                                                    float(v["length"] or 15), v["tags"])
            self.refresh_voices()
            self._say(f"Saved voice '{voice.name}'. Find it in the Voices tab.")
        self.form_popup("Save this song's voice", [
            ("name", "Voice name", ""), ("start", "Take the clip from (seconds) - pick a part with singing", 0),
            ("length", "Clip length (seconds, up to 30)", 15), ("tags", "Voice description (optional), e.g. female vocal, warm alto", "")],
            done)

    def pick_voice_file(self):
        from kivy.factory import Factory
        from kivy.uix.filechooser import FileChooserListView
        from kivy.uix.popup import Popup
        box = BoxLayout(orientation="vertical", spacing=dp(6))
        chooser = FileChooserListView(path=str(Path.home()), filters=["*.wav", "*.mp3", "*.flac", "*.ogg", "*.m4a"])
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        ok, no = Factory.Primary(text="Use this file"), Factory.Btn(text="Cancel")
        row.add_widget(ok)
        row.add_widget(no)
        box.add_widget(chooser)
        box.add_widget(row)
        pop = Popup(title="Choose a clean 5-30s recording of ONE voice", content=box, size_hint=(0.95, 0.9))
        no.bind(on_release=pop.dismiss)

        def go(*_):
            if not chooser.selection:
                return
            path = chooser.selection[0]
            pop.dismiss()
            self.form_popup("Clone this voice", [("name", "Voice name", Path(path).stem), ("tags", "Description (optional)", "")],
                            lambda v: self.clone_voice(path, v["name"], v["tags"]), "Clone")
        ok.bind(on_release=go)
        pop.open()

    def clone_voice(self, path, name, tags):
        v = self.engine.voices.create_from_file(Path(path), name, tags)
        self.refresh_voices()
        self._say(f"Saved voice '{v.name}'. Use it in Talk mode with a cloning backend.")

    def add_preset(self):
        preset = self.ids.preset_pick.text
        if not preset:
            return self._say("This speech backend has no preset voices.", True)
        self.form_popup("Add preset voice", [("name", "Voice name", preset)],
                        lambda v: (self.engine.voices.create_preset(v["name"], preset), self.refresh_voices()))

    # ---- local models ----------------------------------------------------
    def refresh_models(self):
        self._model_by_label = {f"[{m.backend}] {m.name} ({m.size_mb} MB)": m for m in self.engine.models.list()}
        sp = self.ids.s_model
        sp.values = list(self._model_by_label)
        chosen = set(self.engine.store.value.models.values())
        label = next((l for l, m in self._model_by_label.items() if m.id in chosen), None)
        sp.text = label or (sp.values[0] if sp.values else "none installed (backends download once when online)")

    def on_model(self, label):
        m = getattr(self, "_model_by_label", {}).get(label)
        if m:
            self.engine.select_model(m.backend, m.id)

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
                st = self.engine.store.value
                bid = {"as talk-voice model": st.speech_backend, "as singing-clone model": st.converter_backend,
                       "as vocal-separation model": st.separator_backend}.get(self.ids.s_imp.text, st.backend)
                info = self.engine.import_model(path, bid)
                Clock.schedule_once(lambda dt: (self.refresh_models(), self._say(f"Imported {info.name}")))
            except Exception as e:
                Clock.schedule_once(lambda dt, e=e: self._say(f"Import failed: {e}", True))
        threading.Thread(target=work, daemon=True).start()

    def delete_model(self):
        m = getattr(self, "_model_by_label", {}).get(self.ids.s_model.text)
        if not m:
            return self._say("No model selected.", True)
        self.engine.delete_model(m.id)
        self.refresh_models()
        self._say("Model deleted.")

    def unload(self):
        self.engine.unload_all()
        self.refresh_status()

    def show(self, name):
        self.ids.sm.current = name
        if name == "library":
            self.refresh_library()
        if name == "voices":
            self.refresh_voices()

    def _say(self, msg, err=False):
        self.message, self.is_error = msg, err

    # ---- generation ------------------------------------------------------
    def revoice(self, source_id):
        """Re-sing a finished song in the voice picked in the Voice box (needs the separation + cloning models)."""
        self.stop_audio()
        vid = self.selected_voice_id()
        if not vid:
            return self._say("Pick a saved voice in the Voice box first.", True)
        try:
            self.job = self.engine.submit_revoice(source_id, vid)
        except Exception as e:
            return self._say(str(e), True)
        self.result_id = ""
        self.busy, self.progress = True, 0
        self._say("re-voicing…")

    def set_mode(self, m):
        self.mode = m
        self.ids.tog_song.state = "down" if m == "song" else "normal"
        self.ids.tog_talk.state = "down" if m == "talk" else "normal"

    def generate(self):
        self.stop_audio()
        self.result_id = ""
        vid = self.selected_voice_id()
        try:
            if self.mode == "talk":
                self.job = self.engine.submit_talk(self.ids.talk_text.text, vid, self.ids.speed.value)
            else:
                self.job = self.engine.submit(self.ids.prompt.text, self.ids.lyrics.text,
                                              int(self.ids.dur.value), vid)
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
        self._sync_warning(j)
        if j.status == "needs_input":
            self._say(f"{j.message} - waiting for your choice")
            return
        if j.status in ("queued", "running"):
            self._say(f"{j.status} - {j.message} (seed {j.seed})")
            return
        self._sync_warning(None)
        self.busy = False
        self.job = None
        if j.status == "done":
            self.progress = 1
            self._say(f"Done. Seed {j.seed}.")
            self.result_id, self.result_kind = j.id, j.kind
            self.refresh_voices()
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
        self.play_file(self.engine.output_path(job_id, "wav"))

    def play_file(self, path):
        if self.playing:
            return self.stop_audio()
        if not path:
            return self._say("audio file missing", True)
        self.sound = SoundLoader.load(str(path))
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
            talk = (r.get("kind") or "song") == "talk"
            kindtxt = "talk" if talk else f"{r['duration']:.0f}s · {r['mode']}"
            meta = Label(text=f"{when} · {kindtxt} · seed {r['seed']} · {r['status']}",
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
            if (r.get("kind") or "song") in ("song", "revoice"):
                add("Re-voice", lambda i=r["id"]: self.revoice(i), done)
            add("Reuse", lambda r=r: self.reuse(r))
            add("Delete", lambda i=r["id"]: self.delete(i))
            for w in (title, meta, btns):
                card.add_widget(w)
            box.add_widget(card)

    def reuse(self, r):
        if (r.get("kind") or "song") == "talk":
            self.ids.talk_text.text = r["prompt"]
            self.set_mode("talk")
        else:
            self.ids.prompt.text, self.ids.lyrics.text = r["prompt"], r["lyrics"] or ""
            self.set_mode("song")
        self.pick_voice(r.get("voice_id"))
        self.ids.s_seed.text = str(r["seed"])
        self.save_settings()
        self.show("create")

    def delete(self, job_id):
        self.stop_audio()
        self.engine.delete(job_id)
        self.refresh_library()

    # ---- backend install -------------------------------------------------
    def install_backend(self, cuda, speech=False, cloning=False):
        try:
            self.installer.start(cuda, speech, cloning)
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
