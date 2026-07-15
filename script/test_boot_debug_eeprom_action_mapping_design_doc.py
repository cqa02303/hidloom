#!/usr/bin/env python3
"""Static checks for Boot / Debug / EEPROM action mapping design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "keycode" / "boot-debug-eeprom-action-mapping-design.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")
    required_phrases = [
        "QK_BOOT",
        "RESET",
        "EEP_RST",
        "destructive reset は confirmation required",
        "Pi bootloader",
        "audit log",
        "reset scope",
        "default disabled",
    ]
    for phrase in required_phrases:
        assert phrase in text, phrase
    print("ok: Boot / Debug / EEPROM action mapping design keeps destructive actions explicit")


if __name__ == "__main__":
    main()
