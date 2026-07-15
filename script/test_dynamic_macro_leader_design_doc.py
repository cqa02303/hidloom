#!/usr/bin/env python3
"""Static checks for Dynamic Macro / Leader design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "macro" / "dynamic-macro-leader-design.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")

    required_phrases = [
        "DYN_REC_START1",
        "DYN_MACRO_PLAY1",
        "LEADER",
        "runtime memory にだけ置く",
        "永続化しない",
        "output switch",
        "emergency release",
        "default disabled",
        "leader_pending",
        "最終 resolved action",
        "script / system / connectivity",
        "Autocorrect internal",
    ]
    for phrase in required_phrases:
        assert phrase in text, phrase
    print("ok: Dynamic Macro / Leader design keeps runtime state and cancel boundaries explicit")


if __name__ == "__main__":
    main()
