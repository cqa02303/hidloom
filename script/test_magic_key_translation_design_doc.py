#!/usr/bin/env python3
"""Static checks for Magic key translation design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "keycode" / "magic-key-translation-design.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")
    required_phrases = [
        "MAGIC_SWAP_CONTROL_CAPSLOCK",
        "MAGIC_TOGGLE_DEBUG",
        "MAGIC_TOGGLE_NKRO",
        "no-op + warning",
        "persistent setting",
        "host profile",
        "EEPROM reset",
    ]
    for phrase in required_phrases:
        assert phrase in text, phrase
    print("ok: Magic key translation design keeps QMK compatibility and Pi runtime boundaries explicit")


if __name__ == "__main__":
    main()
