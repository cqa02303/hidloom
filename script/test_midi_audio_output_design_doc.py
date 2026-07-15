#!/usr/bin/env python3
"""Static checks for MIDI / Audio output design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "midi" / "audio-output-design.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")

    required_phrases = [
        "USB MIDI gadget",
        "ALSA MIDI",
        "Pi audio",
        "PWM buzzer",
        "MIDI_NOTE(n)",
        "AUDIO_TONE(name)",
        "default disabled",
        "volume",
        "timeout",
        "output switch",
        "emergency release",
        "USB_MIDI=1",
        "HID keyboard / mouse / raw HID",
        "board profile pin reservation",
    ]
    for phrase in required_phrases:
        assert phrase in text, phrase
    print("ok: MIDI / Audio output design keeps backend, volume, and stop boundaries explicit")


if __name__ == "__main__":
    main()
