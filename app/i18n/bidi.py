"""Bidi-safe "label: value" lines for Persian messages.

A Persian line is a right-to-left label followed by a left-to-right
value (a username, a password, a date). Telegram clients resolve each
line's direction from its content, and with a Latin/digit value they can
lay the value out on the wrong side or align the whole line to the left.
Two invisible marks prevent that:

- RLM at the start pins the line as right-to-left, so it stays
  right-aligned whatever the value contains;
- FSI … PDI isolates the value, so its own direction cannot reorder the
  label or the colon around it.

The marks go OUTSIDE any <code> span, so tap-to-copy copies the bare
value. English lines need neither and get none.
"""

from __future__ import annotations

RLM = "‏"
FSI = "⁨"
PDI = "⁩"


def info_line(label: str, value_html: str, lang: str) -> str:
    if lang != "fa":
        return f"{label}: {value_html}"
    return f"{RLM}{label}: {FSI}{value_html}{PDI}"
