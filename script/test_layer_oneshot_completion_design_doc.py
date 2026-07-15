#!/usr/bin/env python3
"""Static checks for Layer / one-shot completion design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "keycode" / "layer-oneshot-completion-design.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")
    required_phrases = ["OSL(n)", "OSM(mod)", "TT(n)", "LT(n,kc)", "LayerManager", "transient state", "zero report", "save payload"]
    for phrase in required_phrases:
        assert phrase in text, phrase
    print("ok: Layer / one-shot completion design keeps transient state boundaries explicit")


if __name__ == "__main__":
    main()
