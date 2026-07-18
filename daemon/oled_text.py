"""Text safety helpers for the ASCII-only OLED font."""
from __future__ import annotations


def ascii_oled_text(value: object) -> str:
    text = str(value)
    return "".join(
        character if character == "\n" or " " <= character <= "~" else "?"
        for character in text
    )
