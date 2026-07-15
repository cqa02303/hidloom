#!/usr/bin/env python3
"""Static checks for MIDI sequencer / audio integration design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "midi" / "sequencer-audio-integration-design.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")

    required_phrases = [
        "SEQ_PLAY(name)",
        "SEQ_STOP",
        "SEQ_TOGGLE(name)",
        "/mnt/p3/sequences/midi/<name>.json",
        "versioned JSON",
        "max_duration_ms",
        "default disabled",
        "output switch",
        "emergency release",
        "all notes off",
        "backend-specific descriptor / GPIO / ALSA device を直接触らない",
        "daemon restart で自動再生しない",
    ]
    for phrase in required_phrases:
        assert phrase in text, phrase
    print("ok: MIDI sequencer / audio integration design keeps sequence storage and stop boundaries explicit")


if __name__ == "__main__":
    main()
