"""Native Kivy UI (same code runs on Linux, Windows and Android)."""
from __future__ import annotations

import os
import re
import shutil
import time
from dataclasses import asdict
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import StringProperty, NumericProperty, BooleanProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.utils import platform

from .. import memory, runtime
from ..command import COMMAND, allowed_input, is_command
from ..engine import Engine
from ..player import AudioPlayer, PlayerError

SCALES = (("Small", 1.0), ("Medium", 1.25), ("Large", 1.5), ("Huge", 1.85))


def screen_size() -> tuple:
    """Pixel size of the main screen, (0, 0) if it cannot be found. Used to pick a readable default size."""
    try:
        if os.name == "nt":
            import ctypes
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
            return int(ctypes.windll.user32.GetSystemMetrics(0)), int(ctypes.windll.user32.GetSystemMetrics(1))
        import subprocess
        out = subprocess.run(["xrandr", "--current"], capture_output=True, text=True, timeout=2).stdout
        m = re.search(r"current (\d+) x (\d+)", out)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return 0, 0


def auto_scale(width: int) -> float:
    return 2.0 if width >= 3200 else 1.6 if width >= 2500 else 1.4 if width >= 1900 else 1.15 if width >= 1500 else 1.0


KV = r"""
#:import dp kivy.metrics.dp
#:import NoTransition kivy.uix.screenmanager.NoTransition
#:set C_BG (0.055, 0.059, 0.075, 1)
#:set C_RAIL (0.039, 0.043, 0.055, 1)
#:set C_PANEL (0.086, 0.094, 0.122, 1)
#:set C_LINE (0.15, 0.165, 0.21, 1)
#:set C_TX (0.91, 0.915, 0.93, 1)
#:set C_MUT (0.54, 0.56, 0.63, 1)
#:set C_ACC (0.486, 0.608, 1, 1)
<Label>:
    color: C_TX
<Field@TextInput>:
    multiline: False
    size_hint_y: None
    height: dp(48)
    background_normal: ''
    background_active: ''
    background_color: 0, 0, 0, 0
    foreground_color: C_TX
    hint_text_color: 0.4, 0.42, 0.5, 1
    cursor_color: C_ACC
    padding: dp(14), dp(14), dp(14), dp(14)
    canvas.before:
        Color:
            rgba: C_ACC if self.focus else C_LINE
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(12)]
        Color:
            rgba: C_PANEL
        RoundedRectangle:
            pos: self.x + dp(1), self.y + dp(1)
            size: self.width - dp(2), self.height - dp(2)
            radius: [dp(11)]
<Area@TextInput>:
    background_normal: ''
    background_active: ''
    background_color: 0, 0, 0, 0
    foreground_color: C_TX
    hint_text_color: 0.4, 0.42, 0.5, 1
    cursor_color: C_ACC
    padding: dp(14), dp(14), dp(14), dp(14)
    canvas.before:
        Color:
            rgba: C_ACC if self.focus else C_LINE
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(12)]
        Color:
            rgba: C_PANEL
        RoundedRectangle:
            pos: self.x + dp(1), self.y + dp(1)
            size: self.width - dp(2), self.height - dp(2)
            radius: [dp(11)]
<Cap@Label>:
    size_hint_y: None
    height: dp(20)
    font_size: '12sp'
    color: C_MUT
    halign: 'left'
    valign: 'middle'
    text_size: self.size
<Group@BoxLayout>:
    orientation: 'vertical'
    size_hint_y: None
    height: self.minimum_height
    spacing: dp(8)
<Btn@Button>:
    size_hint_y: None
    height: dp(48)
    background_normal: ''
    background_down: ''
    background_color: 0, 0, 0, 0
    color: C_TX if not self.disabled else (0.4, 0.42, 0.5, 1)
    canvas.before:
        Color:
            rgba: C_LINE
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(12)]
        Color:
            rgba: (0.086, 0.094, 0.122, 1) if self.state == 'normal' else (0.16, 0.18, 0.25, 1)
        RoundedRectangle:
            pos: self.x + dp(1), self.y + dp(1)
            size: self.width - dp(2), self.height - dp(2)
            radius: [dp(11)]
<Primary@Btn>:
    color: (0.04, 0.05, 0.08, 1) if not self.disabled else (0.55, 0.58, 0.7, 1)
    bold: True
    canvas.before:
        Color:
            rgba: (0.486, 0.608, 1, 1) if (not self.disabled and self.state == 'normal') else ((0.36, 0.46, 0.8, 1) if not self.disabled else (0.2, 0.24, 0.36, 1))
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(12)]
<Tog@ToggleButton>:
    size_hint_y: None
    height: dp(44)
    background_normal: ''
    background_down: ''
    background_color: 0, 0, 0, 0
    bold: self.state == 'down'
    color: (0.04, 0.05, 0.08, 1) if self.state == 'down' else C_MUT
    canvas.before:
        Color:
            rgba: C_ACC if self.state == 'down' else C_LINE
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(12)]
        Color:
            rgba: C_ACC if self.state == 'down' else C_BG
        RoundedRectangle:
            pos: self.x + dp(1), self.y + dp(1)
            size: self.width - dp(2), self.height - dp(2)
            radius: [dp(11)]
<NavBtn@Button>:
    size_hint_y: None
    height: dp(48)
    active: False
    background_normal: ''
    background_down: ''
    background_color: 0, 0, 0, 0
    halign: 'left'
    valign: 'middle'
    text_size: self.width - dp(24), self.height
    padding_x: dp(14)
    color: C_TX if self.active else C_MUT
    bold: self.active
    canvas.before:
        Color:
            rgba: C_PANEL if self.active else (0, 0, 0, 0)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(12)]
        Color:
            rgba: C_ACC if self.active else (0, 0, 0, 0)
        RoundedRectangle:
            pos: self.x, self.y + dp(10)
            size: dp(3), self.height - dp(20)
            radius: [dp(2)]
<Tile@BoxLayout>:
    orientation: 'vertical'
    size_hint_y: None
    padding: dp(14)
    spacing: dp(6)
    canvas.before:
        Color:
            rgba: C_LINE
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(14)]
        Color:
            rgba: C_PANEL
        RoundedRectangle:
            pos: self.x + dp(1), self.y + dp(1)
            size: self.width - dp(2), self.height - dp(2)
            radius: [dp(13)]
<SongCard@ButtonBehavior+BoxLayout>:
    orientation: 'vertical'
    size_hint_y: None
    height: dp(292)
    padding: dp(10)
    spacing: dp(4)
    accent: 0.49, 0.61, 1, 1
    selected: False
    canvas.before:
        Color:
            rgba: C_ACC if self.selected else C_LINE
        RoundedRectangle:
            pos: self.x - dp(2), self.y - dp(2)
            size: self.width + dp(4), self.height + dp(4)
            radius: [dp(17)]
        Color:
            rgba: C_PANEL
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(15)]
        Color:
            rgba: self.accent
        RoundedRectangle:
            pos: self.x + dp(6), self.top - dp(74)
            size: self.width - dp(12), dp(68)
            radius: [dp(11), dp(11), dp(4), dp(4)]
<Row@ButtonBehavior+BoxLayout>:
    orientation: 'vertical'
    size_hint_y: None
    height: dp(96)
    padding: dp(14)
    spacing: dp(4)
    selected: False
    canvas.before:
        Color:
            rgba: C_ACC if self.selected else C_LINE
        RoundedRectangle:
            pos: self.x - dp(1), self.y - dp(1)
            size: self.width + dp(2), self.height + dp(2)
            radius: [dp(15)]
        Color:
            rgba: C_PANEL
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(14)]
<Banner@Label>:
    markup: True
    size_hint_y: None
    height: self.texture_size[1] + dp(28)
    text_size: self.width - dp(28), None
    halign: 'left'
    valign: 'middle'
    canvas.before:
        Color:
            rgba: 0.486, 0.608, 1, 0.35
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(12)]
        Color:
            rgba: 0.1, 0.12, 0.19, 1
        RoundedRectangle:
            pos: self.x + dp(1), self.y + dp(1)
            size: self.width - dp(2), self.height - dp(2)
            radius: [dp(11)]
<Section@Label>:
    text_size: self.width, None
    size_hint_y: None
    height: dp(36)
    font_size: '12sp'
    bold: True
    color: C_ACC
    halign: 'left'
    valign: 'bottom'
<Chip@Label>:
    size_hint: None, None
    size: self.texture_size[0] + dp(12), dp(20)
    font_size: '11sp'
    canvas.before:
        Color:
            rgba: 0.14, 0.155, 0.2, 1
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(9)]
<Pick@Spinner>:
    size_hint_y: None
    height: dp(48)
    background_normal: ''
    background_down: ''
    background_color: 0, 0, 0, 0
    color: C_TX
    canvas.before:
        Color:
            rgba: C_LINE
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(12)]
        Color:
            rgba: C_PANEL
        RoundedRectangle:
            pos: self.x + dp(1), self.y + dp(1)
            size: self.width - dp(2), self.height - dp(2)
            radius: [dp(11)]
<Slider>:
    value_track: True
    value_track_color: C_ACC
    cursor_size: dp(22), dp(22)

<Root>:
    orientation: 'horizontal'
    canvas.before:
        Color:
            rgba: C_BG
        Rectangle:
            pos: self.pos
            size: self.size
    BoxLayout:
        orientation: 'vertical'
        size_hint_x: None
        width: dp(184) if root.width > dp(760) else dp(112)
        padding: dp(16)
        spacing: dp(8)
        canvas.before:
            Color:
                rgba: C_RAIL
            Rectangle:
                pos: self.pos
                size: self.size
            Color:
                rgba: C_LINE
            Rectangle:
                pos: self.right - dp(1), self.y
                size: dp(1), self.height
        Label:
            text: '[b]sudo make music[/b]\n[size=11sp][color=8a8fa0]offline  ·  local[/color][/size]'
            markup: True
            size_hint_y: None
            height: dp(64)
            halign: 'left'
            valign: 'top'
            text_size: self.size
            padding_x: dp(6)
        NavBtn:
            text: 'Create'
            active: root.page == 'create'
            on_release: root.show('create')
        NavBtn:
            text: 'Voices'
            active: root.page == 'voices'
            on_release: root.show('voices')
        NavBtn:
            text: 'Library'
            active: root.page == 'library'
            on_release: root.show('library')
        NavBtn:
            text: 'Models'
            active: root.page == 'store'
            on_release: root.show('store')
        NavBtn:
            text: 'Settings'
            active: root.page == 'settings'
            on_release: root.show('settings')
        Widget:
        Label:
            text: root.badge
            font_size: '11sp'
            color: C_MUT
            size_hint_y: None
            height: dp(72)
            halign: 'left'
            valign: 'bottom'
            text_size: self.size
    BoxLayout:
        orientation: 'vertical'
        Label:
            text: root.page_head
            markup: True
            size_hint_y: None
            height: dp(76)
            halign: 'left'
            valign: 'bottom'
            text_size: self.width - dp(64), self.height - dp(10)
        ScreenManager:
            id: sm
            transition: NoTransition()
            Screen:
                name: 'create'
                ScrollView:
                    bar_width: dp(4)
                    BoxLayout:
                        orientation: 'horizontal' if root.width > dp(1000) else 'vertical'
                        size_hint_y: None
                        height: (max(cleft.height, cright.height) if self.orientation == 'horizontal' else cleft.height + cright.height + self.spacing) + dp(32)
                        padding: dp(32), dp(8), dp(32), dp(24)
                        spacing: dp(32)
                        BoxLayout:
                            id: cleft
                            orientation: 'vertical'
                            size_hint_y: None
                            height: self.minimum_height
                            pos_hint: {'top': 1}
                            spacing: dp(16)
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
                                    size_hint_x: None
                                    width: dp(120)
                                    on_release: root.set_mode('song')
                                Tog:
                                    id: tog_talk
                                    text: 'Talk'
                                    group: 'mode'
                                    allow_no_selection: False
                                    size_hint_x: None
                                    width: dp(120)
                                    on_release: root.set_mode('talk')
                                Widget:
                            BoxLayout:
                                id: song_box
                                orientation: 'vertical'
                                size_hint_y: None
                                height: self.minimum_height if root.mode == 'song' else 0
                                opacity: 1 if root.mode == 'song' else 0
                                disabled: root.mode != 'song'
                                spacing: dp(16)
                                Group:
                                    Cap:
                                        text: 'STYLE  ·  genre, mood, instruments'
                                    Field:
                                        id: prompt
                                        hint_text: 'lo-fi hip hop, mellow, rainy night, piano'
                                Group:
                                    Cap:
                                        text: 'LYRICS  ·  optional, empty = instrumental'
                                    Area:
                                        id: lyrics
                                        size_hint_y: None
                                        height: dp(230)
                                        hint_text: '[verse]\n...'
                            BoxLayout:
                                id: talk_box
                                orientation: 'vertical'
                                size_hint_y: None
                                height: self.minimum_height if root.mode == 'talk' else 0
                                opacity: 1 if root.mode == 'talk' else 0
                                disabled: root.mode != 'talk'
                                spacing: dp(16)
                                Group:
                                    Cap:
                                        text: 'WHAT SHOULD THE VOICE SAY?'
                                    Area:
                                        id: talk_text
                                        size_hint_y: None
                                        height: dp(230)
                                        hint_text: 'Type or paste the text to speak...'
                            ProgressBar:
                                max: 1
                                value: root.progress
                                size_hint_y: None
                                height: dp(8) if root.busy else 0
                                opacity: 1 if root.busy else 0
                            Label:
                                text: root.message
                                size_hint_y: None
                                height: dp(44)
                                text_size: self.width, None
                                halign: 'left'
                                valign: 'top'
                                color: (1, 0.42, 0.42, 1) if root.is_error else C_MUT
                            BoxLayout:
                                size_hint_y: None
                                height: dp(44) if root.result_id else 0
                                opacity: 1 if root.result_id else 0
                                disabled: not root.result_id
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
                        BoxLayout:
                            id: cright
                            orientation: 'vertical'
                            size_hint_x: None if root.width > dp(1000) else 1
                            width: dp(340)
                            size_hint_y: None
                            height: self.minimum_height
                            pos_hint: {'top': 1}
                            spacing: dp(16)
                            BoxLayout:
                                id: song_side
                                orientation: 'vertical'
                                size_hint_y: None
                                height: self.minimum_height if root.mode == 'song' else 0
                                opacity: 1 if root.mode == 'song' else 0
                                disabled: root.mode != 'song'
                                spacing: dp(16)
                                Group:
                                    Cap:
                                        text: 'LENGTH  ·  %d:%02d' % (dur.value // 60, dur.value % 60)
                                    Slider:
                                        id: dur
                                        min: 10
                                        max: root.max_duration
                                        value: 60
                                        step: 5
                                        size_hint_y: None
                                        height: dp(40)
                                Group:
                                    Cap:
                                        text: 'ENGINE'
                                    Pick:
                                        id: backend
                                        on_text: root.on_backend(self.text)
                                    Label:
                                        text: root.backend_note
                                        size_hint_y: None
                                        height: (self.texture_size[1] + dp(6)) if root.backend_note else 0
                                        opacity: 1 if root.backend_note else 0
                                        text_size: self.width, None
                                        halign: 'left'
                                        font_size: '12sp'
                                        color: 1, 0.8, 0.3, 1
                            BoxLayout:
                                id: talk_side
                                orientation: 'vertical'
                                size_hint_y: None
                                height: self.minimum_height if root.mode == 'talk' else 0
                                opacity: 1 if root.mode == 'talk' else 0
                                disabled: root.mode != 'talk'
                                spacing: dp(16)
                                Group:
                                    Cap:
                                        text: 'SPEED  ·  %.2fx' % speed.value
                                    Slider:
                                        id: speed
                                        min: 0.6
                                        max: 1.5
                                        value: 1.0
                                        step: 0.05
                                        size_hint_y: None
                                        height: dp(40)
                                Group:
                                    Cap:
                                        text: 'SPEECH ENGINE'
                                    Pick:
                                        id: sbackend
                                        on_text: root.on_sbackend(self.text)
                            Group:
                                Cap:
                                    text: 'VOICE  ·  from your voice library'
                                Pick:
                                    id: voice
                            Group:
                                height: self.minimum_height if root.mode == 'song' else 0
                                opacity: 1 if root.mode == 'song' else 0
                                disabled: root.mode != 'song'
                                Cap:
                                    text: 'TYPE  sudo make music  AND PRESS ENTER'
                                Field:
                                    id: magic
                                    hint_text: 'sudo make music'
                                    write_tab: False
                                    text_validate_unfocus: False
                                    on_text_validate: root.command_entered(self)
                            Btn:
                                text: 'More options  ' + ('v' if root.more else '>')
                                color: C_MUT
                                on_release: root.more = not root.more
                            Group:
                                height: self.minimum_height if root.more else 0
                                opacity: 1 if root.more else 0
                                disabled: not root.more
                                Cap:
                                    text: 'RESOURCE  ·  ' + root.device_note
                                Pick:
                                    id: resource
                                    values: ['Auto', 'GPU', 'CPU + system RAM']
                                    on_text: root.on_resource(self.text)
            Screen:
                name: 'voices'
                ScrollView:
                    bar_width: dp(4)
                    BoxLayout:
                        orientation: 'vertical'
                        size_hint_y: None
                        height: self.minimum_height
                        padding: dp(32), dp(8), dp(32), dp(24)
                        spacing: dp(16)
                        Cap:
                            text: 'Voices are kept separate from your songs. Only clone voices you have the right to use.'
                            height: dp(24)
                        Label:
                            text: root.model_report
                            markup: True
                            size_hint_y: None
                            height: self.texture_size[1] + dp(8)
                            text_size: self.width, None
                            halign: 'left'
                            font_size: '12sp'
                        Group:
                            Cap:
                                text: 'PRESET VOICE  ·  choose one, then press Add preset voice below'
                            Pick:
                                id: preset_pick
                        GridLayout:
                            id: voice_list
                            cols: max(1, int((self.width + dp(16)) // dp(270)))
                            size_hint_y: None
                            height: self.minimum_height
                            spacing: dp(16)
            Screen:
                name: 'store'
                ScrollView:
                    bar_width: dp(4)
                    BoxLayout:
                        orientation: 'vertical'
                        size_hint_y: None
                        height: self.minimum_height
                        padding: dp(32), dp(8), dp(32), dp(24)
                        spacing: dp(12)
                        Banner:
                            text: root.store_header
                        Group:
                            Cap:
                                text: 'SHOW'
                            Pick:
                                id: store_filter
                                values: ['All', 'Music', 'Talk voice', 'Singing voice cloning', 'Vocal separation']
                                text: 'All'
                                on_text: root.refresh_store()
                        Label:
                            text: root.install_status
                            size_hint_y: None
                            height: dp(22) if root.install_status else 0
                            opacity: 1 if root.install_status else 0
                            text_size: self.width, None
                            halign: 'left'
                            font_size: '12sp'
                        ProgressBar:
                            max: 1
                            value: root.install_progress
                            size_hint_y: None
                            height: dp(10) if root.install_status else 0
                            opacity: 1 if root.install_status else 0
                        BoxLayout:
                            id: store_list
                            orientation: 'vertical'
                            size_hint_y: None
                            height: self.minimum_height
                            spacing: dp(10)
                        Cap:
                            text: 'Models installed on this computer'
                        BoxLayout:
                            id: installed_list
                            orientation: 'vertical'
                            size_hint_y: None
                            height: self.minimum_height
                            spacing: dp(8)
            Screen:
                name: 'library'
                ScrollView:
                    bar_width: dp(4)
                    BoxLayout:
                        id: hist
                        orientation: 'vertical'
                        size_hint_y: None
                        height: self.minimum_height
                        padding: dp(32), dp(8), dp(32), dp(24)
                        spacing: dp(16)
            Screen:
                name: 'settings'
                ScrollView:
                    bar_width: dp(4)
                    BoxLayout:
                        orientation: 'vertical'
                        size_hint_y: None
                        height: self.minimum_height
                        padding: max(dp(32), (root.width - dp(184) - dp(760)) / 2), dp(8), max(dp(32), (root.width - dp(184) - dp(760)) / 2), dp(24)
                        spacing: dp(8)
                        Section:
                            text: 'MEMORY AND SPEED'
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
                        Section:
                            text: 'ENGINES'
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
                        Section:
                            text: 'MODELS ON THIS COMPUTER'
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
                        Section:
                            text: 'PRIVACY AND SAFETY'
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
                            height: dp(40)
                            Cap:
                                text: 'Run my antivirus on new model downloads'
                                height: dp(40)
                            Switch:
                                id: s_avscan
                                size_hint_x: None
                                width: dp(90)
                        Cap:
                            text: 'VirusTotal API key (optional, only used to look up file fingerprints; stored unencrypted on this computer)'
                            height: dp(36)
                        Field:
                            id: s_vt
                            password: True
                        Cap:
                            text: 'Model list address (blank = project default)'
                        Field:
                            id: s_cat
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
                            id: install_box
                            orientation: 'vertical'
                            size_hint_y: None
                            height: self.minimum_height
                            spacing: dp(6)
                            Section:
                                text: 'AI BACKEND INSTALL'
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
            height: dp(52) if root.now_title else 0
            opacity: 1 if root.now_title else 0
            disabled: not root.now_title
            padding: dp(32), dp(6)
            spacing: dp(12)
            canvas.before:
                Color:
                    rgba: C_PANEL
                Rectangle:
                    pos: self.pos
                    size: self.size
            Label:
                text: root.now_title
                shorten: True
                halign: 'left'
                text_size: self.size
                valign: 'middle'
            ProgressBar:
                max: 1
                value: root.now_pos
                size_hint_x: 0.5
            Btn:
                text: 'Stop'
                size_hint: None, None
                size: dp(90), dp(40)
                pos_hint: {'center_y': 0.5}
                on_release: root.stop_audio()
        BoxLayout:
            size_hint_y: None
            height: dp(80)
            padding: dp(32), dp(14)
            spacing: dp(16)
            canvas.before:
                Color:
                    rgba: C_RAIL
                Rectangle:
                    pos: self.pos
                    size: self.size
                Color:
                    rgba: C_LINE
                Rectangle:
                    pos: self.x, self.top - dp(1)
                    size: self.width, dp(1)
            Label:
                text: root.bar_status
                markup: True
                color: C_MUT
                halign: 'left'
                valign: 'middle'
                text_size: self.size
                shorten: True
            Btn:
                text: root.act_ghost
                size_hint: None, 1
                width: max(dp(130), self.texture_size[0] + dp(48))
                opacity: 1 if root.act_ghost else 0
                disabled: root.act_ghost_off or not root.act_ghost
                on_release: root.do_ghost()
            Primary:
                text: root.act_primary
                size_hint: None, 1
                width: max(dp(200), self.texture_size[0] + dp(64))
                font_size: '16sp'
                disabled: root.act_primary_off
                on_release: root.do_primary()
"""


class Root(BoxLayout):
    badge = StringProperty("")
    message = StringProperty("")
    is_error = BooleanProperty(False)
    progress = NumericProperty(0)
    busy = BooleanProperty(False)
    playing = BooleanProperty(False)
    page = StringProperty("create")
    page_head = StringProperty("")
    ui_scale = NumericProperty(0)               # chosen interface size (0 = automatic)
    more = BooleanProperty(False)               # "More options" fold on Create
    act_ghost = StringProperty("")              # the two buttons in the bottom-right action bar
    act_primary = StringProperty("")
    act_ghost_off = BooleanProperty(False)
    act_primary_off = BooleanProperty(False)
    bar_status = StringProperty("")
    now_title = StringProperty("")          # the now-playing bar (every screen)
    now_pos = NumericProperty(0)
    result_id = StringProperty("")
    max_duration = NumericProperty(300)
    effective = StringProperty("")
    install_log = StringProperty("")
    device_note = StringProperty("")
    mode = StringProperty("song")          # song | talk
    result_kind = StringProperty("")
    model_report = StringProperty("")
    store_header = StringProperty("")
    backend_note = StringProperty("")
    lib_mode = StringProperty("songs")          # songs | cards
    install_status = StringProperty("")
    install_progress = NumericProperty(0)

    def __init__(self, engine: Engine, **kw):
        super().__init__(**kw)
        self.engine = engine
        self.installer = runtime.Installer()
        self.job = None
        self.player = AudioPlayer()
        self._autoplay = None            # job id of a card being rendered to play at once
        self.sel_card = self.sel_song = ""
        self.page_head = self.HEADS["create"]
        from kivy.core.window import Window
        self._resize_cb = lambda *_: Clock.schedule_once(lambda dt: self._relayout(), 0.25)
        Window.bind(on_resize=self._resize_cb)
        self.ui_scale = engine.store.value.ui_scale
        Clock.schedule_once(lambda dt: self._init_ui(), 0)
        self._tick_ev = Clock.schedule_interval(self._tick, 0.5)

    # ---- setup / refresh -------------------------------------------------
    def _init_ui(self):
        self.ids.magic.input_filter = lambda s, undo: allowed_input(s)   # letters + spaces only
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
        self._update_backend_note()

    def _update_backend_note(self):
        try:
            info = self.engine._backend(self.engine.store.value.backend).info()
            d = info["description"]
            self.backend_note = (d if d.startswith("BETA") else "BETA - " + d) if info.get("beta") else ""
        except Exception:
            self.backend_note = ""

    def use_backend(self, bid):
        self.engine.store.value.update({"backend": bid})
        self.engine.store.save()
        self.refresh_status()
        self.refresh_models()
        self.refresh_store()
        self._say("Music engine changed: it is used for the next song.")

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
        i.s_avscan.active, i.s_vt.text, i.s_cat.text = s.scan_after_download, s.vt_api_key, s.catalog_url
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
                offline_mode=i.s_offline.active, continuity=i.s_cont.active, ask_on_fallback=i.s_warn.active, scan_after_download=i.s_avscan.active,
                vt_api_key=i.s_vt.text, catalog_url=i.s_cat.text,
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
        from kivy.uix.gridlayout import GridLayout
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
            card = Factory.Tile(height=dp(160))
            title = Label(text=v.name, size_hint_y=None, height=dp(24), halign="left", shorten=True, bold=True, font_size="15sp")
            title.bind(size=lambda w, sz: setattr(w, "text_size", sz))
            how = {"song": "from a song", "upload": "cloned from audio", "preset": "preset"}[v.source]
            meta = Label(text=" · ".join(x for x in (how, v.tags, f"{v.ref_seconds:.0f}s reference" if v.has_ref else "") if x),
                         size_hint_y=None, height=dp(20), font_size="12sp", color=(0.55, 0.57, 0.64, 1),
                         halign="left", shorten=True)
            meta.bind(size=lambda w, sz: setattr(w, "text_size", sz))
            btns = GridLayout(cols=2, size_hint_y=None, height=dp(88), spacing=dp(6))

            def add(text, cb, enabled=True):
                b = Factory.Btn(text=text, disabled=not enabled, height=dp(40))
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

    # ---- model store -----------------------------------------------------
    ROLE_FILTER = {"Music": "music", "Talk voice": "speech", "Singing voice cloning": "converter", "Vocal separation": "separator"}
    FIT_COLOR = {"great": "5fd38d", "tight": "e8c04a", "cpu": "ff9966", "no": "ff6b6b"}
    _last_install_id = None

    def popup_text(self, title, text, buttons=()):
        from kivy.factory import Factory
        from kivy.uix.label import Label
        from kivy.uix.popup import Popup
        from kivy.uix.scrollview import ScrollView
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))
        sv = ScrollView()
        lab = Label(text=text, size_hint_y=None, halign="left", valign="top")
        lab.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
        lab.bind(texture_size=lambda w, sz: setattr(w, "height", sz[1]))
        sv.add_widget(lab)
        box.add_widget(sv)
        pop = Popup(title=title, content=box, size_hint=(0.94, 0.8))
        for label, cb in buttons:
            b = Factory.Primary(text=label)
            b.bind(on_release=lambda *_a, cb=cb: cb())
            box.add_widget(b)
        close = Factory.Btn(text="Close")
        close.bind(on_release=pop.dismiss)
        box.add_widget(close)
        pop.open()
        return pop

    def refresh_store(self):
        from kivy.factory import Factory
        from kivy.uix.label import Label
        e = self.engine
        h = e.hw
        pc = (f"{h.gpu_name} ({h.vram_mb // 1024} GB VRAM)" if h.gpu_name and h.vram_mb else "no GPU found") + \
             (f", {h.ram_mb // 1024} GB RAM" if h.ram_mb else "")
        off = "  [color=ff9966]Offline mode is ON: downloading and list refresh are disabled.[/color]" if e.store.value.offline_mode else ""
        self.store_header = (f"[b]Your PC:[/b] {pc}.  List: {e.catalog.source}"
                             + (f" ({e.catalog.updated})" if e.catalog.updated else "") + "." + off)
        role = self.ROLE_FILTER.get(self.ids.store_filter.text)
        box = self.ids.store_list
        box.clear_widgets()
        busy = bool(e.install_task and e.install_task.status == "running")
        if role in (None, "music"):
            card = Factory.Tile(spacing=dp(3))
            using = e.store.value.backend == "procedural"
            txt = ("[b]Procedural music (no AI)[/b]  [color=e8c04a]BETA[/color]  [color=5fd38d]Built in: nothing to download[/color]\n"
                   "Builds songs from rules: style words pick tempo, scale, chords and instruments; your lyrics shape the structure and a "
                   "robotic vowel voice follows each line. Instant and offline on any PC or phone. It sounds like a game score or synth "
                   "track, not a band, and its voice does not pronounce real words.")
            lab = Label(text=txt, markup=True, size_hint_y=None, halign="left", valign="top")
            lab.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
            lab.bind(texture_size=lambda w, sz, card=card: (setattr(w, "height", sz[1] + dp(4)), setattr(card, "height", sz[1] + dp(4) + dp(42) + dp(36))))
            card.add_widget(lab)
            btns = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
            b = (Factory.Btn if using else Factory.Primary)(text="In use for music" if using else "Use for music", disabled=using)
            b.bind(on_release=lambda *_: self.use_backend("procedural"))
            btns.add_widget(b)
            card.add_widget(btns)
            card.height = dp(220)
            box.add_widget(card)
        for r in e.catalog_rows():
            if role and r["role"] != role:
                continue
            card = Factory.Tile(spacing=dp(3))
            tags = ("  [color=e8c04a]* Best for your PC[/color]" if r["best"] else "") + \
                   ("  [color=7c9cff]Lightweight[/color]" if r["lightest"] else "")
            lines = [f"[b]{r['name']}[/b]{tags}",
                     f"{r['description']}",
                     f"[color=8b8fa3]{r['role']} - ~{r['size_mb'] / 1000:.1f} GB - {r['license']} - {r['format']}"
                     + (" - voice cloning" if r["clone"] else "") + "[/color]",
                     f"[color={self.FIT_COLOR[r['fit']]}]{r['fit_label']}[/color]"]
            if r["gated"] and "gated" not in r["notes"].lower():
                lines.append("[color=ff9966]Gated: accept the licence on the model page and set HF_TOKEN first.[/color]")
            if not r["engine_ok"]:
                lines.append("[color=ff9966]Its engine is not installed yet: see the Install buttons in Settings.[/color]")
            if r["notes"]:
                lines.append(f"[color=8b8fa3]{r['notes']}[/color]")
            lab = Label(text="\n".join(lines), markup=True, size_hint_y=None, halign="left", valign="top")
            lab.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
            lab.bind(texture_size=lambda w, sz, card=card: (setattr(w, "height", sz[1] + dp(4)),
                                                           setattr(card, "height", sz[1] + dp(4) + dp(42) + dp(36))))
            card.add_widget(lab)
            btns = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))

            def add(text, cb, enabled=True, primary=False):
                b = (Factory.Primary if primary else Factory.Btn)(text=text, disabled=not enabled)
                b.bind(on_release=lambda *_: cb())
                btns.add_widget(b)
            if r["installed"]:
                add("Installed", lambda: None, False)
                add("Safety scan", lambda i=r["id"]: self.scan_installed(i))
                add("VirusTotal", lambda i=r["id"]: self.vt_installed(i))
            else:
                add("Download", lambda i=r["id"]: self.download(i), not busy and r["fit"] != "no", True)
                add("Model page", lambda u=r["homepage"]: self.open_link(u), bool(r["homepage"]))
            card.add_widget(btns)
            card.height = dp(210)
            box.add_widget(card)
        inst = self.ids.installed_list
        inst.clear_widgets()
        models = e.models.list()
        if not models:
            inst.add_widget(Label(text="None yet.", size_hint_y=None, height=dp(30)))
        for m in models:
            row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
            t = Label(text=f"{m.name} ({m.size_mb} MB)", halign="left", shorten=True, text_size=(dp(150), None))
            row.add_widget(t)
            for text, cb in (("Safety scan", lambda i=m.id: self.scan_installed(i)), ("VirusTotal", lambda i=m.id: self.vt_installed(i))):
                b = Factory.Btn(text=text)
                b.bind(on_release=lambda *_a, cb=cb: cb())
                row.add_widget(b)
            inst.add_widget(row)

    def open_link(self, url):
        import webbrowser
        webbrowser.open(url)

    def _bg(self, work, done):
        """Run work() in a thread; call done(result_or_exception) on the UI thread."""
        import threading

        def run():
            try:
                res = work()
            except Exception as ex:
                res = ex
            Clock.schedule_once(lambda dt: done(res))
        threading.Thread(target=run, daemon=True).start()

    def refresh_store_list(self):
        self._say("Fetching the model list...")

        def done(res):
            if isinstance(res, Exception):
                return self._say(str(res), True)
            self._say(f"Model list updated: {res} models.")
            self.refresh_store()
        self._bg(self.engine.refresh_catalog, done)

    def download(self, entry_id):
        try:
            self.engine.start_install(entry_id)
        except Exception as ex:
            return self._say(str(ex), True)
        self._say("Download started. You can keep using the app.")
        self.refresh_store()

    def cancel_install(self):
        self.engine.cancel_install()

    def _poll_install(self):
        t = self.engine.install_task
        if not t:
            return
        if t.status == "running":
            self.install_progress, self.install_status = t.progress, f"{t.name}: {t.message}"
            return
        if self._last_install_id == t.id:
            return
        self._last_install_id = t.id
        self.install_progress, self.install_status = 0, ""
        if t.status == "done":
            self._say(f"{t.name}: {t.message}")
            self.refresh_models()
            self.refresh_status()
            self.refresh_voices()
            if t.report and "BLOCK" not in t.report and ("WARN" in t.report or "INFO" in t.report):
                self.popup_text("Safety check", t.report)
        else:
            self._say(t.message, t.status == "error")
        self.refresh_store()

    def _show_scan(self, title, res):
        if isinstance(res, Exception):
            return self._say(str(res), True)
        btns = []
        if res.get("sha256"):
            sha = res["sha256"]
            btns.append(("Open on VirusTotal", lambda: self.open_link(__import__("sudo_make_music.virustotal", fromlist=["x"]).gui_url(sha))))
            if self.engine.store.value.vt_api_key:
                btns.append(("Ask VirusTotal (sends only the fingerprint)", lambda: self._vt_api(sha)))
        extra = f"\n\nFile: {res['file']}\nSHA-256: {res['sha256']}" if res.get("sha256") else ""
        self.popup_text(title, res["text"] + extra, btns)

    def scan_installed(self, model_id):
        self._say("Scanning... (large models take a minute)")
        self._bg(lambda: self.engine.scan_model(model_id), lambda res: self._show_scan("Safety scan", res))

    def vt_installed(self, model_id):
        self._say("Fingerprinting the model...")

        def done(res):
            if isinstance(res, Exception):
                return self._say(str(res), True)
            if not res.get("sha256"):
                return self._say("No file to look up.", True)
            self._show_scan("VirusTotal", res)
        self._bg(lambda: self.engine.scan_model(model_id, use_os=False), done)

    def _vt_api(self, sha):
        self._bg(lambda: self.engine.vt_lookup(sha),
                 lambda r: self.popup_text("VirusTotal", r.summary() if not isinstance(r, Exception) else str(r),
                                           [("Open page", lambda: self.open_link(r.url))] if not isinstance(r, Exception) and r.url else []))

    def pick_scan_folder(self):
        from kivy.factory import Factory
        from kivy.uix.filechooser import FileChooserListView
        from kivy.uix.popup import Popup
        box = BoxLayout(orientation="vertical", spacing=dp(6))
        chooser = FileChooserListView(dirselect=True, path=str(Path.home()))
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        ok, no = Factory.Primary(text="Scan this folder"), Factory.Btn(text="Cancel")
        row.add_widget(ok)
        row.add_widget(no)
        box.add_widget(chooser)
        box.add_widget(row)
        pop = Popup(title="Choose a folder to scan", content=box, size_hint=(0.95, 0.9))
        no.bind(on_release=pop.dismiss)

        def go(*_):
            sel = chooser.selection[0] if chooser.selection else chooser.path
            pop.dismiss()
            self._say("Scanning...")
            self._bg(lambda: self.engine.scan_folder_path(sel), lambda res: self._show_scan("Safety scan", res))
        ok.bind(on_release=go)
        pop.open()

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

    HEADS = {
        "create": "[size=24sp][b]Create[/b][/size]   [color=8a8fa0]Describe the song, then press Generate.[/color]",
        "voices": "[size=24sp][b]Voices[/b][/size]   [color=8a8fa0]Saved voices you can reuse in any song.[/color]",
        "library": "[size=24sp][b]Library[/b][/size]   [color=8a8fa0]Every song and song card, in one place.[/color]",
        "store": "[size=24sp][b]Models[/b][/size]   [color=8a8fa0]Pick what makes your music. We checked your PC.[/color]",
        "settings": "[size=24sp][b]Settings[/b][/size]   [color=8a8fa0]Everything has a sensible default.[/color]",
    }

    def show(self, name):
        self.ids.sm.current = name
        self.page, self.page_head = name, self.HEADS.get(name, "")
        if name == "library":
            self.refresh_library()
        if name == "voices":
            self.refresh_voices()
        if name == "store":
            self.refresh_store()
        self._sync_actions()

    def dispose(self):
        """Stop everything this window set going, before it is replaced (interface size change)."""
        from kivy.core.window import Window
        self._tick_ev.cancel()
        Window.unbind(on_resize=self._resize_cb)
        self.player.stop()

    def set_ui_scale(self, value):
        self.engine.store.value.ui_scale = float(value)
        self.engine.store.save()
        self.ui_scale = float(value)
        Clock.schedule_once(lambda dt: App.get_running_app().rebuild(), 0)

    def _relayout(self):
        if self.page == "library":
            self.refresh_library()

    def _sync_actions(self):
        """The bottom-right buttons change with the page: the main thing you do here is always in the same corner."""
        pg, busy = self.page, self.busy
        g, gc, pr, pc = "", False, "", False
        if pg == "create":
            g, gc, pr, pc = "Cancel", not busy, "Generate" if self.mode == "song" else "Speak", busy
        elif pg == "voices":
            g, pr = "Add preset voice", "Clone a voice..."
        elif pg == "library":
            if self.lib_mode == "cards":
                g, pr, pc = "Import card", "Play", not self.sel_card
            else:
                g, gc = "Delete", not self.sel_song
                pr, pc = ("Stop" if self.playing else "Play"), not self.sel_song
        elif pg == "store":
            g, pr = "Scan a folder...", "Refresh list"
        elif pg == "settings":
            g, pr = "Unload model now", "Save settings"
        self.act_ghost, self.act_ghost_off, self.act_primary, self.act_primary_off = g, gc, pr, pc
        j = self.job
        if busy and j is not None:
            self.bar_status = f"[color=e8c04a]Working[/color]  -  {j.status} - {j.message}"
        else:
            self.bar_status = "[color=58d68d]Ready[/color]"

    def do_ghost(self):
        pg = self.page
        if pg == "create":
            self.cancel()
        elif pg == "voices":
            self.add_preset()
        elif pg == "library":
            if self.lib_mode == "cards":
                self.pick_card_file()
            elif self.sel_song:
                self.delete(self.sel_song)
        elif pg == "store":
            self.pick_scan_folder()
        elif pg == "settings":
            self.unload()

    def do_primary(self):
        pg = self.page
        if pg == "create":
            self.generate()
        elif pg == "voices":
            self.pick_voice_file()
        elif pg == "library":
            if self.lib_mode == "cards":
                if self.sel_card:
                    self.render_card(self.sel_card, play=True)
            elif self.sel_song:
                self.toggle_play(self.sel_song)
        elif pg == "store":
            self.refresh_store_list()
        elif pg == "settings":
            self.save_settings()

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

    def command_entered(self, box):
        """Enter pressed in the command box. The text is only compared with the phrase, never executed."""
        if is_command(box.text):
            if self.busy:
                return self._say("Already generating - wait for it to finish or press Cancel.", True)
            box.text = ""
            self.generate()
        else:
            self._say(f'This box only accepts the phrase "{COMMAND}" (then Enter).', True)
        box.focus = True

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
        self._poll_install()
        self._sync_actions()
        if self.install_log or self.installer.running:
            snap = self.installer.snapshot()
            self.install_log = "\n".join(snap["log"][-8:]) + ("\nDONE - restart the app." if snap["ok"] else "")
        if self.playing:
            if self.player.playing:
                self.now_pos = self.player.fraction
            else:
                self.stop_audio()
        j = self.job
        if not j:
            return
        self.progress = j.progress
        if self._autoplay == j.id and j.status in ("queued", "running"):
            self.now_title, self.now_pos = f"Rendering {j.prompt}...", j.progress
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
        auto, self._autoplay = self._autoplay == j.id, None
        if auto and j.status != "done":
            self.now_title = ""
        if j.status == "done":
            self.progress = 1
            self._say(f"Done. Seed {j.seed}.")
            self.result_id, self.result_kind = j.id, j.kind
            self.refresh_voices()
            if auto:
                self.play_file(self.engine.output_path(j.id, "wav"), j.prompt)
        elif j.status == "error":
            self._say(j.error, True)
        else:
            self._say("Cancelled.")
        self.refresh_status()
        self.refresh_library()

    # ---- playback / export ----------------------------------------------
    def stop_audio(self):
        self.player.stop()
        self.playing = False
        self.now_title, self.now_pos = "", 0

    def toggle_play(self, job_id):
        self.play_file(self.engine.output_path(job_id, "wav"), self._title_of(job_id))

    def _title_of(self, job_id):
        try:
            row = self.engine.history.get(job_id)
            return (row or {}).get("prompt", "") or "Song"
        except Exception:
            return "Song"

    def play_file(self, path, title=""):
        if self.playing:
            return self.stop_audio()
        if not path:
            return self._say("audio file missing", True)
        try:
            self.player.play(path)
        except PlayerError as e:
            return self._say(str(e), True)
        self.playing = True
        self.now_title, self.now_pos = title or "Playing", 0

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
        from kivy.factory import Factory
        from kivy.uix.gridlayout import GridLayout
        box = self.ids.hist
        box.clear_widgets()
        sw = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        for label, mode in (("Cards", "cards"), ("Songs", "songs")):
            t = Factory.Tog(text=label, group="libmode", allow_no_selection=False, size_hint_x=None, width=dp(120),
                            state="down" if self.lib_mode == mode else "normal")
            t.bind(on_release=lambda *_a, m=mode: self.set_lib_mode(m))
            sw.add_widget(t)
        sw.add_widget(BoxLayout())
        box.add_widget(sw)
        from kivy.core.window import Window
        two = Window.width > dp(1000)
        outer = BoxLayout(orientation="horizontal" if two else "vertical", size_hint_y=None, spacing=dp(32))
        outer.bind(minimum_height=lambda *_: None)
        left_w = (Window.width - dp(184 + 340 + 96 + 32)) if two else (Window.width - dp(184 + 64))
        gcols = max(1, int(left_w // dp(240)))
        grid = GridLayout(cols=gcols, spacing=dp(16), size_hint_y=None)
        grid.bind(minimum_height=grid.setter("height"))
        grid.pos_hint = {"top": 1}
        side = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(12), pos_hint={"top": 1})
        if two:
            side.size_hint_x, side.width = None, dp(340)
        side.bind(minimum_height=side.setter("height"))
        if self.lib_mode == "cards":
            self._cards_view(grid, side)
        else:
            self._songs_view(grid, side)
        outer.add_widget(grid)
        outer.add_widget(side)

        def fit(*_):
            outer.height = max(grid.height, side.height) if two else grid.height + side.height + outer.spacing
        grid.bind(height=fit)
        side.bind(height=fit)
        box.add_widget(outer)
        fit()
        self._sync_actions()

    def _panel_text(self, side, head, title, meta):
        from kivy.factory import Factory
        from kivy.uix.label import Label
        side.add_widget(Factory.Cap(text=head))
        t = Factory.Tile(height=dp(86))
        for text, kw in ((title, dict(bold=True, font_size="15sp")), (meta, dict(font_size="12sp", color=(0.54, 0.56, 0.63, 1)))):
            w = Label(text=text, size_hint_y=None, height=dp(24), halign="left", shorten=True, **kw)
            w.bind(size=lambda x, sz: setattr(x, "text_size", sz))
            t.add_widget(w)
        side.add_widget(t)

    def _panel_actions(self, side, head, actions):
        from kivy.factory import Factory
        side.add_widget(Factory.Cap(text=head))
        for text, cb, ok in actions:
            b = Factory.Btn(text=text + "   >", disabled=not ok, halign="left", valign="middle")
            b.bind(on_release=lambda *_a, cb=cb: cb())
            b.bind(size=lambda x, sz: setattr(x, "text_size", (sz[0] - dp(28), sz[1])))
            side.add_widget(b)

    def _songs_view(self, grid, side):
        from kivy.factory import Factory
        from kivy.uix.label import Label
        rows = self.engine.history.list()
        if not rows:
            grid.add_widget(Label(text="Nothing yet. Songs you make appear here.", size_hint_y=None, height=dp(60), color=(0.54, 0.56, 0.63, 1)))
            return
        if self.sel_song not in {r["id"] for r in rows}:
            self.sel_song = rows[0]["id"]
        chosen = None
        for r in rows:
            sel = r["id"] == self.sel_song
            if sel:
                chosen = r
            tile = Factory.Row()
            tile.selected = sel
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["created"]))
            talk = (r.get("kind") or "song") == "talk"
            kindtxt = "talk" if talk else f"{r['duration']:.0f}s - {r['mode']}"
            for text, kw in ((r["prompt"], dict(bold=True, font_size="14sp")),
                             (f"{when}  -  {kindtxt}  -  {r['status']}", dict(font_size="11sp", color=(0.54, 0.56, 0.63, 1)))):
                w = Label(text=text, size_hint_y=None, height=dp(22), halign="left", shorten=True, **kw)
                w.bind(size=lambda x, sz: setattr(x, "text_size", sz))
                tile.add_widget(w)
            tile.bind(on_release=lambda *_a, i=r["id"]: self.select_song(i))
            grid.add_widget(tile)
        r = chosen
        done = r["status"] == "done"
        talk = (r.get("kind") or "song") == "talk"
        self._panel_text(side, "SELECTED SONG", r["prompt"], f"seed {r['seed']}  -  {r['status']}")
        acts = [("Save WAV", lambda i=r["id"]: self.save(i, "wav"), done), ("Save MP3", lambda i=r["id"]: self.save(i, "mp3"), done)]
        if (r.get("kind") or "song") in ("song", "revoice"):
            acts.append(("Re-voice", lambda i=r["id"]: self.revoice(i), done))
        cid = (r.get("params") or {}).get("card_id")
        if cid and self.engine.cards.get(cid):
            acts.append(("Open its song card", lambda c=cid: self.card_dialog(c), True))
        acts.append(("Reuse these settings", lambda r=r: self.reuse(r), True))
        self._panel_actions(side, "DO SOMETHING WITH IT", acts)

    def select_song(self, sid):
        self.sel_song = sid
        self.refresh_library()

    def select_card(self, cid):
        self.sel_card = cid
        self.refresh_library()

    # ---- song cards (procedural songs kept on file for re-use, remix and extend) ----
    def set_lib_mode(self, mode):
        self.lib_mode = mode
        self.refresh_library()

    def _cards_view(self, grid, side):
        from kivy.uix.label import Label
        cards = self.engine.cards.list()
        if not cards:
            grid.add_widget(Label(text="No cards yet. Every song made with the procedural engine keeps one here.",
                                  size_hint_y=None, height=dp(60), color=(0.54, 0.56, 0.63, 1)))
            return
        if self.sel_card not in {c.id for c in cards}:
            self.sel_card = cards[0].id
        for c in cards:
            grid.add_widget(self._song_card(c))
        c = next(x for x in cards if x.id == self.sel_card)
        self._panel_text(side, "SELECTED CARD", c.name, c.recipe.summary())
        self._panel_actions(side, "DO SOMETHING WITH IT", [
            ("Remix", lambda i=c.id: self.card_remix_dialog(i), True),
            ("Extend with a new tune", lambda i=c.id: self.card_extend_dialog(i), True),
            ("Export card file", lambda i=c.id: self.export_card(i), True),
            ("Delete card", lambda i=c.id: self.delete_card(i), True)])

    ACCENTS = [(0.49, 0.61, 1, 1), (0.95, 0.55, 0.45, 1), (0.45, 0.8, 0.6, 1), (0.85, 0.7, 0.35, 1),
               (0.75, 0.55, 0.95, 1), (0.4, 0.78, 0.85, 1)]

    def _song_card(self, c):
        """A real card: coloured header (genre), the recipe as ingredients, form chips, lyric peek, actions."""
        import zlib
        from kivy.factory import Factory
        from kivy.uix.label import Label
        from kivy.uix.gridlayout import GridLayout
        r, st = c.recipe, c.recipe.style
        from ..backends.procedural import NOTE_NAMES
        card = Factory.SongCard(height=dp(300))
        card.accent = self.ACCENTS[zlib.crc32(st["name"].encode()) % len(self.ACCENTS)]

        def lab(text, h, **kw):
            w = Label(text=text, size_hint_y=None, height=dp(h), halign=kw.pop("halign", "left"), valign="middle", **kw)
            w.bind(size=lambda x, s: setattr(x, "text_size", s))
            return w
        head = lab(st["name"].upper(), 38, bold=True, font_size="20sp", color=(0.05, 0.05, 0.08, 1), shorten=True)
        sub = lab(("SAMPLE CARD" if c.name.startswith("Sample: ") else "SONG CARD") + ("  (older engine)" if c.stale else ""), 18, font_size="10sp", color=(0.1, 0.1, 0.15, 0.8))
        card.add_widget(head); card.add_widget(sub)
        card.add_widget(Label(size_hint_y=None, height=dp(12)))          # sits over the header's lower edge
        card.add_widget(lab(c.name, 36, bold=True, font_size="13sp", shorten=True, shorten_from="right"))
        mm, ss = divmod(int(round(r.duration)), 60)
        facts = GridLayout(cols=2, size_hint_y=None, height=dp(66), spacing=dp(2))
        for k, v in (("Key", f"{NOTE_NAMES[st['root_pc']]} {st['mode'].replace('_', ' ')}"), ("Tempo", f"{st['bpm']:.0f} bpm"),
                     ("Length", f"{mm}:{ss:02d}"), ("Voice", "sings lyrics" if st["vocal"] and any(ln for sec in r.sections for ln in sec.lines) else "instrumental")):
            facts.add_widget(lab(k, 16, font_size="11sp", color=(0.55, 0.57, 0.64, 1)))
            facts.add_widget(lab(v, 16, font_size="12sp"))
        card.add_widget(facts)
        kinds = []
        for sec in r.sections:
            if sec.kind not in kinds:
                kinds.append(sec.kind)
        chips = GridLayout(cols=3, size_hint_y=None, height=dp(44), spacing=dp(4))
        for k in kinds[:6]:
            chips.add_widget(Factory.Chip(text=f"{k} x{sum(1 for x in r.sections if x.kind == k)}"))
        card.add_widget(lab("RECIPE: " + str(len(r.sections)) + " sections", 16, font_size="10sp", color=(0.55, 0.57, 0.64, 1)))
        card.add_widget(chips)
        first = next((ln for sec in r.sections for ln in sec.lines if ln), "")
        card.add_widget(lab(f"\u201c{first}\u201d" if first else "no lyrics", 20, font_size="11sp", italic=True,
                            color=(0.7, 0.72, 0.8, 1), shorten=True))
        card.selected = c.id == self.sel_card
        card.bind(on_release=lambda *_a, i=c.id: self.select_card(i))
        return card

    def _track_job(self, job, msg, show=True):
        self.stop_audio()
        self.result_id = ""
        self.job = job
        self.busy, self.progress = True, 0
        self._say(msg)
        if show:
            self.show("create")

    def render_card(self, cid, play=False):
        """Build the card's song. With play=True it starts playing as soon as it is ready (and you stay where you are)."""
        try:
            job = self.engine.submit_card(cid)
            if play:
                self._autoplay = job.id
            self._track_job(job, "rendering the card...", show=not play)
        except Exception as e:
            self._say(str(e), True)

    def card_dialog(self, cid):
        c = self.engine.cards.get(cid)
        if not c:
            return self._say("That card is gone.", True)
        self.popup_text(c.name, f"{c.recipe.summary()}\n\nA card is the song's recipe (a few KB). It rebuilds the same song, "
                                "and can be remixed or extended into a new card.",
                        [("Play now", lambda: self.render_card(cid, play=True)), ("Render again", lambda: self.render_card(cid)), ("Remix...", lambda: self.card_remix_dialog(cid)),
                         ("Extend with a new tune...", lambda: self.card_extend_dialog(cid)),
                         ("Export card file", lambda: self.export_card(cid))])

    def card_remix_dialog(self, cid):
        def go(v):
            words = " ".join(v["words"].split())
            reseed = tuple(p for p in ("melody", "harmony", "drums") if p in v["reseed"].lower())
            vocal = {"yes": True, "no": False}.get(v["vocal"].strip().lower())
            bpm = float(v["bpm"]) if v["bpm"].strip() else None
            card = self.engine.card_remix(cid, words=words, key=v["key"], bpm=bpm, reseed=reseed, vocal=vocal)
            self.refresh_library()
            self._track_job(self.engine.submit_card(card.id), "remixing...")
        self.form_popup("Remix this card", [
            ("words", "New style words (e.g. jazz, synthwave, sad). Blank = keep", ""), ("key", "Key (e.g. D minor). Blank = keep", ""),
            ("bpm", "Tempo in BPM. Blank = keep", ""), ("reseed", "Make new: melody, harmony, drums (any). Blank = none", ""),
            ("vocal", "Voice: yes / no. Blank = keep", "")], go, "Remix + render")

    def card_extend_dialog(self, cid):
        def go(v):
            card = self.engine.card_extend(cid, float(v["seconds"] or 30), v["lyrics"])
            self.refresh_library()
            self._track_job(self.engine.submit_card(card.id), "extending with a new tune...")
        self.form_popup("Extend with another tune", [
            ("seconds", "Seconds to add", "30"), ("lyrics", "Lyrics for the new part (optional, use [verse]/[chorus])", "")],
            go, "Extend + render")

    def export_card(self, cid):
        try:
            c = self.engine.cards.get(cid)
            slug = re.sub(r"[^A-Za-z0-9._-]+", "-", c.name).strip("-") or "card"
            dest = self.export_dir() / f"{slug}.smmcard.json"
            self._say(f"Card saved to {self.engine.cards.export_to(cid, dest.resolve())}")
        except Exception as e:
            self._say(f"Export failed: {e}", True)

    def delete_card(self, cid):
        self.engine.cards.delete(cid)
        self.refresh_library()

    def pick_card_file(self):
        from kivy.factory import Factory
        from kivy.uix.filechooser import FileChooserListView
        from kivy.uix.popup import Popup
        box = BoxLayout(orientation="vertical", spacing=dp(6))
        chooser = FileChooserListView(path=str(Path.home()), filters=["*.json"])
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        ok, no = Factory.Primary(text="Import this card"), Factory.Btn(text="Cancel")
        row.add_widget(ok)
        row.add_widget(no)
        box.add_widget(chooser)
        box.add_widget(row)
        pop = Popup(title="Choose a card file (.smmcard.json)", content=box, size_hint=(0.95, 0.9))
        no.bind(on_release=pop.dismiss)

        def go(*_):
            if not chooser.selection:
                return
            pop.dismiss()
            try:
                c = self.engine.cards.import_file(Path(chooser.selection[0]))
                self._say(f"Imported card '{c.name}'.")
            except Exception as e:
                self._say(f"Not a usable card: {e}", True)
            self.refresh_library()
        ok.bind(on_release=go)
        pop.open()

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
        self.engine = Engine()
        from kivy.config import Config
        from kivy.metrics import Metrics
        self._base_density = Metrics.density
        sw, sh = screen_size() if platform in ("linux", "win", "macosx") else (0, 0)
        self._screen = (sw, sh)
        scale = self._effective_scale()
        if sw and sh:                                   # open at a comfortable size on this screen
            Config.set("graphics", "width", str(int(min(sw * 0.9, 1320 * scale))))
            Config.set("graphics", "height", str(int(min(sh * 0.9, 840 * scale))))
        from kivy.core.window import Window
        if sw and sh:
            Window.size = (int(min(sw * 0.9, 1320 * scale)), int(min(sh * 0.9, 840 * scale)))
        self._apply_scale(scale)
        Builder.load_string(KV)
        Window.bind(on_key_down=self._on_key)
        self.root_widget = Root(self.engine)
        return self.root_widget

    def _effective_scale(self) -> float:
        v = self.engine.store.value.ui_scale
        if v:
            return float(v)
        return auto_scale(self._screen[0]) if self._base_density <= 1.2 else 1.0

    def _apply_scale(self, scale: float):
        from kivy.core.window import Window
        from kivy.metrics import Metrics
        Metrics.density = self._base_density * scale
        if platform in ("linux", "win", "macosx"):      # the layout is built for a desktop window
            w, h = dp(900), dp(600)
            if self._screen[0]:
                w, h = min(w, int(self._screen[0] * 0.95)), min(h, int((self._screen[1] or 99999) * 0.9))
            Window.minimum_width, Window.minimum_height = w, h

    def rebuild(self):
        """Apply a new interface size right away: replace the window's content, keeping the same page."""
        from kivy.core.window import Window
        old = self.root_widget
        page = old.page
        old.dispose()
        Window.remove_widget(old)
        self._apply_scale(self._effective_scale())
        new = Root(self.engine)
        self.root_widget = self.root = new
        Window.add_widget(new)
        Clock.schedule_once(lambda dt: new.show(page), 0.1)

    def _on_key(self, window, key, scancode, codepoint, modifiers):
        if "ctrl" not in modifiers:
            return False
        step = 1 if (codepoint in ("+", "=") or key in (61, 43, 270)) else -1 if (codepoint == "-" or key in (45, 269)) else 0
        if not step:
            return False
        values = [v for _n, v in SCALES]
        cur = self._effective_scale()
        i = min(range(len(values)), key=lambda k: abs(values[k] - cur))
        j = max(0, min(len(values) - 1, i + step))
        if values[j] != self.engine.store.value.ui_scale:
            self.root_widget.set_ui_scale(values[j])
        return True

    def on_stop(self):
        self.root_widget.player.stop()
        self.engine.shutdown()


def run() -> None:
    runtime.activate()
    SudoMakeMusicApp().run()
