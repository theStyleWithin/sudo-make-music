import time
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
    e.store.value.ask_on_fallback = False     # most tests want the automatic path
    yield e
    e.shutdown()


def wait(engine, job, timeout=30):
    t = time.time()
    while job.status in ("queued", "running", "needs_input") and time.time() - t < timeout:
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


def test_install_commands():
    from sudo_make_music import runtime
    cmds = runtime.install_commands("cpu")
    assert "--target" in cmds[0] and "whl/cpu" in " ".join(cmds[0])
    assert len(runtime.install_commands("cpu", speech=True)) == len(cmds) + 1
    assert "chatterbox-tts" in runtime.install_commands("cpu", speech=True)[-1]
    with pytest.raises(ValueError):
        runtime.install_commands("bogus")


def test_continuity_passes_context(engine):
    engine.store.value.update({"continuity": True})
    engine.store.value.overrides = {"chunk_seconds": 10, "overlap_seconds": 1.0}
    job = wait(engine, engine.submit("test", "", 25))
    assert job.status == "done", job.error
    req = engine._backends["mock"].last_request
    assert req.index > 0 and req.context_audio is not None and req.context_sr == 44100


def test_no_context_when_off(engine):
    engine.store.value.overrides = {"chunk_seconds": 10, "overlap_seconds": 1.0}
    wait(engine, engine.submit("test", "", 25))
    assert engine._backends["mock"].last_request.context_audio is None


def test_long_song_streams_to_disk(engine):
    engine.store.value.overrides = {"chunk_seconds": 60, "overlap_seconds": 3.0, "max_duration": 1800}
    job = wait(engine, engine.submit("test", "", 1500), timeout=120)   # 25 minutes
    assert job.status == "done", job.error
    with wave.open(str(engine.output_path(job.id, "wav")), "rb") as w:
        assert abs(w.getnframes() / w.getframerate() - 1500) < 0.1


def test_model_store_import_swap_delete(engine, tmp_path):
    src = tmp_path / "my-model"
    src.mkdir()
    (src / "weights.bin").write_bytes(b"x" * 10)
    info = engine.import_model(str(src), "acestep", "My Finetune")
    assert info.backend == "acestep" and engine.store.value.models["acestep"] == info.id
    src2 = tmp_path / "other"
    src2.mkdir()
    info2 = engine.import_model(str(src2), "acestep", "My Finetune")   # name clash -> unique id
    assert info2.id != info.id
    engine.select_model("acestep", info.id)
    assert engine.store.value.models["acestep"] == info.id
    from sudo_make_music.backends import registry
    assert str(engine.resolve_model(registry()["acestep"]())) == info.path
    engine.delete_model(info.id)
    assert engine.models.get(info.id) is None and info.id not in engine.store.value.models.values()


def test_offline_mode_requires_local_model(engine):
    engine.store.value.backend = "acestep"
    engine.store.value.update({"offline_mode": True})
    from sudo_make_music.backends import registry
    with pytest.raises(RuntimeError, match="offline"):
        engine.resolve_model(registry()["acestep"]())
    import os
    engine._apply_offline(True)
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    engine._apply_offline(False)
    assert "HF_HUB_OFFLINE" not in os.environ


def test_no_gpu_resolves_to_cpu():
    p = memory.resolve("quality", None, vram_mb=None)
    assert p.device == "cpu" and p.chunk_seconds <= 30 and p.offload is False and p.quantize is True
    assert memory.resolve("safe", None, vram_mb=6144).device == "cuda"
    assert memory.resolve("safe", None, vram_mb=1024).device == "cpu"          # too little VRAM
    assert memory.resolve("safe", {"device": "cpu"}, vram_mb=6144).device == "cpu"
    assert memory.resolve("safe", {"device": "cuda"}, vram_mb=None).device == "cuda"


def test_oom_steps_down_gpu_then_cpu(engine):
    from dataclasses import replace
    engine.hw = HardwareInfo("RTX 2060", 6144, 16000)
    engine.store.value.overrides = {"chunk_seconds": 10, "overlap_seconds": 1.0, "offload": False, "quantize": False}
    be = engine._backend("mock")
    be.oom_unless = lambda p: p.device == "cpu"          # only CPU works
    job = wait(engine, engine.submit("test", "", 25))
    assert job.status == "done", job.error
    devs = [(p.device, p.offload, p.quantize) for p in be.seen_params]
    assert devs[0] == ("cuda", False, False)
    assert ("cuda", True, True) in devs and devs[-1][0] == "cpu"
    assert job.params.device == "cpu"


def test_oom_recovers_with_offload_only(engine):
    engine.hw = HardwareInfo("RTX 2060", 6144, 16000)
    engine.store.value.overrides = {"chunk_seconds": 10, "overlap_seconds": 1.0, "offload": False, "quantize": False}
    engine._backend("mock").oom_unless = lambda p: p.offload and p.quantize
    job = wait(engine, engine.submit("test", "", 15))
    assert job.status == "done" and job.params.device == "cuda" and job.params.offload


def test_oom_gives_clear_error_when_cpu_switch_impossible(engine):
    engine.hw = HardwareInfo("RTX 2060", 6144, 16000)
    engine.store.value.overrides = {"chunk_seconds": 10, "offload": True, "quantize": True}
    be = engine._backend("mock")
    be.oom_unless = lambda p: False
    be.can_switch_device_live = False
    engine._cuda_initialised = lambda: True
    job = wait(engine, engine.submit("test", "", 15))
    assert job.status == "error" and "Compute device" in job.error


def wait_status(job, status, timeout=10):
    t = time.time()
    while job.status != status and time.time() - t < timeout:
        time.sleep(0.05)
    return job.status == status


def _gpu_engine(engine, **ov):
    engine.hw = HardwareInfo("RTX 2060", 6144, 16000)
    engine.store.value.ask_on_fallback = True
    engine.store.value.overrides = {"chunk_seconds": 10, "overlap_seconds": 1.0, "offload": False,
                                    "quantize": False, **ov}


def test_oom_asks_user_and_applies_choice(engine):
    _gpu_engine(engine)
    be = engine._backend("mock")
    be.oom_unless = lambda p: p.device == "cpu"
    job = engine.submit("test", "", 15)
    assert wait_status(job, "needs_input")
    ids = [o["id"] for o in job.to_dict()["decision"]["options"]]
    assert ids == ["offload", "cpu", "cancel"]
    engine.resolve_decision(job.id, "offload")              # still OOMs on the GPU -> asks again
    t = time.time()
    while time.time() - t < 10 and not (job.decision and "offload" not in [o["id"] for o in job.decision["options"]]):
        time.sleep(0.05)
    ids = [o["id"] for o in job.decision["options"]]
    assert "offload" not in ids and "cpu" in ids
    engine.resolve_decision(job.id, "cpu")
    wait(engine, job)
    assert job.status == "done" and job.params.device == "cpu"


def test_oom_user_can_cancel(engine):
    _gpu_engine(engine)
    engine._backend("mock").oom_unless = lambda p: False
    job = engine.submit("test", "", 15)
    assert wait_status(job, "needs_input")
    engine.resolve_decision(job.id, "cancel")
    wait(engine, job)
    assert job.status == "cancelled"


def test_oom_cpu_restart_choice_persists_setting(engine):
    _gpu_engine(engine, offload=True, quantize=True)
    be = engine._backend("mock")
    be.oom_unless = lambda p: False
    be.can_switch_device_live = False
    engine._cuda_initialised = lambda: True
    job = engine.submit("test", "", 15)
    assert wait_status(job, "needs_input")
    assert [o["id"] for o in job.decision["options"]] == ["cpu_restart", "cancel"]
    engine.resolve_decision(job.id, "cpu_restart")
    wait(engine, job)
    assert job.status == "error" and "Restart" in job.error
    assert engine.store.value.overrides["device"] == "cpu"


def test_no_gpu_warns_before_starting(engine):
    engine.hw = HardwareInfo(None, None, 16000)
    engine.store.value.ask_on_fallback = True
    engine.store.value.overrides = {"chunk_seconds": 10, "overlap_seconds": 1.0}
    be = engine._backend("mock")
    be.uses_gpu = True
    job = engine.submit("test", "", 15)
    assert wait_status(job, "needs_input")
    assert "No GPU" in job.decision["reason"]
    engine.resolve_decision(job.id, "cpu")
    wait(engine, job)
    assert job.status == "done" and job.params.device == "cpu"


def test_no_warning_when_user_chose_cpu(engine):
    engine.hw = HardwareInfo(None, None, 16000)
    engine.store.value.ask_on_fallback = True
    engine.store.value.overrides = {"chunk_seconds": 10, "device": "cpu"}
    engine._backend("mock").uses_gpu = True
    job = wait(engine, engine.submit("test", "", 15))
    assert job.status == "done"          # manual choice: no popup
