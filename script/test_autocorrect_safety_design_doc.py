#!/usr/bin/env python3
"""Static checks for Autocorrect safety design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "input" / "autocorrect-safety-design.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")

    required_phrases = [
        "enabled=false",
        '"settings"',
        '"autocorrect"',
        "ASCII lower-case word correction",
        "host layout 自動判定",
        "Unicode replacement",
        "InteractionEngine",
        "AutocorrectEngine",
        "Send String runner",
        "dictionary validation",
        "Repeat Key",
        "Caps Word",
        "output switch",
        "config reload",
        "emergency release",
        "read-only validation / dictionary preview",
        "runtime first slice",
        "logicd/autocorrect.py",
        "AutocorrectRuntime",
        "validate_autocorrect_settings()",
        "script/test_autocorrect_runtime.py",
        "Send String storage と Autocorrect dictionary を混ぜない",
    ]
    for phrase in required_phrases:
        assert phrase in text, phrase
    print("ok: Autocorrect safety design keeps core boundaries explicit")


if __name__ == "__main__":
    main()
