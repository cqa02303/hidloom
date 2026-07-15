#!/usr/bin/env python3
"""Static checks for PAW3805EK mounted cursor / settings UI design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "hardware" / "paw3805ek-mounted-cursor-settings-design.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")

    required_phrases = [
        "type\": \"paw3805ek\"",
        "owner\": \"spid\"",
        "spid` は起動しない",
        "orientation",
        "rotation",
        "axis_swap",
        "invert_x",
        "logicd cursor transform",
        "mouse HID report",
        "raw sensor register editor は作らない",
        "mouse zero report",
        "sensor failure が keyboard output を止めない",
    ]
    for phrase in required_phrases:
        assert phrase in text, phrase
    print("ok: PAW3805EK mounted cursor design keeps daemon/spid/logicd/settings boundaries explicit")


if __name__ == "__main__":
    main()
