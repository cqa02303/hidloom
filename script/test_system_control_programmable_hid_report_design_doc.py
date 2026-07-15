#!/usr/bin/env python3
"""Static checks for System control / programmable HID report design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "hid" / "system-control-programmable-hid-report-design.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")
    required_phrases = [
        "KC_SYSTEM_POWER",
        "Programmable HID",
        "default disabled",
        "arbitrary byte report",
        "named report",
        "allowlist",
        "audit log",
        "Vial Raw HID",
    ]
    for phrase in required_phrases:
        assert phrase in text, phrase
    print("ok: System control / programmable HID report design keeps report boundaries explicit")


if __name__ == "__main__":
    main()
