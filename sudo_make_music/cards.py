"""Song cards: a procedural song kept on file as a tiny recipe (a few KB of plain data, no audio, no code).

A card rebuilds the same song every time, and can be remixed or extended into a new card. Cards live in their own
library (separate from songs), can be exported as a small file and imported again. Anything imported is untrusted
input: it is validated field by field and rebuilt from a whitelist, never executed."""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .backends.procedural import DRUMS, ENERGY, ENGINE_VERSION, MAX_SECONDS, SCALES, Recipe, SectionRecipe

MAX_FILE_BYTES = 300_000
WAVES = {"sine", "triangle", "square", "saw", "sub"}
MOTIF = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def _int(v, lo, hi, what):
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise ValueError(f"{what} must be a whole number from {lo} to {hi}")
    return v


def _num(v, lo, hi, what):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise ValueError(f"{what} must be a number from {lo} to {hi}")
    return float(v)


def _str(v, maxlen, what):
    if not isinstance(v, str) or len(v) > maxlen or any(ord(c) < 32 and c not in "\n\t" for c in v):
        raise ValueError(f"{what} must be text of at most {maxlen} characters")
    return v


def validate_recipe(d) -> Recipe:
    """Strict check of an untrusted recipe; returns a freshly built Recipe (unknown keys are dropped)."""
    if not isinstance(d, dict):
        raise ValueError("the recipe is not an object")
    st = d.get("style")
    if not isinstance(st, dict):
        raise ValueError("the recipe has no style")
    if st.get("mode") not in SCALES or st.get("drums") not in DRUMS:
        raise ValueError("unknown mode or drum pattern")
    for k in ("lead", "pad", "bass"):
        if st.get(k) not in WAVES:
            raise ValueError(f"unknown instrument for {k}")
    if not isinstance(st.get("vocal"), bool):
        raise ValueError("vocal must be true or false")
    style = dict(name=_str(st.get("name"), 24, "style name"), bpm=_num(st.get("bpm"), 30, 260, "tempo"),
                 mode=st["mode"], root_pc=_int(st.get("root_pc"), 0, 11, "key"), swing=_num(st.get("swing"), 0, 0.5, "swing"),
                 drums=st["drums"], lead=st["lead"], pad=st["pad"], bass=st["bass"],
                 density=_num(st.get("density"), 0, 1, "density"), echo=_num(st.get("echo"), 0, 1, "echo"), vocal=st["vocal"])
    sd = d.get("seeds")
    if not isinstance(sd, dict):
        raise ValueError("the recipe has no seeds")
    seeds = {k: _int(sd.get(k), 1, 2 ** 31, f"{k} seed") for k in ("drums", "melody", "harmony")}
    raw = d.get("sections")
    if not isinstance(raw, list) or not 1 <= len(raw) <= 300:
        raise ValueError("a song needs 1 to 300 sections")
    secs = []
    for x in raw:
        if not isinstance(x, dict) or x.get("kind") not in ENERGY:
            raise ValueError("unknown section kind")
        prog, lines = x.get("prog"), x.get("lines", [])
        if not isinstance(prog, list) or not 1 <= len(prog) <= 16 or not isinstance(lines, list) or len(lines) > 64:
            raise ValueError("bad chords or lyric lines in a section")
        motif = x.get("motif", "verse")
        if not isinstance(motif, str) or not MOTIF.match(motif):
            raise ValueError("bad motif name")
        secs.append(SectionRecipe(x["kind"], _int(x.get("bars"), 1, 512, "bars"),
                                  [_int(p, 0, 13, "chord") for p in prog], [_str(l, 300, "lyric line") for l in lines], motif))
    r = Recipe(_str(d.get("prompt", ""), 500, "prompt"), _str(d.get("lyrics", ""), 20000, "lyrics"),
               _int(d.get("seed", 0), 0, 2 ** 32, "seed"), style, seeds, secs,
               engine=_int(d.get("engine", ENGINE_VERSION), 0, 1000, "engine version"),
               extensions=_int(d.get("extensions", 0), 0, 1000, "extension count"))
    if r.duration > MAX_SECONDS:
        raise ValueError("the song is longer than the maximum length")
    return r


@dataclass
class Card:
    id: str
    name: str
    created: float
    parent: str | None
    recipe: Recipe

    @property
    def stale(self) -> bool:
        """Made by a different version of the music engine: it may sound different now."""
        return self.recipe.engine != ENGINE_VERSION

    def to_file(self) -> dict:
        return {"format": "smm-card", "version": 1, "id": self.id, "name": self.name, "created": self.created,
                "parent": self.parent, "recipe": self.recipe.to_dict()}


def _clean_name(name: str) -> str:
    name = re.sub(r"[\x00-\x1f]", " ", str(name)).strip()[:80]
    return name or "Untitled card"


class CardStore:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else paths.home() / "cards"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, card_id: str) -> Path:
        if not card_id.isalnum():
            raise ValueError("bad card id")
        return self.root / f"{card_id}.json"

    def _write(self, c: Card) -> Card:
        tmp = self._path(c.id).with_suffix(".tmp")
        tmp.write_text(json.dumps(c.to_file(), indent=1), encoding="utf-8")
        tmp.replace(self._path(c.id))
        return c

    def create(self, name: str, recipe: Recipe, parent: str | None = None) -> Card:
        return self._write(Card(uuid.uuid4().hex[:10], _clean_name(name), time.time(), parent, recipe))

    def get(self, card_id: str) -> Card | None:
        try:
            doc = json.loads(self._path(card_id).read_text(encoding="utf-8"))
            return Card(doc["id"], _clean_name(doc["name"]), float(doc["created"]), doc.get("parent"), validate_recipe(doc["recipe"]))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def list(self) -> list[Card]:
        cards = [self.get(p.stem) for p in self.root.glob("*.json")]
        return sorted([c for c in cards if c], key=lambda c: c.created, reverse=True)

    def rename(self, card_id: str, name: str) -> Card:
        c = self.get(card_id)
        if not c:
            raise ValueError("no such card")
        c.name = _clean_name(name)
        return self._write(c)

    def delete(self, card_id: str) -> None:
        self._path(card_id).unlink(missing_ok=True)

    def export_to(self, card_id: str, dest: Path) -> Path:
        c = self.get(card_id)
        if not c:
            raise ValueError("no such card")
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(c.to_file(), indent=1), encoding="utf-8")
        return dest

    def import_file(self, path: Path) -> Card:
        path = Path(path)
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("not a card file (missing, or larger than 300 KB)")
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise ValueError("not a card file (not valid JSON)") from e
        if not isinstance(doc, dict) or doc.get("format") != "smm-card":
            raise ValueError("not a sudo make music card file")
        return self.create(doc.get("name", path.stem), validate_recipe(doc.get("recipe")))     # always a fresh id, no parent
