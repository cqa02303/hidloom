#!/usr/bin/env python3
"""Static checks for QMK alias completion design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "keycode" / "qmk-alias-completion-design.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")
    required_phrases = [
        "canonical action",
        "KC_ENT",
        "KC_LCTRL",
        "QK_LAYER_LOCK",
        "RGB_TOG",
        "QK_BOOT",
        "unknown alias warning",
        "custom action 64",
    ]
    for phrase in required_phrases:
        assert phrase in text, phrase
    print("ok: QMK alias completion design keeps canonical alias boundaries explicit")


if __name__ == "__main__":
    main()
