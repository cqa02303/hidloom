#!/usr/bin/env python3
"""Static checks for Digitizer / Haptic / Steno feature design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "hid" / "digitizer-haptic-steno-feature-design.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")
    required_phrases = [
        "Digitizer",
        "Haptic",
        "Steno",
        "default disabled",
        "HID descriptor",
        "board profile",
        "steno mode",
        "emergency release",
        "raw report",
    ]
    for phrase in required_phrases:
        assert phrase in text, phrase
    print("ok: Digitizer / Haptic / Steno design keeps large feature dependencies explicit")


if __name__ == "__main__":
    main()
