"""Split typed text into sentence-sized chunks for speech backends."""
from __future__ import annotations

import re

_SENT = re.compile(r"(?<=[.!?\u3002\uff01\uff1f])\s+|\n+")


def split_text(text: str, max_chars: int = 240) -> list[str]:
    parts = [p.strip() for p in _SENT.split(text.strip()) if p and p.strip()]
    out: list[str] = []
    for p in parts:
        while len(p) > max_chars:                      # very long sentence: cut at a comma/space
            cut = max(p.rfind(",", 0, max_chars), p.rfind(" ", 0, max_chars))
            cut = cut if cut > max_chars // 3 else max_chars
            out.append(p[:cut].strip(" ,"))
            p = p[cut:].strip(" ,")
        if p:
            out.append(p)
    merged: list[str] = []
    for p in out:                                      # glue short neighbours so we do not synthesize fragments
        if merged and len(merged[-1]) + len(p) + 1 <= max_chars // 2:
            merged[-1] += " " + p
        else:
            merged.append(p)
    return merged
