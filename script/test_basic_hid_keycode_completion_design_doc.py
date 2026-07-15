#!/usr/bin/env python3
"""Static checks for Basic HID keycode completion design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "keycode" / "basic-hid-keycode-completion-design.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")
    required_phrases = [
        "KC_A",
        "QMK alias",
        "USB HID usage",
        "Linux input keycode",
        "HTTP picker",
        "Vial import/export",
        "side-effect-free",
        "host layout",
    ]
    for phrase in required_phrases:
        assert phrase in text, phrase
    print("ok: Basic HID keycode completion design keeps canonical HID boundaries explicit")


if __name__ == "__main__":
    main()
