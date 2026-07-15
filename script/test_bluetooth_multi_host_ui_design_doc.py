#!/usr/bin/env python3
"""Static checks for Bluetooth multi-host operation UI design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "bluetooth" / "multi-host-ui-design.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")

    required_phrases = [
        "read-only host list",
        "active host",
        "last connected",
        "notify_ready",
        "forget host",
        "confirmation 必須",
        "HTTP から BlueZ を直接操作しない",
        "audit log",
        "host profile metadata は read-only merge",
        "forget しても profile config を自動削除しない",
    ]
    for phrase in required_phrases:
        assert phrase in text, phrase
    print("ok: Bluetooth multi-host UI design keeps host operation boundaries explicit")


if __name__ == "__main__":
    main()
