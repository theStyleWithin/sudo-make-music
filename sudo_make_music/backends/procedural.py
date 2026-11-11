"""Procedural music (BETA): songs built from rules, no AI model, numpy only.

In the spirit of seed-driven procedural generation: one seed + your style words + your lyrics deterministically produce
a whole song (same input = same song). The style words pick tempo, scale, chord progressions, drum pattern and
instruments; the lyrics (with [verse]/[chorus]/... tags) set the song's structure, and each lyric line becomes a melody
phrase with one note per syllable, played by a robotic "vowel voice" (it follows the vowels of your words but does not
pronounce them). The whole song is planned first (intro/verse/chorus/...), then rendered section by section and streamed
to disk, so a 30 minute song needs no more memory than a 1 minute one.

It sounds like a game score or a synth track, not a band. That is why it is labelled BETA."""
from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

from ..memory import GenParams
from .base import ModelBackend, SegmentRequest, SegmentResult, Cancelled, register

SR = 44100
SCALES = {
    "major": [0, 2, 4, 5, 7, 9, 11], "minor": [0, 2, 3, 5, 7, 8, 10], "dorian": [0, 2, 3, 5, 7, 9, 10],
    "phrygian": [0, 1, 3, 5, 7, 8, 10], "lydian": [0, 2, 4, 6, 7, 9, 11],
    "pentatonic_minor": [0, 3, 5, 7, 10], "pentatonic_major": [0, 2, 4, 7, 9],
}
MINORISH = {"minor", "dorian", "phrygian", "pentatonic_minor"}
PROG_MINOR = [[0, 5, 2, 6], [0, 3, 4, 0], [0, 6, 5, 6], [0, 2, 6, 3], [0, 5, 3, 4]]
PROG_MAJOR = [[0, 4, 5, 3], [0, 5, 3, 4], [0, 3, 4, 3], [1, 4, 0, 0], [0, 2, 3, 4]]
VOWEL_FORMANTS = {"a": (800, 1200, 2600), "e": (450, 1900, 2600), "i": (300, 2300, 3000),
                  "o": (500, 900, 2500), "u": (320, 800, 2400)}
RHYTHMS = [[0, 4, 8, 12], [0, 3, 6, 8, 11, 14], [0, 2, 4, 8, 10, 12], [0, 6, 8, 14], [0, 4, 6, 8, 12, 14], [0, 8],
           [0, 2, 4, 6, 8, 10, 12, 14]]
FORM_DEFAULT = ["intro", "verse", "chorus", "verse", "chorus", "bridge", "chorus", "outro"]
BASE_BARS = {"intro": 4, "verse": 8, "pre": 4, "chorus": 8, "bridge": 4, "outro": 4, "solo": 8, "drop": 8}
PRIORITY = {"bridge": 0, "pre": 1, "solo": 2, "outro": 2, "intro": 3, "drop": 4, "verse": 5, "chorus": 6}
ENERGY = {  # per section kind: pad, bass, drums (none/light/full/big), lead, voice, octave-double
    "intro": dict(pad=1.0, bass=0.0, drums="light", lead=0.6, voice=0.0, dbl=False),
    "verse": dict(pad=0.9, bass=1.0, drums="full", lead=0.55, voice=1.0, dbl=False),
    "pre": dict(pad=1.0, bass=1.0, drums="light", lead=0.6, voice=1.0, dbl=False),
    "chorus": dict(pad=1.2, bass=1.0, drums="big", lead=0.9, voice=1.0, dbl=True),
    "bridge": dict(pad=1.1, bass=0.6, drums="none", lead=0.7, voice=1.0, dbl=False),
    "outro": dict(pad=1.0, bass=0.5, drums="light", lead=0.5, voice=0.7, dbl=False),
    "solo": dict(pad=0.9, bass=1.0, drums="full", lead=1.0, voice=0.0, dbl=True),
    "drop": dict(pad=1.0, bass=1.0, drums="big", lead=1.0, voice=0.0, dbl=True),
}
GENRES = [  # (keywords, settings). First match wins; later words can still tweak mood/tempo.
    (("lo-fi", "lofi", "lo fi", "chillhop", "hip hop", "hip-hop", "hiphop", "study", "chill"),
     dict(name="lo-fi", bpm=(70, 88), modes=("minor", "dorian"), swing=0.18, drums="boombap", lead="triangle", pad="sine", bass="sub", density=0.4, echo=0.25)),
    (("trance",), dict(name="trance", bpm=(136, 146), modes=("minor",), swing=0, drums="fourfloor", lead="saw", pad="saw", bass="saw", density=0.7, echo=0.3)),
    (("techno",), dict(name="techno", bpm=(128, 140), modes=("minor", "phrygian"), swing=0, drums="fourfloor", lead="square", pad="saw", bass="saw", density=0.5, echo=0.2)),
    (("house", "edm", "dance", "club", "disco"), dict(name="house", bpm=(120, 130), modes=("minor", "major", "dorian"), swing=0.05, drums="fourfloor", lead="saw", pad="saw", bass="saw", density=0.6, echo=0.2)),
    (("synthwave", "retrowave", "outrun", "80s", "eighties"), dict(name="synthwave", bpm=(100, 118), modes=("minor",), swing=0, drums="rock", lead="saw", pad="saw", bass="saw", density=0.55, echo=0.35)),
    (("chiptune", "8-bit", "8 bit", "8bit", "arcade", "retro game", "video game"), dict(name="chiptune", bpm=(120, 150), modes=("major", "pentatonic_major", "minor"), swing=0, drums="breakbeat", lead="square", pad="square", bass="square", density=0.75, echo=0.1)),
    (("metal", "punk", "rock", "grunge", "guitar"), dict(name="rock", bpm=(112, 160), modes=("minor", "major"), swing=0, drums="rock", lead="saw", pad="saw", bass="saw", density=0.7, echo=0.1)),
    (("jazz", "swing", "bossa", "bebop"), dict(name="jazz", bpm=(96, 140), modes=("dorian", "major"), swing=0.3, drums="swing", lead="triangle", pad="sine", bass="sub", density=0.5, echo=0.15)),
    (("ambient", "cinematic", "epic", "orchestral", "atmospheric", "drone", "space", "dreamy", "dream pop", "shoegaze", "meditation", "calm"),
     dict(name="ambient", bpm=(56, 80), modes=("dorian", "lydian", "minor"), swing=0, drums="none", lead="sine", pad="saw", bass="sub", density=0.25, echo=0.5)),
]
DEFAULT_STYLE = dict(name="pop", bpm=(96, 112), modes=("minor", "major"), swing=0.05, drums="boombap", lead="triangle", pad="sine", bass="sub", density=0.5, echo=0.2)
SAD = ("sad", "dark", "melanchol", "moody", "night", "rain", "lonely", "tense", "gloom", "haunt", "cry")
HAPPY = ("happy", "bright", "uplift", "joy", "sunny", "upbeat", "cheer", "fun", "summer", "party")
ANGRY = ("angry", "aggressive", "rage", "evil", "doom")


@dataclass
class Style:
    name: str
    bpm: float
    mode: str
    root_pc: int
    swing: float
    drums: str
    lead: str
    pad: str
    bass: str
    density: float
    echo: float
    vocal: bool


@dataclass
class Note:
    bar: int            # bar within the section
    step: int           # 16th-note step within the bar (0-15)
    length: int         # in 16th notes
    midi: int
    vowel: str | None = None


@dataclass
class Section:
    kind: str
    bars: int
    chords: list = field(default_factory=list)      # per bar: root degree of the chord
    lines: list = field(default_factory=list)       # lyric lines
    notes: list = field(default_factory=list)       # melody notes (voiced when `vowel` is set)


@dataclass
class Plan:
    style: Style
    bpm: float
    scale: list
    sections: list
    total_bars: int
    duration: float
    seed: int

    @property
    def spb(self) -> float:        # seconds per bar (4/4)
        return 240.0 / self.bpm


# ------------------------------------------------------------------ text -> style / structure
def parse_style(prompt: str, lyrics: str, rng: np.random.Generator) -> Style:
    text = f"{prompt} {lyrics[:200]}".lower()
    cfg = next((c for kws, c in GENRES if any(k in text for k in kws)), DEFAULT_STYLE)
    lo, hi = cfg["bpm"]
    bpm = float(rng.uniform(lo, hi))
    m = re.search(r"(\d{2,3})\s*bpm", text)
    if m and 40 <= int(m.group(1)) <= 220:
        bpm = float(int(m.group(1)))
    else:
        bpm *= 0.82 if re.search(r"\bslow", text) else 1.18 if re.search(r"\b(fast|energetic|uptempo)", text) else 1.0
    mode = str(rng.choice(cfg["modes"]))
    if any(k in text for k in ANGRY):
        mode = "phrygian"
    elif any(k in text for k in SAD) and mode not in MINORISH:
        mode = "minor"
    elif any(k in text for k in HAPPY) and mode in MINORISH:
        mode = "major" if mode != "pentatonic_minor" else "pentatonic_major"
    root = int(rng.integers(0, 12))
    k = re.search(r"\b([a-g])(#|b)?\s*(major|minor)\b", text)
    if k:
        root = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}[k.group(1)] + {"#": 1, "b": -1}.get(k.group(2) or "", 0)
        root %= 12
        mode = k.group(3)
    return Style(cfg["name"], bpm, mode, root, cfg["swing"], cfg["drums"], cfg["lead"], cfg["pad"], cfg["bass"],
                 cfg["density"], cfg["echo"], vocal=not re.search(r"instrumental|no vocal|without vocal", text))


_TAG = re.compile(r"^\s*\[([^\]]+)\]\s*$")


def _kind(tag: str) -> str:
    t = tag.lower()
    for k, names in (("pre", ("pre",)), ("chorus", ("chorus", "hook", "refrain")), ("verse", ("verse",)), ("bridge", ("bridge", "middle")),
                     ("intro", ("intro",)), ("outro", ("outro", "end")), ("solo", ("solo", "instrumental", "break")), ("drop", ("drop",))):
        if any(n in t for n in names):
            return k
    return "verse"


def parse_lyrics(lyrics: str) -> list[tuple[str, list[str]]]:
    """[(kind, lines)]: from [tags] if present, else blocks separated by blank lines alternate verse/chorus."""
    secs: list[tuple[str, list[str]]] = []
    cur: tuple[str, list[str]] | None = None
    blocks: list[list[str]] = [[]]
    tagged = any(_TAG.match(l) for l in lyrics.splitlines())
    for raw in lyrics.splitlines():
        line = raw.strip()
        m = _TAG.match(raw)
        if tagged:
            if m:
                cur = (_kind(m.group(1)), [])
                secs.append(cur)
            elif line and cur is not None:
                cur[1].append(line)
            elif line:
                cur = ("verse", [line])
                secs.append(cur)
        elif line:
            blocks[-1].append(line)
        elif blocks[-1]:
            blocks.append([])
    if not tagged:
        for i, b in enumerate([b for b in blocks if b]):
            secs.append((("verse", "chorus")[i % 2], b))
    return secs


def syllables(line: str) -> list[str]:
    """One vowel letter (a e i o u) per syllable: rough, English-ish, good enough to drive a vowel voice."""
    out: list[str] = []
    for word in re.findall(r"[a-zA-Z']+", line.lower()):
        groups = re.findall(r"[aeiouy]+", word)
        if len(groups) > 1 and word.endswith("e") and not word.endswith(("le", "ee")) and groups[-1] == "e":
            groups = groups[:-1]
        for g in groups or ["a"]:
            v = g[0]
            out.append("i" if v == "y" else v)
    return out or ["a"]


def _allocate(weights: list[float], total: int, min_bars: int) -> list[int]:
    s = sum(weights)
    raw = [w * total / s for w in weights]
    bars = [max(min_bars, int(r)) for r in raw]
    order = sorted(range(len(bars)), key=lambda i: -(raw[i] - int(raw[i])))
    j = 0
    while sum(bars) < total:
        bars[order[j % len(bars)]] += 1
        j += 1
    while sum(bars) > total:
        i = max(range(len(bars)), key=lambda i: bars[i])
        if bars[i] <= min_bars:
            break
        bars[i] -= 1
    return bars


# ------------------------------------------------------------------ the plan (pure symbolic: easy to test)
def scale_note(base: int, scale: list, degree: int) -> int:
    return base + 12 * (degree // len(scale)) + scale[degree % len(scale)]


def plan_song(prompt: str, lyrics: str, duration: float, seed: int) -> Plan:
    rng = np.random.default_rng([int(seed) & 0xFFFFFFFF, zlib.crc32(f"{prompt}\n{lyrics}".encode())])
    style = parse_style(prompt, lyrics, rng)
    scale = SCALES[style.mode]
    total_bars = max(2, round(duration * style.bpm / 240.0))
    bpm = 240.0 * total_bars / duration                   # nudge the tempo so the song lands exactly on the requested length
    form: list[tuple[str, list[str]]] = parse_lyrics(lyrics) if lyrics.strip() else []
    if not form:
        form = [(k, []) for k in FORM_DEFAULT]
    elif style.vocal and form[0][0] not in ("intro",) and total_bars >= 24:
        form = [("intro", [])] + form
    while len(form) > 1 and total_bars < 3 * len(form):    # short song: drop the least important sections first
        i = min(range(len(form)), key=lambda i: (PRIORITY[form[i][0]], -i))
        form.pop(i)
    weights = [float(max(BASE_BARS[k], min(16, 2 * len(l)) if l else 0)) for k, l in form]
    bars = _allocate(weights, total_bars, 2 if total_bars >= 2 * len(form) else 1)
    progs = PROG_MINOR if style.mode in MINORISH else PROG_MAJOR
    pick = {k: progs[int(rng.integers(len(progs)))] for k in ("verse", "chorus", "bridge")}
    pick["bridge"] = progs[(progs.index(pick["verse"]) + 2) % len(progs)]
    chord_len = 1 if bpm >= 80 else 2
    base = 60 + (((style.root_pc + 5) % 12) - 5)
    secs: list[Section] = []
    motifs: dict[str, list] = {}
    for (kind, lines), nb in zip(form, bars):
        prog = pick.get(kind if kind in pick else "verse")
        sec = Section(kind, nb, [prog[(b // chord_len) % len(prog)] for b in range(nb)], list(lines))
        _melody(sec, style, scale, base, rng, motifs)
        secs.append(sec)
    return Plan(style, bpm, scale, secs, total_bars, duration, int(seed))


def _snap(scale: list, deg: int, chord: int) -> int:
    tones = [chord + o for o in (0, 2, 4)]
    cands = [t + 7 * k for t in tones for k in (-1, 0, 1)]
    return min(cands, key=lambda c: abs(c - deg))


def _walk(rng, deg: int, lo: int = 5, hi: int = 14) -> int:
    deg += int(rng.choice([-2, -1, -1, 0, 1, 1, 2, 3, -3], p=[.1, .22, .22, .08, .22, .08, .04, .02, .02]))
    return int(min(hi, max(lo, deg)))


def _melody(sec: Section, style: Style, scale: list, base: int, rng, motifs: dict) -> None:
    n = len(scale)
    lines = sec.lines if style.vocal else []
    bpl = 2 if len(lines) * 2 <= sec.bars else 1
    deg = 8
    bar = 0
    for line in lines:
        if bar + bpl > sec.bars:
            break
        vowels = syllables(line)[:14]
        steps = 16 * bpl
        pos = sorted({min(steps - 1, round(k * steps / len(vowels))) for k in range(len(vowels))})
        vowels = vowels[:len(pos)]
        for k, (p, v) in enumerate(zip(pos, vowels)):
            b, st = divmod(p, 16)
            chord = sec.chords[bar + b]
            deg = _snap(scale, _walk(rng, deg), chord) if (k == 0 or k == len(pos) - 1 or st % 8 == 0) else _walk(rng, deg)
            nxt = pos[k + 1] if k + 1 < len(pos) else steps
            sec.notes.append(Note(bar + b, st, int(min(8, max(1, nxt - p))), scale_note(base, scale, deg), v))
        bar += bpl
    # instrumental melody (lead) for the rest of the section
    key = sec.kind if sec.kind in ("verse", "chorus", "bridge") else "verse"
    if key not in motifs:
        pats = [r for r in RHYTHMS if (len(r) <= 4) == (style.density < 0.5)] or RHYTHMS
        motif, d = [], 8
        for b in range(2):
            pat = pats[int(rng.integers(len(pats)))]
            for i, st in enumerate(pat):
                d = _walk(rng, d)
                length = (pat[i + 1] if i + 1 < len(pat) else 16) - st
                motif.append((b, st, int(min(6, max(1, length))), d - 7))
        motifs[key] = motif
    for b in range(bar, sec.bars):
        chord = sec.chords[b]
        for mb, st, ln, off in motifs[key]:
            if mb != b % 2:
                continue
            d = _snap(scale, 7 + off + chord, chord) if st in (0, 8) else int(min(16, max(4, 7 + off + chord)))
            if b % 4 == 3 and st >= 12:
                d = min(16, d + 1)                          # small variation at the end of every 4th bar
            sec.notes.append(Note(b, st, ln, scale_note(base, scale, d), None))


# ------------------------------------------------------------------ sound
@lru_cache(maxsize=None)
def _table(kind: str, harmonics: int) -> np.ndarray:
    ph = np.linspace(0, 2 * np.pi, 2048, endpoint=False)
    if kind == "sine":
        t = np.sin(ph)
    elif kind == "triangle":
        t = sum(((-1) ** ((k - 1) // 2)) * np.sin(k * ph) / k ** 2 for k in range(1, 2 * harmonics, 2)) * (8 / np.pi ** 2)
    elif kind == "square":
        t = sum(np.sin(k * ph) / k for k in range(1, 2 * harmonics, 2)) * (4 / np.pi) * 0.7
    else:                                                    # saw
        t = sum(np.sin(k * ph) / k for k in range(1, harmonics + 1)) * (2 / np.pi) * 0.8
    return (t / max(1e-9, np.max(np.abs(t)))).astype(np.float32)


def osc(kind: str, freq: float, n: int, detune_cents: float = 0.0) -> np.ndarray:
    f = freq * 2 ** (detune_cents / 1200)
    tab = _table(kind, int(max(1, min(48, 9000 / f))))
    idx = ((np.arange(n) * (f / SR)) % 1.0) * 2048
    i0 = idx.astype(np.int64)
    fr = (idx - i0).astype(np.float32)
    return tab[i0] * (1 - fr) + tab[(i0 + 1) % 2048] * fr


def adsr(n: int, a: float, d: float, s: float, r: float) -> np.ndarray:
    dur = n / SR
    a, r = min(a, dur * 0.4), min(r, dur * 0.4)
    d = min(d, max(0.0, dur - a - r))
    xs = [0, a, a + d, max(dur - r, a + d), dur]
    return np.interp(np.arange(n) / SR, xs, [0, 1, s, s, 0]).astype(np.float32)


def midi_hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def vowel_voice(freq: float, vowel: str, n: int) -> np.ndarray:
    """Buzzy source shaped by vowel formants: a robotic choir that follows the vowels of the lyrics."""
    t = np.arange(n) / SR
    vib = 1 + 0.005 * np.sin(2 * np.pi * 5.3 * t) * np.clip(t / 0.25, 0, 1)
    phase = 2 * np.pi * np.cumsum(freq * vib) / SR
    src = np.zeros(n)
    for k in range(1, int(min(40, 5000 / freq)) + 1):
        src += np.sin(k * phase) / k
    spec = np.fft.rfft(src)
    f = np.fft.rfftfreq(n, 1 / SR)
    env = np.full_like(f, 0.03)
    for fm, bw, amp in zip(VOWEL_FORMANTS[vowel], (90, 110, 150), (1.0, 0.6, 0.35)):
        env += amp * np.exp(-0.5 * ((f - fm) / bw) ** 2)
    out = np.fft.irfft(spec * env, n).astype(np.float32)
    return out / max(1e-6, float(np.max(np.abs(out))))


def _drum_kit(rng: np.random.Generator, chip: bool) -> dict:
    t = lambda d: np.arange(int(d * SR)) / SR
    tk = t(0.35)
    f = 45 + 75 * np.exp(-tk * 35)
    kick = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tk * 16)
    ts = t(0.22)
    noise = rng.standard_normal(len(ts))
    snare = noise * np.exp(-ts * 24) * 0.55 + np.sin(2 * np.pi * 190 * ts) * np.exp(-ts * 30) * 0.5
    th = t(0.07)
    hn = rng.standard_normal(len(th) + 1)
    hat = np.diff(hn) * np.exp(-th * 90) * 0.5
    to = t(0.28)
    on = rng.standard_normal(len(to) + 1)
    openhat = np.diff(on) * np.exp(-to * 14) * 0.45
    if chip:
        kick, snare = kick * np.sign(np.sin(np.cumsum(f) * 2 * np.pi / SR + 1e-9)), np.sign(noise) * np.exp(-ts * 30) * 0.5
    return {k: v.astype(np.float32) for k, v in dict(kick=kick, snare=snare, hat=hat, open=openhat).items()}


DRUMS = {  # step lists on a 16 grid
    "fourfloor": dict(kick=[0, 4, 8, 12], snare=[4, 12], hat=[2, 6, 10, 14], bass=[2, 6, 10, 14]),
    "boombap": dict(kick=[0, 7, 10], snare=[4, 12], hat=list(range(0, 16, 2)), bass=[0, 7, 10]),
    "breakbeat": dict(kick=[0, 6, 10], snare=[4, 12, 14], hat=list(range(0, 16, 2)), bass=[0, 3, 6, 10]),
    "rock": dict(kick=[0, 8, 10], snare=[4, 12], hat=list(range(0, 16, 2)), bass=list(range(0, 16, 2))),
    "swing": dict(kick=[0, 10], snare=[4, 12], hat=[0, 4, 7, 8, 12, 15], bass=[0, 4, 8, 12]),
    "none": dict(kick=[], snare=[], hat=[], bass=[0]),
}


class Renderer:
    def __init__(self, plan: Plan):
        self.p = plan
        self.rng = np.random.default_rng([plan.seed & 0xFFFFFFFF, 7])
        self.kit = _drum_kit(self.rng, plan.style.name == "chiptune")
        self.base = 60 + (((plan.style.root_pc + 5) % 12) - 5)

    def _place(self, buf, start, sig, gain, pan=0.0, echo=0.0):
        gl, gr = gain * np.sqrt((1 - pan) / 2), gain * np.sqrt((1 + pan) / 2)
        taps = [(0, 1.0)] + ([(int(0.75 * 60 / self.p.bpm * SR), echo * 0.6), (int(1.5 * 60 / self.p.bpm * SR), echo * 0.3)] if echo > 0.05 else [])
        for off, g in taps:
            s0 = start + off
            if s0 >= len(buf):
                continue
            e = min(len(buf), s0 + len(sig))
            buf[s0:e, 0] += sig[:e - s0] * (gl * g)
            buf[s0:e, 1] += sig[:e - s0] * (gr * g)

    def section(self, sec: Section, tail: int) -> np.ndarray:
        p, st = self.p, self.p.style
        spb = p.spb
        bar_n = int(round(spb * SR))
        sec_n = bar_n * sec.bars
        buf = np.zeros((sec_n + tail, 2), np.float32)
        en = ENERGY[sec.kind]
        step_n = bar_n / 16
        swing = lambda s: int(step_n * (s + (st.swing if s % 2 else 0.0)))
        pat = DRUMS[st.drums]
        for b in range(sec.bars):
            o = b * bar_n
            root_deg = sec.chords[b]
            tri = [scale_note(self.base - 12, p.scale, root_deg + k) for k in (0, 2, 4)]
            if en["pad"]:                                    # pad: the chord, slightly detuned left/right for width
                n = int(bar_n * 1.12)
                env = adsr(n, 0.25 * spb, 0.2, 0.8, 0.35 * spb)
                for side, det in ((-1, -7), (1, 7)):
                    sig = sum(osc(st.pad, midi_hz(m), n, det) for m in tri) / 3 * env
                    self._place(buf, o, sig, 0.11 * en["pad"], side * 0.6)
            drums = en["drums"]
            if en["bass"]:
                bm = scale_note(self.base - 24, p.scale, root_deg)
                for s in pat["bass"]:
                    ln = 2 if st.drums in ("fourfloor", "rock") else 5 if st.drums != "none" else 15
                    n = int(step_n * ln)
                    sig = osc("sine" if st.bass == "sub" else st.bass, midi_hz(bm), n) * adsr(n, 0.004, 0.05, 0.8, 0.04)
                    self._place(buf, o + swing(s), sig, 0.30 * en["bass"])
            if drums != "none" and st.drums != "none":
                hats = pat["hat"] if drums != "big" else sorted(set(pat["hat"]) | set(range(1, 16, 2)))
                if drums == "light":
                    hats = pat["hat"][::2]
                for s in hats:
                    self._place(buf, o + swing(s), self.kit["hat"], 0.10 if s % 4 else 0.14, 0.3)
                if drums in ("full", "big"):
                    for s in pat["kick"]:
                        self._place(buf, o + swing(s), self.kit["kick"], 0.55)
                    for s in pat["snare"]:
                        self._place(buf, o + swing(s), self.kit["snare"], 0.32, -0.1)
                    if b == sec.bars - 1:                    # fill into the next section
                        for s in (12, 13, 14, 15):
                            self._place(buf, o + swing(s), self.kit["snare"], 0.14 + 0.03 * (s - 12))
                    if b % 4 == 0 and st.drums not in ("fourfloor",):
                        self._place(buf, o, self.kit["open"], 0.08, 0.3)
        for note in sec.notes:
            o = note.bar * bar_n + swing(note.step)
            n = max(int(step_n * note.length * 0.97), int(0.06 * SR))
            f = midi_hz(note.midi)
            if note.vowel and en["voice"] and st.vocal:
                sig = vowel_voice(f, note.vowel, n + int(0.05 * SR)) * adsr(n + int(0.05 * SR), 0.03, 0.06, 0.85, 0.07)
                self._place(buf, o, sig, 0.20 * en["voice"], 0.0, st.echo * 0.7)
                self._place(buf, o, osc(st.lead, f, n) * adsr(n, 0.01, 0.1, 0.5, 0.06), 0.05)
            elif note.vowel is None and en["lead"]:
                env = adsr(n, 0.008, 0.12, 0.45 if st.lead != "sine" else 0.8, 0.08)
                self._place(buf, o, osc(st.lead, f, n) * env, 0.17 * en["lead"], -0.2, st.echo)
                if en["dbl"]:
                    self._place(buf, o, osc("triangle", f * 2, n) * env, 0.07 * en["lead"], 0.2, st.echo)
        return buf


@register
class ProceduralBackend(ModelBackend):
    id = "procedural"
    name = "Procedural music (no AI) - BETA"
    description = ("BETA. Builds a song from rules: the seed and your style words pick tempo, scale, chords, drums and instruments; "
                   "your lyrics (with [verse]/[chorus] tags) set the structure and a robotic vowel voice follows every line. "
                   "Instant, offline, any PC or phone, nothing to download or scan. It sounds like a game score or synth track, "
                   "not a band, and the voice does not pronounce real words.")
    needs_model = False
    uses_gpu = False
    beta = True
    streams_whole_song = True
    max_segment_seconds = 7200
    can_switch_device_live = True

    def __init__(self):
        self._loaded = False

    def load(self, params: GenParams, model_path=None) -> None:
        self._loaded = True

    @property
    def loaded(self) -> bool:
        return self._loaded

    def unload(self) -> None:
        self._loaded = False

    def plan(self, req: SegmentRequest) -> Plan:
        return plan_song(req.prompt, req.lyrics, float(req.duration), int(req.seed))

    def stream_song(self, req: SegmentRequest, params: GenParams, progress, cancelled):
        """Yields SegmentResult blocks (one per section) that concatenate to exactly the requested duration."""
        plan = self.plan(req)
        r = Renderer(plan)
        total = int(round(plan.duration * SR))
        tail = int((plan.spb + 1.0) * SR)
        carry = None
        emitted = 0
        for i, sec in enumerate(plan.sections):
            if cancelled():
                raise Cancelled()
            buf = r.section(sec, tail)
            if carry is not None:
                buf[:len(carry)] += carry
            n = buf.shape[0] - tail
            carry = buf[n:].copy()
            out = buf[:n]
            if i == len(plan.sections) - 1:                  # fade out the last two bars
                fade = min(n, int(2 * plan.spb * SR))
                out[n - fade:] *= np.linspace(1, 0, fade, dtype=np.float32)[:, None]
            out = np.tanh(out * 1.1) * 0.9
            out = out[:max(0, total - emitted)]
            emitted += len(out)
            progress((i + 1) / len(plan.sections))
            yield SegmentResult(out.astype(np.float32), SR)
        if emitted < total:                                  # rounding: pad silence to the exact length
            yield SegmentResult(np.zeros((total - emitted, 2), np.float32), SR)

    def generate_segment(self, req, params, progress, cancelled):
        blocks = [b.audio for b in self.stream_song(req, params, progress, cancelled)]
        return SegmentResult(np.concatenate(blocks), SR)
