import time
import wave

import numpy as np
import pytest

from sudo_make_music import player as pl


def make_wav(path, seconds=1.0):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(8000)
        w.writeframes((np.zeros((int(8000 * seconds), 2), dtype="<i2")).tobytes())
    return path


def test_wav_seconds(tmp_path):
    assert abs(pl.wav_seconds(make_wav(tmp_path / "a.wav", 2)) - 2) < 0.01
    assert pl.wav_seconds(tmp_path / "missing.wav") == 0.0


def test_play_and_stop_uses_a_separate_process(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "_tools", lambda path: [["sleep", "30"]])
    monkeypatch.setattr(pl.sys, "platform", "linux")
    p = pl.AudioPlayer()
    p.play(make_wav(tmp_path / "a.wav", 2))
    assert p.playing and p.method == "sleep"
    p.stop()
    assert not p.playing


def test_end_of_song_is_noticed(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "_tools", lambda path: [["sleep", "1"]])
    monkeypatch.setattr(pl.sys, "platform", "linux")
    p = pl.AudioPlayer()
    p.play(make_wav(tmp_path / "a.wav", 1))
    time.sleep(1.4)
    assert not p.playing


def test_falls_back_to_the_next_player_when_one_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "_tools", lambda path: [["false"], ["sleep", "30"]])
    monkeypatch.setattr(pl.sys, "platform", "linux")
    p = pl.AudioPlayer()
    p.play(make_wav(tmp_path / "a.wav", 1))
    assert p.playing and p.method == "sleep"
    p.stop()


def test_clear_error_when_nothing_can_play(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "_tools", lambda path: [["false"]])
    monkeypatch.setattr(pl.sys, "platform", "linux")
    monkeypatch.setitem(__import__("sys").modules, "kivy.core.audio", None)      # kivy fallback unavailable too
    with pytest.raises(pl.PlayerError):
        pl.AudioPlayer().play(make_wav(tmp_path / "a.wav", 1))
    with pytest.raises(pl.PlayerError):
        pl.AudioPlayer().play(tmp_path / "missing.wav")
