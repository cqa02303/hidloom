#!/usr/bin/env python3
"""Static checks for matrixd scanner abstraction design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = (
    ROOT
    / "docs"
    / "daemon"
    / "specs"
    / "matrixd"
    / "scanner-abstraction-design.md"
)


def main() -> None:
    text = DOC.read_text(encoding="utf-8")

    required_phrases = [
        "scanner.h",
        "scanner_charlieplex.c",
        "scanner_rowcol.c",
        "matrix_event_t",
        "type\": \"charlieplex\"",
        "type\": \"row_column\"",
        "diode_direction",
        "logicd` は scanner type を知らない",
        "Vial keymap protocol は scanner type に依存しない",
        "charlieplex` default",
        "scanner type を変えても `logicd` event format が変わらない",
    ]
    for phrase in required_phrases:
        assert phrase in text, phrase
    print("ok: matrixd scanner abstraction design keeps scanner type out of logicd/Vial")


if __name__ == "__main__":
    main()
