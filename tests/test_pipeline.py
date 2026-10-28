import json
import time
import urllib.request
import wave

import pytest

from sudo_make_music import memory
from sudo_make_music.audio import plan_segments
from sudo_make_music.engine import Engine
from sudo_make_music.hardware import HardwareInfo
from sudo_make_music.history import History
from sudo_make_music.settings import SettingsStore


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("SUDO_MAKE_MUSIC_HOME", str(tmp_path))
    e = Engine(SettingsStore(tmp_path / "s.json"), History(tmp_path / "h.db"))
    e.store.value.backend = "mock"
    yield e
    e.shutdown()


def wait(engine, job, timeout=30):
    t = time.time()
    while job.status in ("queued", "running") and time.time() - t < timeout:
        time.sleep(0.05)
    return job


def test_recommend_mode():
    assert memory.recommend_mode(HardwareInfo("RTX 2060", 6144, 16000)) == "safe"
    assert memory.recommend_mode(HardwareInfo(None, None, 16000)) == "safe"
    assert memory.recommend_mode(HardwareInfo("x", 10240, 0)) == "balanced"
    assert memory.recommend_mode(HardwareInfo("x", 24576, 0)) == "quality"


def test_overrides_and_batch():
    p = memory.resolve("safe", {"chunk_seconds": 30, "offload": False})
    assert p.chunk_seconds == 30 and p.offload is False and p.quantize is True and p.batch_size == 1


@pytest.mark.parametrize("total,chunk,ov", [(60, 60, 3), (200, 60, 3), (600, 60, 3), (61, 60, 3)])
def test_plan_covers_total(total, chunk, ov):
    plan = plan_segments(total, chunk, ov)
    assert all(d <= chunk + 1e-6 for d in plan)
    assert abs(sum(plan) - (len(plan) - 1) * ov - total) < 1e-6


def test_chunked_generation_length(engine):
    engine.store.value.overrides = {"chunk_seconds": 10, "overlap_seconds": 1.0}
    job = wait(engine, engine.submit("test", "", 35))
    assert job.status == "done", job.error
    assert job.segments >= 4
    with wave.open(str(engine.output_path(job.id, "wav")), "rb") as w:
        assert abs(w.getnframes() / w.getframerate() - 35) < 0.05
    assert engine.history.get(job.id)["status"] == "done"


def test_cancel(engine):
    engine.store.value.overrides = {"chunk_seconds": 10, "overlap_seconds": 1.0}
    job = engine.submit("test", "", 120)
    time.sleep(0.2)
    engine.cancel(job.id)
    wait(engine, job)
    assert job.status == "cancelled"
    assert engine.output_path(job.id, "wav") is None


def test_unload_when_idle(engine):
    engine.store.value.idle_unload_seconds = 1
    wait(engine, engine.submit("test", "", 10))
    assert engine._backends["mock"].loaded
    engine._last_used = time.time() - 10
    for _ in range(40):
        if not engine._backends["mock"].loaded:
            break
        time.sleep(0.25)
    assert not engine._backends["mock"].loaded


def test_unavailable_backend_rejected(engine):
    engine.store.value.backend = "acestep"
    try:
        import acestep  # noqa: F401
    except Exception:
        with pytest.raises(RuntimeError):
            engine.submit("x", "", 30)


def test_mp3_export(engine):
    engine.store.value.output_format = "mp3"
    job = wait(engine, engine.submit("test", "", 10))
    assert job.status == "done", job.error
    assert engine.output_path(job.id, "mp3").stat().st_size > 1000


def test_http_api(engine):
    from http.server import ThreadingHTTPServer
    import threading
    from sudo_make_music.server import make_handler

    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(engine))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    st = json.load(urllib.request.urlopen(base + "/api/status"))
    assert st["mode"] == "safe" and any(b["id"] == "mock" for b in st["backends"])
    assert b"sudo make music" in urllib.request.urlopen(base + "/").read()
    req = urllib.request.Request(base + "/api/generate", json.dumps({"prompt": "x", "duration": 10}).encode(),
                                 {"Content-Type": "application/json"})
    jid = json.load(urllib.request.urlopen(req))["id"]
    wait(engine, engine.jobs[jid])
    assert urllib.request.urlopen(f"{base}/audio/{jid}.wav").read()[:4] == b"RIFF"
    assert len(json.load(urllib.request.urlopen(base + "/api/history"))) == 1
    srv.shutdown()


def test_token_auth(engine):
    import urllib.error
    from http.server import ThreadingHTTPServer
    import threading
    from sudo_make_music.server import make_handler

    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(engine, token="s3cret"))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(base + "/api/status")
    assert e.value.code == 401
    r = urllib.request.urlopen(base + "/api/status?token=s3cret")
    assert "smm_token=s3cret" in r.headers["Set-Cookie"]
    req = urllib.request.Request(base + "/api/status", headers={"Cookie": "smm_token=s3cret"})
    assert urllib.request.urlopen(req).status == 200
    srv.shutdown()


def test_install_commands():
    from sudo_make_music import runtime
    cmds = runtime.install_commands("cpu")
    assert "--target" in cmds[0] and "whl/cpu" in " ".join(cmds[0])
    with pytest.raises(ValueError):
        runtime.install_commands("bogus")
