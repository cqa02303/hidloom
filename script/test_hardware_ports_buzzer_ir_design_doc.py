#!/usr/bin/env python3
"""Static checks for hardware ports / buzzer / IR design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "hardware" / "hardware-ports-buzzer-ir-design.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")

    required_phrases = [
        "hardware_ports",
        "buzzer_pwm",
        "ir_tx",
        "default は disabled",
        "pin reservation",
        "pin overlap",
        "max_duty",
        "max_duration_ms",
        "carrier_hz",
        "output switch",
        "emergency release",
        "hardware がない時は daemon を起動しない",
        "HTTP から pin number を直接指定して即時操作しない",
    ]
    for phrase in required_phrases:
        assert phrase in text, phrase
    print("ok: hardware ports / buzzer / IR design keeps pin reservation and stop boundaries explicit")


if __name__ == "__main__":
    main()
