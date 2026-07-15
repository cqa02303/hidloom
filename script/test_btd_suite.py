#!/usr/bin/env python3
"""Run all btd-related smoke tests."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "script"))

from suite_runner import run_suite  # noqa: E402

TESTS = (
    "script/test_btd_protocol.py",
    "script/test_btd_backend.py",
    "script/test_btd_bluez_backend.py",
    "script/test_btd_bluez_dbus_plan.py",
    "script/test_btd_backend_selection.py",
    "script/test_btd_gatt_hid.py",
    "script/test_btd_gatt_app.py",
    "script/test_btd_gatt_adapter.py",
    "script/test_btd_advertising.py",
    "script/test_btd_pairing.py",
    "script/test_btd_pairing_window_tool.py",
    "script/test_btd_service_file.py",
    "script/test_btd_socket_boundary.py",
)


def main() -> None:
    run_suite("all btd tests", TESTS)


if __name__ == "__main__":
    main()
