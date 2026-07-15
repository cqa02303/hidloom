#!/usr/bin/env python3
"""Static checks for Lighting key alias compatibility design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "lighting" / "lighting-key-alias-compatibility-design.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")
    required_phrases = ["RGB_TOG", "RGB_MATRIX", "BL_TOGG", "canonicalize", "unknown alias", "Vial custom keycode 64", "restore path", "semantic role override"]
    for phrase in required_phrases:
        assert phrase in text, phrase
    print("ok: Lighting key alias compatibility design keeps alias/effect/role boundaries explicit")


if __name__ == "__main__":
    main()
