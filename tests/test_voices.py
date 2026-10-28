import sqlite3
import time
import wave

import numpy as np
import pytest

from sudo_make_music.audio import read_wav, write_wav
from sudo_make_music.engine import Engine
from sudo_make_music.history import History
from sudo_make_music.settings import SettingsStore
from sudo_make_music.textsplit import split_text
from sudo_make_music.voices import VoiceStore


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("SUDO_MAKE_MUSIC_HOME", str(tmp_path))
    e = Engine(SettingsStore(tmp_path / "s.json"), History(tmp_path / "h.db"))
    e.store.value.backend = "mock"
    e.store.value.speech_backend = "mock_speech"
    e.store.value.ask_on_fallback = False
    e.store.value.overrides = {"chunk_seconds": 10, "overlap_seconds": 1.0}
    yield e
    e.shutdown()


def wait(job, timeout=30):
    t = time.time()
    while job.status in ("queued", "running", "needs_input") and time.time() - t < timeout:
        time.sleep(0.05)
    return job


def tone(path, hz, secs=3.0, sr=24000):
    t = np.arange(int(secs * sr)) / sr
    write_wav(path, (0.3 * np.sin(2 * np.pi * hz * t))[:, None].astype(np.float32), sr)
    return path


def test_split_text():
    assert split_text("Hello there. How are you? Fine!") == ["Hello there. How are you? Fine!"]
    long = "word " * 200
    parts = split_text(long, max_chars=100)
    assert len(parts) > 5 and all(len(p) <= 100 for p in parts)
    assert split_text("   ") == []
    assert len(split_text("First sentence is reasonably long and fills space. " * 8, max_chars=120)) >= 4


def test_voice_store_roundtrip(tmp_path):
    vs = VoiceStore(tmp_path / "v")
    src = tone(tmp_path / "ref.wav", 200, 4)
    v = vs.create_from_file(src, "Alice", tags="female vocal")
    assert v.has_ref and abs(v.ref_seconds - 4) < 0.1 and vs.ref_path(v.id).is_file()
    assert [x.id for x in vs.list()] == [v.id]
    p = vs.create_preset("Narrator", "af_heart")
    assert p.preset == "af_heart" and not p.has_ref and vs.ref_path(p.id) is None
    vs.update(v.id, name="Alice 2", tags="alto")
    assert vs.get(v.id).name == "Alice 2" and vs.get(v.id).tags == "alto"
    vs.delete(v.id)
    assert vs.get(v.id) is None and len(vs.list()) == 1
    with pytest.raises(ValueError):
        vs.create_from_file(tone(tmp_path / "short.wav", 200, 0.4), "x")
    assert not any((tmp_path / "v").glob("*/ref.wav")) or len(vs.list()) == 1
    with pytest.raises(ValueError):
        vs.create_preset("  ", "x")


def test_reference_is_trimmed_to_30s(tmp_path):
    vs = VoiceStore(tmp_path / "v")
    v = vs.create_from_file(tone(tmp_path / "long.wav", 150, 45), "Long")
    assert v.ref_seconds <= 30.5


def test_save_voice_from_song_is_separate_from_songs(engine):
    job = wait(engine.submit("lofi", "", 20))
    assert job.status == "done"
    v = engine.save_voice_from_job(job.id, "Singer A", start=2, length=8, tags="warm alto")
    assert v.source == "song" and v.seed == job.seed and v.origin_prompt == "lofi" and abs(v.ref_seconds - 8) < 0.1
    assert len(engine.history.list()) == 1          # the song library is untouched
    assert [x.id for x in engine.voices.list()] == [v.id]
    engine.delete(job.id)                            # deleting the song keeps the saved voice
    assert engine.voices.get(v.id) is not None and engine.voices.ref_path(v.id).is_file()


def test_song_with_saved_voice_reuses_seed_tags_and_reference(engine):
    first = wait(engine.submit("lofi", "", 20))
    v = engine.save_voice_from_job(first.id, "Singer A", tags="warm alto vocal")
    job = wait(engine.submit("pop song", "", 25, voice_id=v.id))
    assert job.status == "done" and job.seed == v.seed          # not random
    req = engine._backends["mock"].last_request
    assert req.prompt.startswith("warm alto vocal") and "pop song" in req.prompt
    assert req.context_audio is not None and req.context_audio.shape[1] == 2   # voice reference reaches the model
    again = wait(engine.submit("pop song", "", 25, voice_id=v.id))
    assert again.seed == job.seed
    other = wait(engine.submit("pop song", "", 25))             # no voice -> random seed again
    assert other.seed != v.seed


def test_pinned_seed_wins_over_voice_seed(engine):
    first = wait(engine.submit("lofi", "", 10))
    v = engine.save_voice_from_job(first.id, "A")
    engine.store.value.update({"seed": 7})
    assert wait(engine.submit("x", "", 10, voice_id=v.id)).seed == 7


def test_talk_with_cloned_voice_differs_per_voice(engine, tmp_path):
    a = engine.voices.create_from_file(tone(tmp_path / "a.wav", 180), "A")
    b = engine.voices.create_from_file(tone(tmp_path / "b.wav", 400), "B")
    ja = wait(engine.submit_talk("Hello world. This is a test.", a.id))
    jb = wait(engine.submit_talk("Hello world. This is a test.", b.id))
    assert ja.status == jb.status == "done", (ja.error, jb.error)
    xa, _ = read_wav(engine.output_path(ja.id, "wav"))
    xb, _ = read_wav(engine.output_path(jb.id, "wav"))
    assert len(xa) > 24000 and not np.allclose(xa[:20000], xb[:20000])
    assert engine.history.get(ja.id)["kind"] == "talk" and engine.history.get(ja.id)["voice_id"] == a.id


def test_talk_with_same_voice_is_repeatable(engine, tmp_path):
    a = engine.voices.create_from_file(tone(tmp_path / "a.wav", 180), "A")
    x = [read_wav(engine.output_path(wait(engine.submit_talk("Same words here.", a.id)).id, "wav"))[0] for _ in range(2)]
    assert np.allclose(x[0], x[1])


def test_talk_preset_and_speed(engine):
    p = engine.voices.create_preset("High", "high")
    fast = wait(engine.submit_talk("one two three four five six", p.id, speed=2.0))
    slow = wait(engine.submit_talk("one two three four five six", p.id, speed=0.5))
    n = lambda j: read_wav(engine.output_path(j.id, "wav"))[0].shape[0]
    assert n(slow) > n(fast) * 2


def test_talk_long_text_is_chunked(engine):
    text = " ".join(f"This is sentence number {i} of a long passage." for i in range(12))
    job = wait(engine.submit_talk(text))
    assert job.status == "done" and job.segments > 1


def test_talk_rejects_cloning_on_preset_only_backend(engine, tmp_path):
    v = engine.voices.create_from_file(tone(tmp_path / "a.wav", 180), "A")
    engine._backend("mock_speech").supports_cloning = False
    with pytest.raises(ValueError, match="cannot clone"):
        engine.submit_talk("hi", v.id)
    with pytest.raises(ValueError):
        engine.submit_talk("   ")


def test_one_model_in_memory_at_a_time(engine):
    wait(engine.submit("lofi", "", 10))
    assert engine._backends["mock"].loaded
    wait(engine.submit_talk("hello there"))
    assert engine._backends["mock_speech"].loaded and not engine._backends["mock"].loaded


def test_cancel_talk_removes_partial(engine):
    job = engine.submit_talk(" ".join("Sentence number %d is here." % i for i in range(60)))
    time.sleep(0.15)
    engine.cancel(job.id)
    wait(job)
    assert job.status == "cancelled" and engine.output_path(job.id, "wav") is None


def test_history_upgrade_adds_columns(tmp_path):
    db = tmp_path / "old.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE history (id TEXT PRIMARY KEY, created REAL, backend TEXT, prompt TEXT, lyrics TEXT, "
              "duration REAL, seed INTEGER, mode TEXT, status TEXT, error TEXT, elapsed REAL, params TEXT)")
    c.execute("INSERT INTO history VALUES ('a',1,'m','p','',1,1,'safe','done','',1,'{}')")
    c.commit()
    c.close()
    h = History(db)
    assert h.list()[0]["id"] == "a"
    h.add(id="b", kind="talk", voice_id="v", backend="m", prompt="x", status="done")
    assert h.get("b")["kind"] == "talk"
