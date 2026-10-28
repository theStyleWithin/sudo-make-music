"""Make stdout/stderr safe BEFORE Kivy is imported.

A windowed Windows exe (no console) has no usable stdout/stderr: they are None, or exist but raise on write.
Kivy then adds a console log handler that writes to the stderr that Kivy itself replaced with a logger,
and `import kivy` dies with "RecursionError: maximum recursion depth exceeded". Turning off Kivy's console
logging and giving Python harmless streams avoids it. Logs still go to Kivy's log file.
"""
from __future__ import annotations

import os
import sys


def _usable(stream) -> bool:
    if stream is None:
        return False
    try:
        stream.write("")
        stream.flush()
        return True
    except Exception:
        return False


def ensure_std_streams() -> bool:
    """Returns True if any stream had to be replaced (and Kivy console logging was switched off)."""
    replaced = False
    for name in ("stdout", "stderr"):
        if not _usable(getattr(sys, name, None)):
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
            replaced = True
    if replaced or getattr(sys, "frozen", False):
        os.environ.setdefault("KIVY_NO_CONSOLELOG", "1")
    return replaced
