import json
import time
import wave

import numpy as np
import pytest

from sudo_make_music.backends import Cancelled, SegmentRequest, registry
from sudo_make_music.backends.stableaudio import (StableAudioLiteRTBackend, LiteRTRunner, _match, pingpong_sample)
from sudo_make_music.engine import Engine
from sudo_make_music.history import History
from sudo_make_music.memory import resolve
from sudo_make_music.settings import SettingsStore

SIZE, DOWN, C = 524288, 2048, 64
L = SIZE // DOWN


class FakeRunner(LiteRTRunner):
    calls: list = []

    def run(self, inputs):
        name = self.path.name
        FakeRunner.calls.append((name, {k: np.array(v) for k, v in inputs.items()}))
        if name == "cond.tflite":
            return {"serving_default_out_cross:0": np.zeros((1, 64, 768), np.float32),
                    "out_mask:0": np.ones((1, 64), np.float32), "out_global:0": np.zeros((1, 768), np.float32)}
        if name == "dit.tflite":
            return {"Identity:0": 0.5 * inputs["x"]}
        if name == "ae.tflite":
            z = inputs["latent"]
            a = np.repeat(z.mean(axis=1), DOWN, axis=-1)           # (1, samples)
            return {"audio": np.stack([a, a * 0.5], axis=1)}       # (1, 2, samples)
        raise AssertionError(name)


DESCRIPTOR = {
    "sample_rate": 44100, "sample_size": SIZE, "latent_channels": C, "downsample": DOWN, "steps": 8, "max_tokens": 64,
    "conditioner": {"file": "cond.tflite", "inputs": {"ids": "input_ids", "mask": "attention_mask", "seconds": "seconds_total"},
                    "outputs": {"cross": "out_cross", "cross_mask": "out_mask", "global": "out_global"}},
    "dit": {"file": "dit.tflite", "inputs": {"x": "x", "t": "t", "cross": "cross", "cross_mask": "cross_mask", "global": "global"},
            "outputs": {"v": "Identity"}},
    "autoencoder": {"file": "ae.tflite", "inputs": {"latent": "latent"}, "outputs": {"audio": "audio"}},
}


@pytest.fixture
def folder(tmp_path):
    f = tmp_path / "sao"
    f.mkdir()
    for n in ("cond.tflite", "dit.tflite", "ae.tflite"):
        (f / n).write_bytes(b"x")
    (f / "smm-litert.json").write_text(json.dumps(DESCRIPTOR))
    return f


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    FakeRunner.calls = []
    monkeypatch.setattr(StableAudioLiteRTBackend, "runner_factory", staticmethod(lambda p, threads=4: FakeRunner(p)))
    monkeypatch.setattr(StableAudioLiteRTBackend, "tokenizer_factory",
                        staticmethod(lambda mp, d: (lambda text: [5, 6, 7, 1] + [0] * 60)))


def gen(folder, seed=1, duration=8.0, cancelled=lambda: False, progress=lambda f: None):
    b = StableAudioLiteRTBackend()
    b.load(resolve("safe"), folder)
    return b.generate_segment(SegmentRequest("lofi", "", duration, seed), resolve("safe"), progress, cancelled)


def test_registry_has_both_stable_audio_backends():
    r = registry()
    assert r["stableaudio"].max_segment_seconds == 11 and r["stableaudio_litert"].max_segment_seconds == 11
    assert not r["stableaudio"].supports_context


def test_pingpong_matches_reference_formula():
    rng_a, rng_b = np.random.default_rng(3), np.random.default_rng(3)
    x0 = rng_a.standard_normal((1, 4, 8)).astype(np.float32)
    rng_b.standard_normal((1, 4, 8))                              # same stream position
    t = np.linspace(1, 0, 5, dtype=np.float32)
    dit = lambda x, ti: 0.3 * x + ti
    got = pingpong_sample(dit, x0.copy(), t, rng_a)
    x = x0.copy()
    for i in range(4):                                            # stable-audio-tools sample_flow_pingpong
        den = x - t[i] * dit(x, t[i])
        x = (1 - t[i + 1]) * den + t[i + 1] * rng_b.standard_normal(x.shape).astype(np.float32)
    assert np.allclose(got, x, atol=1e-5)


def test_litert_pipeline_shapes_steps_and_conditioning(folder):
    res = gen(folder, duration=8.0)
    assert res.sample_rate == 44100 and res.audio.shape == (8 * 44100, 2)
    assert abs(float(np.max(np.abs(res.audio))) - 1.0) < 1e-6          # peak-normalised
    dit_calls = [c for c in FakeRunner.calls if c[0] == "dit.tflite"]
    assert len(dit_calls) == 8
    ts = [float(c[1]["t"][0]) for c in dit_calls]
    assert ts[0] == 1.0 and ts == sorted(ts, reverse=True) and abs(ts[-1] - 0.125) < 1e-6
    cond = next(c for c in FakeRunner.calls if c[0] == "cond.tflite")[1]
    assert float(cond["seconds_total"][0, 0]) == 8.0 and cond["input_ids"].shape == (1, 64)
    assert dit_calls[0][1]["x"].shape == (1, C, L) and "cross_mask" in dit_calls[0][1]


def test_litert_seed_determinism(folder):
    a, b, c = gen(folder, seed=5), gen(folder, seed=5), gen(folder, seed=6)
    assert np.allclose(a.audio, b.audio) and not np.allclose(a.audio, c.audio)


def test_litert_cancel_mid_sampling(folder):
    n = []

    def cancelled():
        n.append(1)
        return len(n) > 4
    with pytest.raises(Cancelled):
        gen(folder, cancelled=cancelled)


def test_litert_errors_are_actionable(folder, tmp_path):
    b = StableAudioLiteRTBackend()
    with pytest.raises(RuntimeError, match="smm-litert.json"):
        b.load(resolve("safe"), tmp_path)
    d = json.loads((folder / "smm-litert.json").read_text())
    d["dit"]["inputs"]["x"] = "no_such_tensor"
    (folder / "smm-litert.json").write_text(json.dumps(d))
    class Strict(FakeRunner):
        def run(self, inputs):
            _match(["x", "t"], list(inputs)[0]) if self.path.name == "dit.tflite" else None
            return super().run(inputs)
    StableAudioLiteRTBackend.runner_factory = staticmethod(lambda p, threads=4: Strict(p))
    with pytest.raises(KeyError, match="smm-litert.json"):
        gen(folder)


def test_match_handles_tflite_name_decoration():
    names = ["serving_default_input_ids:0", "serving_default_attention_mask:0", "StatefulPartitionedCall:0"]
    assert _match(names, "input_ids") == 0 and _match(names, "attention_mask") == 1
    assert _match(names, "StatefulPartitionedCall") == 2
    with pytest.raises(KeyError):
        _match(names, "nope")


def test_engine_builds_long_song_from_11s_clips(folder, tmp_path, monkeypatch):
    monkeypatch.setenv("SUDO_MAKE_MUSIC_HOME", str(tmp_path / "home"))
    e = Engine(SettingsStore(tmp_path / "s.json"), History(tmp_path / "h.db"))
    try:
        e.store.value.update({"backend": "stableaudio_litert", "ask_on_fallback": False})
        e.import_model(str(folder), "stableaudio_litert", "SAO Small LiteRT")
        e.store.value.overrides = {"overlap_seconds": 1.0}
        job = e.submit("lofi beat", "ignored lyrics", 40)
        t = time.time()
        while job.status in ("queued", "running") and time.time() - t < 60:
            time.sleep(0.05)
        assert job.status == "done", job.error
        assert job.segments >= 4                                   # 40s from <=11s clips
        with wave.open(str(e.output_path(job.id, "wav")), "rb") as w:
            assert abs(w.getnframes() / w.getframerate() - 40) < 0.1
    finally:
        e.shutdown()


def test_local_t5_path_is_injected_into_config():
    from sudo_make_music.backends.stableaudio import _set_key
    cfg = {"model": {"conditioning": {"configs": [{"id": "prompt", "config": {"t5_model_name": "t5-base"}},
                                                  {"id": "seconds_total", "config": {"min_val": 0}}]}}}
    _set_key(cfg, "t5_model_name", "/models/sao/t5-base")
    assert cfg["model"]["conditioning"]["configs"][0]["config"]["t5_model_name"] == "/models/sao/t5-base"
