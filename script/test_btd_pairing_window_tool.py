#!/usr/bin/env python3
"""Regression tests for the BLE HID pairing window helper."""
from __future__ import annotations

import tempfile
import os
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.btd_bluez_pairing_window import (  # noqa: E402
    A_PRESS,
    A_RELEASE,
    DIGIT_USAGE,
    ENTER_TAP,
    NOTIFY_STARTED_MARKER,
    build_btd_env,
    device_addresses,
    digit_report,
    format_device_info,
    log_contains,
    run_text,
    tail_log,
    write_passkey_file,
)


def main() -> None:
    old_agent = os.environ.get("BTD_PAIRING_AGENT")
    os.environ.pop("BTD_PAIRING_AGENT", None)
    env = build_btd_env("/tmp/example-btd.sock")
    if old_agent is not None:
        os.environ["BTD_PAIRING_AGENT"] = old_agent
    assert env["BTD_EVENTS_SOCK"] == "/tmp/example-btd.sock"
    assert env["BTD_BACKEND"] == "bluez"
    assert env["BTD_BLUEZ_ENABLE"] == "1"
    assert env["BTD_GATT_ADAPTER"] == "bluez-dbus"
    assert env["BTD_GATT_SECURITY"] == "none"
    assert env["BTD_ADVERTISING_ADAPTER"] == "bluez-dbus"
    assert env["BTD_ADVERTISING_MODE"] == "pairing"
    assert env["BTD_PAIRING_MODE"] == "1"
    assert env["BTD_PAIRING_ADAPTER"] == "bluetoothctl"
    assert env["BTD_PAIRING_AGENT"] == "KeyboardOnly"
    assert env["BTD_PAIRING_PASSKEY_FILE"] == "/tmp/btd_pairing_passkey.txt"
    assert env["BTD_STATUS_INTERVAL"] == "5"
    custom_env = build_btd_env("/tmp/example-btd.sock", "/tmp/custom-passkey.txt")
    assert custom_env["BTD_PAIRING_PASSKEY_FILE"] == "/tmp/custom-passkey.txt"
    assert A_PRESS.hex() == "0000040000000000"
    assert A_RELEASE == bytes(8)
    assert ENTER_TAP.hex() == "0000280000000000"
    assert DIGIT_USAGE["1"] == 0x1E
    assert DIGIT_USAGE["0"] == 0x27
    assert digit_report("1").hex() == "00001e0000000000"
    assert digit_report("0").hex() == "0000270000000000"
    try:
        digit_report("x")
    except ValueError as exc:
        assert "unsupported passkey digit" in str(exc)
    else:
        raise AssertionError("invalid passkey digit should fail")
    assert device_addresses("Device AA:BB:CC:DD:EE:FF Phone\nDevice 11:22:33:44:55:66 Host") == {
        "AA:BB:CC:DD:EE:FF",
        "11:22:33:44:55:66",
    }
    assert device_addresses("(none)") == set()
    formatted = format_device_info(
        {
            "Address": "AA:BB:CC:DD:EE:FF",
            "Name": "Phone",
            "Paired": "no",
            "Connected": "yes",
            "ServicesResolved": "no",
        }
    )
    assert "Address=AA:BB:CC:DD:EE:FF" in formatted
    assert "Paired=no" in formatted
    assert "Connected=yes" in formatted
    assert "ServicesResolved=no" in formatted

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "pairing.log"
        path.write_text("one\ntwo\nthree\n")
        assert tail_log(str(path), lines=2) == "two\nthree"
        assert log_contains(str(path), "two") is True
        assert log_contains(str(path), NOTIFY_STARTED_MARKER) is False
        path.write_text(f"before\n{NOTIFY_STARTED_MARKER} characteristic=/x\n")
        assert log_contains(str(path), NOTIFY_STARTED_MARKER) is True
        assert "does not exist" in tail_log(str(Path(tmp) / "missing.log"))
        assert log_contains(str(Path(tmp) / "missing.log"), "anything") is False
        passkey_path = Path(tmp) / "passkey.txt"
        write_passkey_file(str(passkey_path), "654321")
        assert passkey_path.read_text() == "654321"
        try:
            write_passkey_file(str(passkey_path), "12ab")
        except ValueError as exc:
            assert "passkey must contain only digits" in str(exc)
        else:
            raise AssertionError("invalid passkey should fail")

    assert run_text(["true"]) == ""
    assert "exited" in run_text(["false"])

    tool_text = (ROOT / "tools" / "btd_bluez_pairing_window.py").read_text()
    assert "--poll-interval" in tool_text
    assert "--gatt-security" in tool_text
    assert "--type-passkey" in tool_text
    assert "--send-passkey" in tool_text
    assert "default=2.0" in tool_text
    assert "connected_hint_printed" in tool_text

    print("ok: btd pairing window helper")


if __name__ == "__main__":
    main()
