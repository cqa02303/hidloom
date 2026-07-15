#!/usr/bin/env python3
"""Regression checks for the btd protocol document."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    doc = (ROOT / "docs" / "daemon" / "specs" / "btd" / "socket-protocol.md").read_text(encoding="utf-8")

    for required in [
        "`btd1`",
        "`0x01`",
        "`0x02`",
        "`0x03`",
        "`0x04`",
        "Keyboard HID report",
        "Mouse HID report",
        "Consumer Control HID report",
        "Control message",
        "legacy raw 8-byte keyboard report",
        "Consumer Control は socket protocol / runtime 経路を実装済み",
        "BTD_CONSUMER_CONTROL=1",
        "Report ID 3",
    ]:
        assert required in doc, required

    assert "Mouse / Consumer report の protocol 決定" not in doc
    assert "Mouse / Consumer / Status framing は未導入" not in doc
    assert "現在も socket protocol は report type header を持たず" not in doc
    print("ok: btd protocol document is current")


if __name__ == "__main__":
    main()
