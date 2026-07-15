#!/usr/bin/env python3
"""Static checks for USB host identity / keymap hot swap design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "connectivity" / "usb-host-identity-keymap-hot-swap-design.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")
    required_phrases = [
        "USB host identity は初期実装では自動判定しない",
        "manual host profile selection",
        "full keymap swap",
        "初期対象外",
        "zero report",
        "transient state clear",
        "failed swap rollback",
        "Vial save / unlock 中に swap しない",
    ]
    for phrase in required_phrases:
        assert phrase in text, phrase
    print("ok: USB host identity / keymap hot swap design keeps identity and rollback boundaries explicit")


if __name__ == "__main__":
    main()
