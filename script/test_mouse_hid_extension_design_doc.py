#!/usr/bin/env python3
"""Static checks for Mouse HID extension design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "hid" / "mouse-hid-extension-design.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")
    required_phrases = ["KC_BTN1", "KC_WH_U", "MS_LEFT", "Drag Lock", "PAW3805EK", "mouse zero report", "source 分離", "System panel"]
    for phrase in required_phrases:
        assert phrase in text, phrase
    print("ok: Mouse HID extension design keeps report owner and source boundaries explicit")


if __name__ == "__main__":
    main()
