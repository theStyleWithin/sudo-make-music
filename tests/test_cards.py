import copy
import json

import numpy as np
import pytest

from sudo_make_music.backends.base import SegmentRequest
from sudo_make_music.backends.procedural import (ENGINE_VERSION, SR, ProceduralBackend, Recipe, extend, make_recipe,
                                                 plan_from_recipe, remix)
from sudo_make_music.cards import CardStore, validate_recipe

LYRICS = "[verse]\nNeon rivers in the dark\nI keep your name inside my heart\n[chorus]\nHold on, hold on\nWe will find the light"


def audio(recipe, limit=None):
    b = ProceduralBackend()
    a = np.concatenate([x.audio for x in b.stream_recipe(recipe, None, lambda f: None, lambda: False)])
    return a


def notes(recipe):
    return [(i, n.bar, n.step, n.length, n.midi, n.vowel) for i, s in enumerate(plan_from_recipe(recipe).sections) for n in s.notes]


def base_recipe(prompt="lo-fi chill sad", lyrics=LYRICS, dur=60, seed=11):
    return make_recipe(prompt, lyrics, dur, seed)


def test_recipe_is_small_plain_data_and_rebuilds_the_exact_same_song():
    r = base_recipe()
    blob = json.dumps(r.to_dict())
    assert len(blob) < 5000
    back = validate_recipe(json.loads(blob))
    assert back == r and np.array_equal(audio(r), audio(back))
    req = SegmentRequest("lo-fi chill sad", LYRICS, 60.0, 11)         # the old "prompt in, song out" path is unchanged
    direct = np.concatenate([x.audio for x in ProceduralBackend().stream_song(req, None, lambda f: None, lambda: False)])
    assert np.array_equal(direct, audio(r)) and len(direct) == 60 * SR


def test_card_store_roundtrip_rename_delete_export_import(tmp_path):
    s = CardStore(tmp_path / "cards")
    c = s.create("Rainy night", base_recipe())
    assert s.get(c.id).recipe == c.recipe and [x.id for x in s.list()] == [c.id]
    assert s.rename(c.id, "  Renamed\x00card ").name == "Renamed card"
    out = s.export_to(c.id, tmp_path / "out" / "rainy.smmcard.json")
    imp = s.import_file(out)
    assert imp.id != c.id and imp.parent is None and imp.recipe == c.recipe and len(s.list()) == 2
    s.delete(c.id)
    assert s.get(c.id) is None and len(s.list()) == 1
    with pytest.raises(ValueError):
        s.get("../etc/passwd") or s._path("../x")


def test_old_engine_version_is_flagged(tmp_path):
    s = CardStore(tmp_path)
    r = base_recipe()
    r.engine = ENGINE_VERSION + 1
    assert s.create("future", r).stale and not s.create("now", base_recipe()).stale


def test_imports_are_validated_strictly(tmp_path):
    s = CardStore(tmp_path / "cards")
    good = {"format": "smm-card", "version": 1, "name": "x", "recipe": base_recipe().to_dict()}

    def put(doc, name="c.json", raw=None):
        p = tmp_path / name
        p.write_text(raw if raw is not None else json.dumps(doc))
        return p

    assert s.import_file(put(good)).name == "x"
    bad = []
    r = lambda: copy.deepcopy(good)
    d = r(); d["recipe"]["style"]["mode"] = "__import__('os')"; bad.append(d)
    d = r(); d["recipe"]["style"]["drums"] = "evil"; bad.append(d)
    d = r(); d["recipe"]["style"]["lead"] = "sample.wav"; bad.append(d)
    d = r(); d["recipe"]["style"]["bpm"] = 99999; bad.append(d)
    d = r(); d["recipe"]["style"]["bpm"] = "fast"; bad.append(d)
    d = r(); d["recipe"]["sections"][0]["bars"] = 10 ** 9; bad.append(d)
    d = r(); d["recipe"]["sections"][0]["kind"] = "../../x"; bad.append(d)
    d = r(); d["recipe"]["sections"][0]["prog"] = [99]; bad.append(d)
    d = r(); d["recipe"]["sections"][0]["motif"] = "a b/../c"; bad.append(d)
    d = r(); d["recipe"]["sections"] = []; bad.append(d)
    d = r(); d["recipe"]["seeds"] = {"drums": -1, "melody": 1, "harmony": 1}; bad.append(d)
    d = r(); d["recipe"]["lyrics"] = "x" * 30000; bad.append(d)
    d = r(); d["format"] = "something-else"; bad.append(d)
    d = r(); d["recipe"]["sections"][0]["bars"] = 500; d["recipe"]["sections"] *= 40; d["recipe"]["style"]["bpm"] = 40; bad.append(d)  # too long
    for i, doc in enumerate(bad):
        with pytest.raises(ValueError):
            s.import_file(put(doc, f"bad{i}.json"))
    for raw in ("not json", "[1, 2, 3]", "null", "{}"):
        with pytest.raises(ValueError):
            s.import_file(put(None, "junk.json", raw))
    with pytest.raises(ValueError):
        s.import_file(put(None, "huge.json", " " * 400_000))
    with pytest.raises(ValueError):
        s.import_file(tmp_path / "missing.json")
    d = r(); d["recipe"]["evil"] = "payload"; d["recipe"]["style"]["extra"] = 1
    c = s.import_file(put(d, "extra.json"))
    assert "evil" not in json.dumps(c.recipe.to_dict()) and "extra" not in c.recipe.style    # unknown keys are dropped


def test_remix_changes_only_what_was_asked():
    r = base_recipe()
    drums = remix(r, reseed=("drums",), new_seed=1)
    assert notes(drums) == notes(r) and drums.seeds["drums"] != r.seeds["drums"] and not np.array_equal(audio(drums), audio(r))
    mel = remix(r, reseed=("melody",), new_seed=1)
    assert notes(mel) != notes(r) and mel.seeds["drums"] == r.seeds["drums"]
    assert [s.prog for s in mel.sections] == [s.prog for s in r.sections]
    harm = remix(r, reseed=("harmony",), new_seed=2)
    assert [s.prog for s in harm.sections] != [s.prog for s in r.sections] or harm.seeds["harmony"] != r.seeds["harmony"]
    assert [s.bars for s in harm.sections] == [s.bars for s in r.sections]
    jazz = remix(r, words="jazz")
    assert jazz.style["drums"] == "swing" and jazz.style["name"] == "jazz" and jazz.style["root_pc"] == r.style["root_pc"]
    assert [s.bars for s in jazz.sections] == [s.bars for s in r.sections]
    unchanged = remix(r, words="blah blah")
    assert unchanged.style == r.style


def test_remix_key_tempo_voice_and_validity():
    r = base_recipe()
    k = remix(r, key="D minor")
    assert k.style["root_pc"] == 2 and k.style["mode"] == "minor"
    p = plan_from_recipe(k)
    pcs = {(2 + x) % 12 for x in [0, 2, 3, 5, 7, 8, 10]}
    assert all(n.midi % 12 in pcs for s in p.sections for n in s.notes)
    f = remix(r, bpm=r.style["bpm"] * 2)
    assert abs(f.duration - r.duration / 2) < 0.01
    assert not any(n[5] for n in notes(remix(r, vocal=False)))
    assert any(n[5] for n in notes(r))
    assert remix(r, words="happy bright").style["mode"] in ("major", "pentatonic_major", "lydian")
    for rr in (k, f, drums_ := remix(r, reseed=("melody", "harmony", "drums"))):
        assert validate_recipe(json.loads(json.dumps(rr.to_dict()))) == rr
    with pytest.raises(ValueError):
        remix(r, bpm=40, max_seconds=10)


def test_extend_adds_a_new_tune_in_the_same_key_and_keeps_the_start_intact():
    r = base_recipe(dur=60)
    e = extend(r, 30, new_seed=5)
    assert e.style == r.style and e.seeds == r.seeds and e.extensions == 1
    assert e.sections[:len(r.sections)] == r.sections                   # the original part is untouched
    new = e.sections[len(r.sections):]
    assert new and all(s.motif.startswith("x1-") for s in new)
    assert abs(e.duration - (r.duration + 30)) < 240 / r.style["bpm"]    # within one bar of the requested length
    assert {tuple(s.prog) for s in new} != {tuple(s.prog) for s in r.sections}
    pcs = {(r.style["root_pc"] + x) % 12 for x in [0, 2, 3, 5, 7, 8, 10, 9, 11, 1, 4, 6]}
    assert notes(e)[:len(notes(r))] == notes(r)                          # same notes for the original sections
    a_old, a_new = audio(r), audio(e)
    keep = len(a_old) - int(3.5 * plan_from_recipe(r).spb * SR)          # everything before the old ending is bit-identical
    assert np.array_equal(a_old[:keep], a_new[:keep])
    assert len(a_new) == round(e.duration * SR) and float(np.abs(a_new[len(a_old):]).max()) > 0.05
    e2 = extend(e, 20, new_seed=6)
    assert e2.extensions == 2 and {s.motif for s in e2.sections[len(e.sections):]} <= {"x2-verse", "x2-chorus", "x2-bridge"}
    assert validate_recipe(json.loads(json.dumps(e2.to_dict()))) == e2


def test_extend_moves_the_ending_and_takes_lyrics_and_respects_the_cap():
    r = make_recipe("house dance", "", 60, 3)                           # default form ends with an outro
    assert r.sections[-1].kind == "outro"
    e = extend(r, 40, new_seed=1)
    assert e.sections[-1].kind == "outro" and [s.kind for s in e.sections].count("outro") == 1     # one ending, at the new end
    l = extend(base_recipe(), 30, lyrics="[verse]\nBrand new words here", new_seed=2)
    assert any("Brand new words here" in s.lines for s in l.sections) and "Brand new words here" in l.lyrics
    assert any(n[5] for n in notes(l)[len(notes(base_recipe())):])
    with pytest.raises(ValueError, match="maximum"):
        extend(base_recipe(), 1000, max_seconds=100)
    tiny = extend(base_recipe(), 1, new_seed=1)
    assert tiny.total_bars > base_recipe().total_bars


def test_extension_is_deterministic_for_a_given_seed():
    r = base_recipe()
    assert extend(r, 30, new_seed=9) == extend(r, 30, new_seed=9) and extend(r, 30, new_seed=9) != extend(r, 30, new_seed=10)
