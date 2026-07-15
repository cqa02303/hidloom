#!/usr/bin/env python3
"""Watch Bluetooth reconnect state for the production btd service."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from dataclasses import dataclass


DEFAULT_DEVICE = "14:35:B7:EF:AB:72"
DEFAULT_URL = "https://localhost/api/status"
RESET_MARKERS = (
    "BlueZ GATT keyboard input reset to null report",
    "BlueZ connected device monitor saw disconnect",
    "reset_keyboard_null=True",
)


@dataclass(frozen=True)
class BtSnapshot:
    connected: bool | None
    paired: bool | None
    bonded: bool | None
    trusted: bool | None
    services_resolved: bool | None
    status_connected_count: int
    status_paired_count: int


def run_text(command: list[str], *, timeout: float = 5.0) -> str:
    try:
        proc = subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)
    except Exception as exc:
        return f"{command[0]} failed: {exc}"
    return (proc.stdout + proc.stderr).strip()


def parse_bt_bool(text: str, field_name: str) -> bool | None:
    m = re.search(rf"^\s*{re.escape(field_name)}:\s*(yes|no)\s*$", text, re.MULTILINE | re.IGNORECASE)
    if not m:
        return None
    return m.group(1).lower() == "yes"


def count_status_devices(status_text: str, field_name: str) -> int:
    try:
        data = json.loads(status_text)
    except json.JSONDecodeError:
        return 0
    bluetooth = data.get("bluetooth") or {}
    devices = bluetooth.get(field_name) or []
    return len(devices) if isinstance(devices, list) else 0


def read_snapshot(device: str, status_url: str, auth: str) -> BtSnapshot:
    info = run_text(["bluetoothctl", "info", device], timeout=5.0)
    status = run_text(["curl", "-ks", "-u", auth, status_url], timeout=5.0)
    return BtSnapshot(
        connected=parse_bt_bool(info, "Connected"),
        paired=parse_bt_bool(info, "Paired"),
        bonded=parse_bt_bool(info, "Bonded"),
        trusted=parse_bt_bool(info, "Trusted"),
        services_resolved=parse_bt_bool(info, "ServicesResolved"),
        status_connected_count=count_status_devices(status, "connected_devices"),
        status_paired_count=count_status_devices(status, "paired_devices"),
    )


def format_snapshot(snapshot: BtSnapshot) -> str:
    fields = (
        f"connected={snapshot.connected}",
        f"paired={snapshot.paired}",
        f"bonded={snapshot.bonded}",
        f"trusted={snapshot.trusted}",
        f"services_resolved={snapshot.services_resolved}",
        f"api_connected={snapshot.status_connected_count}",
        f"api_paired={snapshot.status_paired_count}",
    )
    return " ".join(fields)


def journal_since(since_epoch: int) -> str:
    return run_text(["journalctl", "-u", "btd", f"--since=@{since_epoch}", "--no-pager", "-l"], timeout=8.0)


def count_reset_markers(log_text: str) -> int:
    return sum(log_text.count(marker) for marker in RESET_MARKERS)


def main() -> None:
    parser = argparse.ArgumentParser(description="Watch production Bluetooth reconnect state.")
    parser.add_argument("--device", default=DEFAULT_DEVICE)
    parser.add_argument("--duration", type=float, default=90.0)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--status-url", default=DEFAULT_URL)
    parser.add_argument("--auth", default="admin:admin")
    args = parser.parse_args()

    start = int(time.time())
    deadline = time.monotonic() + max(1.0, args.duration)
    last_line = ""
    transitions: list[str] = []
    print("Watching Bluetooth reconnect state.")
    print("Toggle the host Bluetooth off/on while this is running.")
    while time.monotonic() < deadline:
        snapshot = read_snapshot(args.device, args.status_url, args.auth)
        line = format_snapshot(snapshot)
        if line != last_line:
            stamp = time.strftime("%H:%M:%S")
            print(f"{stamp} {line}", flush=True)
            transitions.append(line)
            last_line = line
        time.sleep(max(0.5, args.interval))

    logs = journal_since(start)
    reset_count = count_reset_markers(logs)
    final = read_snapshot(args.device, args.status_url, args.auth)
    print("\n== summary ==")
    print(f"transitions={len(transitions)} reset_markers={reset_count}")
    print(f"final {format_snapshot(final)}")
    if final.connected is True and final.bonded is True and final.trusted is True:
        print("result=connected_bonded_trusted")
    else:
        print("result=needs_attention")


if __name__ == "__main__":
    main()
