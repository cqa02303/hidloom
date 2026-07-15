#!/usr/bin/env python3
"""Regression checks for active Bluetooth and pointing-device docs."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ACTIVE_DOCS = [
    "docs/daemon/specs/btd/socket-protocol.md",
    "docs/bluetooth/ble-gatt-hid-spec.md",
    "docs/bluetooth/implementation-plan.md",
    "docs/bluetooth/hid-backend-plan.md",
    "docs/bluetooth/host-led-output-report-design.md",
    "docs/daemon/specs/spid/mouse-sensor-plan.md",
]

PRIVATE_WORKSPACE_DOCS = [
    "docs/CURRENT_STATUS.md",
    "docs/TODO_PRIORITY.md",
]

STALE_PHRASES = [
    "Mouse / Consumer",
    "Consumer Control / Mouse",
    "raw fixed 8-byte",
    "当面 raw fixed",
    "現時点では keyboard report のみ",
    "Mouse: 後回し",
    "OutputRouter / Bluetooth mouse report への統合は後回し",
    "Mouse / Consumer / Status framing は未導入",
    "report type header を持たず",
]


def main() -> None:
    docs = list(ACTIVE_DOCS)
    if (ROOT / "docs" / "CURRENT_STATUS.md").is_file():
        docs.extend(PRIVATE_WORKSPACE_DOCS)

    for rel in docs:
        text = (ROOT / rel).read_text(encoding="utf-8")
        for phrase in STALE_PHRASES:
            assert phrase not in text, f"{rel}: stale phrase remains: {phrase}"

    btd = (ROOT / "docs" / "daemon" / "specs" / "btd" / "socket-protocol.md").read_text(
        encoding="utf-8"
    )
    assert "`0x02` | 4 bytes | Mouse HID report" in btd
    assert "`0x04` | 2 bytes | Consumer Control HID report" in btd
    assert "Consumer Control は socket protocol / runtime 経路を実装済み" in btd
    assert "BTD_CONSUMER_CONTROL=1" in btd
    assert "legacy raw 8-byte keyboard report" in btd

    spid = (ROOT / "docs" / "daemon" / "specs" / "spid" / "mouse-sensor-plan.md").read_text(
        encoding="utf-8"
    )
    assert "btd BLE HID mouse" in spid
    assert "OutputRouter / Bluetooth mouse report への統合は実装済み" in spid

    print("ok: Bluetooth docs reflect current mouse/framed protocol state")


if __name__ == "__main__":
    main()
