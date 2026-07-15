#!/usr/bin/env python3
"""Smoke tests for the Bluetooth reconnect watch helper."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.bt_reconnect_watch import (  # noqa: E402
    BtSnapshot,
    count_reset_markers,
    count_status_devices,
    format_snapshot,
    parse_bt_bool,
)


def main() -> None:
    info = "Name: iPhone\nPaired: yes\nBonded: yes\nTrusted: no\nConnected: yes\n"
    assert parse_bt_bool(info, "Paired") is True
    assert parse_bt_bool(info, "Trusted") is False
    assert parse_bt_bool(info, "ServicesResolved") is None
    status = '{"bluetooth":{"connected_devices":["AA"],"paired_devices":["AA","BB"]}}'
    assert count_status_devices(status, "connected_devices") == 1
    assert count_status_devices(status, "paired_devices") == 2
    assert count_status_devices("not json", "paired_devices") == 0
    snapshot = BtSnapshot(
        connected=True,
        paired=True,
        bonded=True,
        trusted=True,
        services_resolved=None,
        status_connected_count=1,
        status_paired_count=1,
    )
    line = format_snapshot(snapshot)
    assert "connected=True" in line
    assert "api_connected=1" in line
    assert count_reset_markers("reset_keyboard_null=True\nBlueZ connected device monitor saw disconnect") == 2
    print("ok: Bluetooth reconnect watch helper")


if __name__ == "__main__":
    main()
