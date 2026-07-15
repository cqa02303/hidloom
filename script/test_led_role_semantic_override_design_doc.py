#!/usr/bin/env python3
"""Static checks for LED role semantic override design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "lighting" / "led-role-semantic-override-design.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")
    required_phrases = [
        "role_overrides",
        "manual override",
        "auto role inspector",
        "known semantic role",
        "preview override は runtime-only",
        "restore path",
        "manual override が auto role より優先される",
        "effect state と semantic role",
    ]
    for phrase in required_phrases:
        assert phrase in text, phrase
    print("ok: LED role semantic override design keeps role/save/preview boundaries explicit")


if __name__ == "__main__":
    main()
