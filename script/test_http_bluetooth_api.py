#!/usr/bin/env python3
"""Smoke tests for HTTP Bluetooth control helpers."""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon" / "http"))
sys.path.insert(0, str(ROOT))

from bluetooth_api import (  # noqa: E402
    build_bluetooth_host_forget_guard,
    normalize_bluetooth_address,
    normalize_pairing_mode,
    rename_bluetooth_host_metadata,
    run_forget_action,
    run_pairing_action,
    update_bluetooth_host_observation_metadata,
    validate_bluetooth_display_name,
)


async def main_async() -> None:
    assert normalize_pairing_mode(True) == "on"
    assert normalize_pairing_mode(False) == "off"
    assert normalize_pairing_mode("toggle") == "toggle"
    try:
        normalize_pairing_mode("bad")
    except ValueError as exc:
        assert "pairing mode" in str(exc)
    else:
        raise AssertionError("invalid pairing mode should fail")

    commands: list[dict] = []

    async def send_ok(cmd: dict):
        commands.append(cmd)
        return {"t": "BT", "result": "ok", "action": cmd["action"]}

    result = await run_pairing_action(send_ok, "on")
    assert result == {"result": "ok", "mode": "on", "action": "BT_PAIRING_ON"}
    assert commands[-1] == {"t": "BT", "action": "BT_PAIRING_ON"}

    result = await run_pairing_action(send_ok, False)
    assert result["action"] == "BT_PAIRING_OFF"

    commands.clear()
    result = await run_forget_action(send_ok)
    assert result["result"] == "ok"
    assert result["actions"] == ["BT_PAIRING_OFF", "BT_DISCONNECT", "BT_FORGET_DEVICE"]
    assert commands == [
        {"t": "BT", "action": "BT_PAIRING_OFF"},
        {"t": "BT", "action": "BT_DISCONNECT"},
        {"t": "BT", "action": "BT_FORGET_DEVICE"},
    ]

    async def send_none(_cmd: dict):
        return None

    assert (await run_pairing_action(send_none, "toggle"))["result"] == "error"
    assert (await run_forget_action(send_none))["result"] == "error"

    assert normalize_bluetooth_address("aa:bb:cc:dd:ee:ff") == "AA:BB:CC:DD:EE:FF"
    try:
        normalize_bluetooth_address("bad")
    except ValueError as exc:
        assert "Bluetooth address" in str(exc)
    else:
        raise AssertionError("invalid bluetooth address should fail")

    assert validate_bluetooth_display_name("  Work laptop  ") == "Work laptop"
    assert validate_bluetooth_display_name("", clear=True) == ""
    for bad in ("", "bad\nname", "x" * 65):
        try:
            validate_bluetooth_display_name(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid display name should fail: {bad!r}")

    with tempfile.TemporaryDirectory() as tmpdir:
        hosts_path = Path(tmpdir) / "bluetooth_hosts.json"
        hosts_path.write_text(
            json.dumps({
                "version": 1,
                "hosts": {
                    "aa:bb:cc:dd:ee:ff": {
                        "last_connected_at": "2026-06-01T00:00:00+00:00",
                        "last_connected_source": "fixture",
                    }
                },
            }),
            encoding="utf-8",
        )
        result = rename_bluetooth_host_metadata(hosts_path, "aa:bb:cc:dd:ee:ff", "Work laptop")
        assert result["result"] == "ok"
        assert result["address"] == "AA:BB:CC:DD:EE:FF"
        assert result["display_name"] == "Work laptop"
        assert result["source"] == "local_metadata"
        stored = json.loads(hosts_path.read_text(encoding="utf-8"))
        host = stored["hosts"]["AA:BB:CC:DD:EE:FF"]
        assert host["display_name"] == "Work laptop"
        assert host["last_connected_source"] == "fixture"

        dry = update_bluetooth_host_observation_metadata(
            hosts_path,
            "AA:BB:CC:DD:EE:FF",
            last_seen_name="Desk phone",
            last_connected_at="2026-06-10T12:34:56+09:00",
            last_connected_source="btd_notify_ready",
            dry_run=True,
        )
        assert dry["dry_run"] is True
        assert dry["preserved_display_name"] == "Work laptop"
        stored_after_dry = json.loads(hosts_path.read_text(encoding="utf-8"))
        assert stored_after_dry["hosts"]["AA:BB:CC:DD:EE:FF"]["last_connected_source"] == "fixture"

        observed = update_bluetooth_host_observation_metadata(
            hosts_path,
            "AA:BB:CC:DD:EE:FF",
            last_seen_name="Desk phone",
            last_connected_at="2026-06-10T12:34:56+09:00",
            last_connected_source="btd_notify_ready",
        )
        assert observed["result"] == "ok"
        assert observed["preserved_display_name"] == "Work laptop"
        stored = json.loads(hosts_path.read_text(encoding="utf-8"))
        host = stored["hosts"]["AA:BB:CC:DD:EE:FF"]
        assert host["display_name"] == "Work laptop"
        assert host["last_seen_name"] == "Desk phone"
        assert host["last_connected_at"] == "2026-06-10T12:34:56+09:00"
        assert host["last_connected_source"] == "btd_notify_ready"

        cleared = rename_bluetooth_host_metadata(hosts_path, "AA:BB:CC:DD:EE:FF", "", clear=True)
        assert cleared["cleared"] is True
        stored = json.loads(hosts_path.read_text(encoding="utf-8"))
        assert "display_name" not in stored["hosts"]["AA:BB:CC:DD:EE:FF"]

        guard = build_bluetooth_host_forget_guard(
            "aa:bb:cc:dd:ee:ff",
            {"confirm_address": "AA:BB:CC:DD:EE:FF", "dry_run": True},
            device={"paired": True, "connected": True},
        )
        assert guard["result"] == "dry_run"
        assert guard["single_address_only"] is True
        assert guard["connected_warning"] is True
        assert guard["command_plan"] == [
            {"t": "BT", "action": "BT_FORGET_HOST", "address": "AA:BB:CC:DD:EE:FF"}
        ]
        try:
            build_bluetooth_host_forget_guard(
                "AA:BB:CC:DD:EE:FF",
                {"confirm_address": "11:22:33:44:55:66", "dry_run": True},
            )
        except ValueError as exc:
            assert "confirm_address" in str(exc)
        else:
            raise AssertionError("mismatched confirm address should fail")
        try:
            build_bluetooth_host_forget_guard(
                "AA:BB:CC:DD:EE:FF",
                {"confirm_address": "AA:BB:CC:DD:EE:FF", "dry_run": False},
            )
        except ValueError as exc:
            assert "disabled until real-device" in str(exc)
        else:
            raise AssertionError("non-dry-run per-host forget should remain disabled")

    print("ok: HTTP Bluetooth API helpers")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
