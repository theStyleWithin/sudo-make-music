"""The one-phrase "command box" under the lyrics.

It is NOT a terminal: the text is only ever compared with COMMAND and is never executed, parsed or passed to a
shell. Matching the phrase just presses "Generate"; anything else is ignored.
"""
COMMAND = "sudo make music"


def is_command(text: str) -> bool:
    """True for the phrase typed with any capitalisation / extra spaces around the words."""
    return " ".join(text.split()).lower() == COMMAND


def allowed_input(substring: str) -> str:
    """Keystroke filter for the box: letters and spaces only (nothing a shell would treat specially)."""
    return "".join(ch for ch in substring if ch.isalpha() or ch == " ")
