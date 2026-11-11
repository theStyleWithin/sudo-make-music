import time

import numpy as np
import pytest

from sudo_make_music.backends.base import Cancelled, SegmentRequest
from sudo_make_music.backends.procedural import (MINORISH, SCALES, SR, ProceduralBackend, parse_lyrics, plan_song, syllables)
from sudo_make_music.engine import Engine
from sudo_make_music.history import History
from sudo_make_music.settings import SettingsStore

LYRICS = "[verse]\nNeon rivers in the dark\nI keep your name inside my heart\n[chorus]\nHold on, hold on\nWe will find the light\n[bridge]\nRemember me"


def render(prompt="lo-fi chill", lyrics="", dur=30.0, seed=1):
    b = ProceduralBackend()
    req = SegmentRequest(prompt, lyrics, dur, seed)
    return np.concatenate([x.audio for x in b.stream_song(req, None, lambda f: None, lambda: False)])


def test_same_input_same_song_different_seed_different_song():
    a, b, c = render(seed=5), render(seed=5), render(seed=6)
    assert np.array_equal(a, b) and not np.allclose(a[:SR * 5], c[:SR * 5])


def test_exact_length_and_sane_levels_for_many_durations():
    for dur in (5, 17, 33.5, 90):
        a = render(dur=dur, lyrics=LYRICS)
        assert len(a) == round(dur * SR), dur
        peak, rms = float(np.abs(a).max()), float(np.sqrt((a ** 2).mean()))
        assert 0.1 < peak <= 1.0 and rms > 0.01 and np.isfinite(a).all(), (dur, peak, rms)


def test_style_words_pick_tempo_mode_and_instruments():
    assert 120 <= plan_song("house dance", "", 60, 1).style.bpm <= 131
    assert 56 <= plan_song("ambient cinematic", "", 60, 1).style.bpm <= 81 and plan_song("ambient", "", 60, 1).style.drums == "none"
    assert plan_song("rock", "", 60, 1).style.drums == "rock" and plan_song("chiptune", "", 60, 1).style.lead == "square"
    assert plan_song("techno 140 bpm", "", 60, 1).style.bpm == 140
    assert plan_song("sad dark chill", "", 60, 1).style.mode in MINORISH
    assert plan_song("happy bright dance", "", 60, 2).style.mode in ("major", "lydian", "pentatonic_major")
    p = plan_song("song in D minor", "", 60, 3)
    assert p.style.root_pc == 2 and p.style.mode == "minor"
    assert plan_song("ambient instrumental", "[verse]\nhello", 60, 1).style.vocal is False


def test_every_note_and_chord_stays_in_the_key():
    for prompt in ("lo-fi sad", "happy house", "ambient dreamy", "chiptune", "jazz"):
        p = plan_song(prompt, LYRICS, 120, 9)
        pcs = {(p.style.root_pc + s) % 12 for s in SCALES[p.style.mode]}
        for sec in p.sections:
            for n in sec.notes:
                assert n.midi % 12 in pcs, (prompt, sec.kind, n)
                assert 0 <= n.step < 16 and 0 <= n.bar < sec.bars and n.length >= 1


def test_song_fills_the_duration_exactly_with_bars():
    p = plan_song("pop", "", 100, 4)
    assert sum(s.bars for s in p.sections) == p.total_bars
    assert abs(p.total_bars * p.spb - 100) < 1e-6


def test_lyric_tags_become_the_structure_and_lines_become_melody():
    p = plan_song("pop", LYRICS, 120, 4)
    kinds = [s.kind for s in p.sections]
    assert kinds[-3:] == ["verse", "chorus", "bridge"] or kinds[:3] == ["verse", "chorus", "bridge"] or "bridge" in kinds
    assert "verse" in kinds and "chorus" in kinds
    verse = next(s for s in p.sections if s.kind == "verse")
    voiced = [n for n in verse.notes if n.vowel]
    want = len(syllables("Neon rivers in the dark")) + len(syllables("I keep your name inside my heart"))
    assert len(voiced) == want and all(n.vowel in "aeiou" for n in voiced)
    inst = plan_song("pop", LYRICS + "\n", 120, 4)
    assert [s.kind for s in inst.sections] == kinds


def test_short_songs_drop_sections_but_still_work():
    p = plan_song("pop", LYRICS, 8, 4)
    assert 1 <= len(p.sections) <= 3 and sum(s.bars for s in p.sections) == p.total_bars
    assert len(render(lyrics=LYRICS, dur=8)) == 8 * SR


def test_untagged_lyrics_alternate_verse_and_chorus():
    assert [k for k, _ in parse_lyrics("a b c\nd e f\n\ng h i\n\nj k l")] == ["verse", "chorus", "verse"]
    assert [k for k, _ in parse_lyrics("[Verse 1]\nhi\n[Pre-Chorus]\nyo\n[Hook]\nla")] == ["verse", "pre", "chorus"]


def test_syllable_counter():
    assert len(syllables("hello world")) == 3 and len(syllables("the cake")) == 2
    assert syllables("sky") == ["i"] and syllables("!!!") == ["a"]


def test_instrumental_flag_removes_the_voice_notes():
    p = plan_song("lo-fi instrumental", LYRICS, 60, 1)
    assert not any(n.vowel for s in p.sections for n in s.notes)


def test_styles_sound_different():
    def centroid(a):
        m = np.abs(np.fft.rfft(a[: SR * 20, 0]))
        f = np.fft.rfftfreq(SR * 20, 1 / SR)
        return float((m * f).sum() / m.sum())
    assert centroid(render("chiptune retro game", dur=30)) > centroid(render("ambient cinematic", dur=30))


def test_streaming_blocks_and_cancel():
    b = ProceduralBackend()
    req = SegmentRequest("lo-fi", LYRICS, 90, 2)
    blocks = list(b.stream_song(req, None, lambda f: None, lambda: False))
    assert len(blocks) >= 3 and max(len(x.audio) for x in blocks) < 60 * SR      # never one giant array
    calls = []
    with pytest.raises(Cancelled):
        for _ in b.stream_song(req, None, lambda f: None, lambda: (calls.append(1), len(calls) > 1)[1]):
            pass


def test_a_three_minute_song_renders_quickly():
    t = time.time()
    a = render("synthwave", LYRICS, 180, 3)
    assert len(a) == 180 * SR and time.time() - t < 60


def test_through_the_engine_no_gpu_no_model_no_prompts(tmp_path, monkeypatch):
    monkeypatch.setenv("SUDO_MAKE_MUSIC_HOME", str(tmp_path))
    e = Engine(SettingsStore(tmp_path / "s.json"), History(tmp_path / "h.db"))
    try:
        e.store.value.update({"backend": "procedural", "ask_on_fallback": True})     # popup would block: it must not appear
        job = e.submit("lo-fi chill rainy night", LYRICS, 45)
        t = time.time()
        while job.status in ("queued", "running", "needs_input") and time.time() - t < 60:
            time.sleep(0.05)
        assert job.status == "done", job.error
        import wave
        with wave.open(str(e.output_path(job.id, "wav")), "rb") as w:
            assert abs(w.getnframes() / w.getframerate() - 45) < 0.05 and w.getnchannels() == 2
        assert job.segments == 1 and e.history.get(job.id)["status"] == "done"
        info = {b["id"]: b for b in e.backend_infos()}["procedural"]
        assert info["beta"] and info["available"] and "BETA" in info["name"]
    finally:
        e.shutdown()
