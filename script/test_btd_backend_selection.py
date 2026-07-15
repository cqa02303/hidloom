#!/usr/bin/env python3
"""Regression tests for btd backend selection."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from btd.backend import LoggingBackend  # noqa: E402
from btd.bluez_backend import BlueZAdvertisingMode, BlueZBackend, BlueZHidTransport  # noqa: E402
from btd.btd import build_backend  # noqa: E402
from btd.gatt_adapter import BlueZDbusGattRegistrationAdapter, DryRunGattRegistrationAdapter  # noqa: E402


def main() -> None:
    logging_backend = build_backend("logging")
    assert isinstance(logging_backend, LoggingBackend)

    bluez_backend = build_backend("bluez")
    assert isinstance(bluez_backend, BlueZBackend)
    assert bluez_backend.enabled is False
    assert bluez_backend.transport == BlueZHidTransport.BLE
    assert isinstance(bluez_backend.adapter, DryRunGattRegistrationAdapter)
    assert bluez_backend.status().advertising_adapter_kind == "dry-run"
    assert bluez_backend.advertising_mode == BlueZAdvertisingMode.PAIRING

    enabled_bluez_backend = build_backend("bluez", bluez_enable=True)
    assert isinstance(enabled_bluez_backend, BlueZBackend)
    assert enabled_bluez_backend.enabled is True

    monitored_backend = build_backend("bluez", disconnect_monitor_interval_sec=2.0)
    assert isinstance(monitored_backend, BlueZBackend)
    assert monitored_backend.disconnect_monitor_interval_sec == 2.0
    assert monitored_backend.disconnect_idle_monitor_interval_sec == 60.0

    idle_backoff_backend = build_backend(
        "bluez",
        advertising_monitor_interval_sec=1.0,
        advertising_idle_monitor_interval_sec=60.0,
        disconnect_monitor_interval_sec=2.0,
        disconnect_idle_monitor_interval_sec=60.0,
    )
    assert isinstance(idle_backoff_backend, BlueZBackend)
    assert idle_backoff_backend._advertising_monitor_sleep_interval() == 60.0
    assert idle_backoff_backend._disconnect_monitor_sleep_interval() == 60.0
    idle_backoff_backend._monitor_saw_connected_devices = True
    assert idle_backoff_backend._disconnect_monitor_sleep_interval() == 2.0

    stuck_reconnect_backend = build_backend(
        "bluez",
        stuck_reconnect_polls=3,
        stuck_reconnect_cooldown_sec=15.0,
    )
    assert isinstance(stuck_reconnect_backend, BlueZBackend)
    assert stuck_reconnect_backend.stuck_reconnect_polls == 3
    assert stuck_reconnect_backend.stuck_reconnect_cooldown_sec == 15.0

    bluez_dbus_backend = build_backend("bluez", gatt_adapter="bluez-dbus")
    assert isinstance(bluez_dbus_backend, BlueZBackend)
    assert isinstance(bluez_dbus_backend.adapter, BlueZDbusGattRegistrationAdapter)
    assert bluez_dbus_backend.status().advertising_adapter_kind == "bluez-dbus"

    secure_backend = build_backend("bluez", gatt_security="encrypt")
    assert isinstance(secure_backend, BlueZBackend)
    secure_report_map = secure_backend.application.services[0].characteristics[1]
    assert secure_report_map.flags == ("encrypt-read",)

    dry_advertising_backend = build_backend("bluez", gatt_adapter="bluez-dbus", advertising_adapter="dry-run")
    assert isinstance(dry_advertising_backend, BlueZBackend)
    assert dry_advertising_backend.status().advertising_adapter_kind == "dry-run"

    always_advertising_backend = build_backend("bluez", advertising_mode="always")
    assert isinstance(always_advertising_backend, BlueZBackend)
    assert always_advertising_backend.advertising_mode == BlueZAdvertisingMode.ALWAYS

    off_advertising_backend = build_backend("bluez", advertising_mode="off")
    assert isinstance(off_advertising_backend, BlueZBackend)
    assert off_advertising_backend.advertising_mode == BlueZAdvertisingMode.OFF

    pairing_backend = build_backend("bluez", pairing_adapter="bluetoothctl", pairing_mode=True)
    assert isinstance(pairing_backend, BlueZBackend)
    assert pairing_backend.pairing_mode is True
    assert pairing_backend.status().pairing_adapter_kind == "bluetoothctl"
    assert pairing_backend.status().pairing_mode_enabled is False

    custom_pairing_backend = build_backend(
        "bluez",
        pairing_adapter="bluetoothctl",
        pairing_agent_capability="NoInputNoOutput",
        pairing_mode=True,
    )
    assert isinstance(custom_pairing_backend, BlueZBackend)
    assert custom_pairing_backend.status().pairing_adapter_kind == "bluetoothctl"
    assert custom_pairing_backend.status().pairing_agent_capability == "NoInputNoOutput"

    try:
        build_backend("unknown")
    except ValueError as exc:
        assert "unknown backend" in str(exc)
    else:
        raise AssertionError("unknown backend should fail")

    try:
        build_backend("bluez", advertising_mode="invalid")
    except ValueError as exc:
        assert "invalid BlueZ advertising mode" in str(exc)
    else:
        raise AssertionError("invalid advertising mode should fail")

    try:
        build_backend("bluez", gatt_adapter="invalid")
    except ValueError as exc:
        assert "unknown GATT adapter kind" in str(exc)
    else:
        raise AssertionError("invalid GATT adapter should fail")

    print("ok: btd backend selection")


if __name__ == "__main__":
    main()
