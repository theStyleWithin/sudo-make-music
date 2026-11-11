"""Sample song cards that ship with the app, so new users have recipes to look at, play, remix and extend.

They are built from short prompts with fixed seeds (no data files to package) and added once, on first run.
Deleting them is fine: they are not added again.
"""
from __future__ import annotations

from .backends.procedural import make_recipe

PREFIX = "Sample: "

# (card name, style prompt, lyrics, seconds, seed)
SAMPLES = [
    ("Lo-fi study beat", "lo-fi chill, rainy night, mellow", "", 90, 11),
    ("Club night (house)", "house dance, upbeat, bright, instrumental", "", 120, 12),
    ("Night drive (synthwave)", "synthwave, retro, neon, driving",
     "[verse]\nNeon rivers in the dark\nEngine humming, city sparks\n[chorus]\nDrive, drive, into the light\nWe are the night", 120, 13),
    ("Slow sunrise (ambient)", "ambient cinematic, dreamy, calm", "", 100, 14),
    ("Open road (rock)", "rock, energetic, driving",
     "[verse]\nWheels on the highway, sun on my face\nNowhere to be and no one to chase\n[chorus]\nHey, hey, we keep on running", 120, 15),
    ("Late-night jazz", "jazz, smooth, relaxed, instrumental", "", 100, 16),
    ("Lift off (trance)", "trance, euphoric, uplifting, instrumental", "", 120, 17),
    ("Pixel quest (chiptune)", "chiptune, 8-bit, playful, instrumental", "", 80, 18),
]


def install_samples(cards, settings_store) -> int:
    """Add the sample cards once. Returns how many were added."""
    if getattr(settings_store.value, "samples_seeded", False):
        return 0
    n = 0
    for name, prompt, lyrics, seconds, seed in SAMPLES:
        try:
            cards.create(PREFIX + name, make_recipe(prompt, lyrics, seconds, seed))
            n += 1
        except Exception:
            continue                      # never block startup over a sample
    settings_store.value.samples_seeded = True
    settings_store.save()
    return n
