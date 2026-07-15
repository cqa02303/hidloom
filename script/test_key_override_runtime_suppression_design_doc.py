#!/usr/bin/env python3
"""Static checks for Key Override runtime suppression design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "keycode" / "key-override-runtime-suppression-design.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")
    required_phrases = [
        "suppressed source action",
        "replacement press",
        "replacement release",
        "Mod-Morph",
        "Repeat Key history",
        "output switch",
        "emergency release",
        "save payload",
    ]
    for phrase in required_phrases:
        assert phrase in text, phrase
    print("ok: Key Override runtime suppression design keeps press/release and priority boundaries explicit")


if __name__ == "__main__":
    main()
