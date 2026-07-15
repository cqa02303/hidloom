#!/usr/bin/env python3
"""Static checks for Vial advanced macro compatibility design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "macro" / "vial-advanced-macro-compatibility-design.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")

    required_phrases = [
        "settings.vial_macro_buffer",
        "expanded local macro",
        "raw Vial macro buffer",
        "raw buffer を実行 source にしない",
        "unsupported command warning",
        "KML / QMK macro keycode",
        "Dynamic Macro",
        "Send String",
        "Script editor",
        ".vil` round-trip",
        "system / connectivity / power action を自動変換しない",
    ]
    for phrase in required_phrases:
        assert phrase in text, phrase
    print("ok: Vial advanced macro compatibility design keeps raw buffer and runtime macro boundaries explicit")


if __name__ == "__main__":
    main()
