#!/usr/bin/env python3
"""Static checks for Morse romaji composition planning design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    backlog = (ROOT / "docs" / "feature/design-todo-backlog.md").read_text(encoding="utf-8")
    wishlist_path = ROOT / "docs" / "WISHLIST.md"
    status_path = ROOT / "docs" / "CURRENT_STATUS.md"
    wishlist = wishlist_path.read_text(encoding="utf-8") if wishlist_path.is_file() else None
    status = status_path.read_text(encoding="utf-8") if status_path.is_file() else None

    required = [
        "Morse romaji composition planning design",
        "touch flick composition plan",
        "read-only `romaji_us_ime`",
        "host IME owner",
        "`MORSE(name)` の runtime は 1 sequence = 1 action",
        "fallback / force_commit / feedback",
        "Vial import-export",
        "実機なしで coverage と blocking reason",
        "実送信は touch flick composition と同じく",
    ]
    for phrase in required:
        assert phrase in backlog, phrase

    assert "### Morse romaji composition planning design" in backlog
    if wishlist is not None:
        assert "Morse 入力によるローマ字入力補助は、touch flick composition plan と同じ read-only `romaji_us_ime` 境界で整理できるため、2026-06-04 に設計TODOへ昇格済みです。" in wishlist
        assert "| W3 | Morse 入力によるローマ字入力補助 |" not in wishlist
        assert "| W3 | 和文モールス入力 |" in wishlist
    if status is not None:
        assert "Morse romaji / touch-panel / IME / named text" in status

    print("ok: Morse romaji composition design is promoted from wishlist to TODO")


if __name__ == "__main__":
    main()
