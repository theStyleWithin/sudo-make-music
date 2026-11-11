from sudo_make_music.backends.procedural import ProceduralBackend
from sudo_make_music.cards import CardStore
from sudo_make_music.samples import SAMPLES, PREFIX, install_samples
from sudo_make_music.settings import SettingsStore


def test_samples_installed_once_and_valid(tmp_path):
    cards, store = CardStore(tmp_path / "c"), SettingsStore(tmp_path / "s.json")
    assert install_samples(cards, store) == len(SAMPLES)
    got = cards.list()
    assert len(got) == len(SAMPLES) and all(c.name.startswith(PREFIX) and not c.stale for c in got)
    assert len({c.recipe.style["name"] for c in got}) >= 6          # a spread of genres
    assert install_samples(cards, store) == 0                       # not added twice
    cards.delete(got[0].id)
    assert install_samples(CardStore(tmp_path / "c"), SettingsStore(tmp_path / "s.json")) == 0   # deleted ones stay deleted


def test_every_sample_renders(tmp_path):
    cards, store = CardStore(tmp_path / "c"), SettingsStore(tmp_path / "s.json")
    install_samples(cards, store)
    for c in cards.list():
        r = c.recipe
        assert 60 <= r.duration <= 130
        r.sections = r.sections[:1]                                 # one section is enough to prove it renders
        import numpy as np
        audio = np.concatenate([x.audio for x in ProceduralBackend().stream_recipe(r, None, lambda f: None, lambda: False)])
        assert audio.size and np.isfinite(audio).all() and np.abs(audio).max() > 0.01
