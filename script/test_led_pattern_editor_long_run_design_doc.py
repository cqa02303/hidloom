#!/usr/bin/env python3
"""Static checks for LED pattern editor / long-run metrics design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "lighting" / "led-long-run-metrics.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")
    required_phrases = [
        "Pattern editor boundary",
        "pattern",
        "splash",
        "reactive",
        "semantic role override",
        "Preview / restore policy",
        "brightness ceiling",
        "timeout",
        "/mnt/p3/led_pattern_editor.json",
        "config/default/ledd.json",
        "drafts",
        "accepted FPS",
        "applied FPS",
        "dropped frames",
        "thermal reading",
        "human observation note",
    ]
    for phrase in required_phrases:
        assert phrase in text, phrase
    print("ok: LED pattern editor / long-run metrics design keeps preview and metrics boundaries explicit")


if __name__ == "__main__":
    main()
