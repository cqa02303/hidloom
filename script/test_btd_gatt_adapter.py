#!/usr/bin/env python3
"""Regression tests for BLE HID GATT registration adapter boundary."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from btd.gatt_adapter import (  # noqa: E402
    BlueZDbusGattRegistrationAdapter,
    BlueZGattAdapterUnavailable,
    DryRunGattRegistrationAdapter,
    build_gatt_adapter,
    _input_null_value,
    _keyboard_input_null_value,
    _managed_objects,
)
from btd.gatt_app import build_hid_gatt_application  # noqa: E402
from btd.gatt_hid import BOOT_KEYBOARD_INPUT_REPORT_UUID, CONSUMER_INPUT_REPORT, HID_REPORT_UUID, KEYBOARD_INPUT_REPORT, KEYBOARD_OUTPUT_REPORT, MOUSE_INPUT_REPORT  # noqa: E402


class _FakeVariant:
    def __init__(self, signature: str, value: object) -> None:
        self.signature = signature
        self.value = value


async def main_async() -> None:
    adapter = DryRunGattRegistrationAdapter()
    report = bytes.fromhex("0000040000000000")

    # Before registration the adapter validates but does not record a notify.
    await adapter.notify_keyboard_report(report)
    status = adapter.status()
    assert status.registered is False
    assert status.notifications == 0
    assert status.last_report_hex == ""
    assert status.notifying is False
    assert status.adapter_kind == "dry-run"
    assert status.available is True

    app = build_hid_gatt_application("/com/example/hid")
    managed = _managed_objects(app, _FakeVariant)
    assert "/com/example/hid/service0000" in managed
    assert "/com/example/hid/service0001" in managed
    assert "/com/example/hid/service0002" in managed
    assert "org.bluez.GattService1" in managed["/com/example/hid/service0000"]
    service_props = managed["/com/example/hid/service0000"]["org.bluez.GattService1"]
    assert service_props["UUID"].signature == "s"
    assert service_props["Primary"].value is True
    assert service_props["Includes"].value == []
    notify_char_path = "/com/example/hid/service0000/char0004"
    assert "org.bluez.GattCharacteristic1" in managed[notify_char_path]
    notify_props = managed[notify_char_path]["org.bluez.GattCharacteristic1"]
    assert notify_props["Flags"].value == ["read", "notify"]
    assert notify_props["Value"].value == KEYBOARD_INPUT_REPORT.encode_value(bytes(8))
    output_char_path = "/com/example/hid/service0000/char0005"
    assert "org.bluez.GattCharacteristic1" in managed[output_char_path]
    output_props = managed[output_char_path]["org.bluez.GattCharacteristic1"]
    assert output_props["Flags"].value == ["read", "write", "write-without-response"]
    assert output_props["Value"].value == KEYBOARD_OUTPUT_REPORT.encode_value(bytes(1))
    mouse_char_path = "/com/example/hid/service0000/char0006"
    assert "org.bluez.GattCharacteristic1" in managed[mouse_char_path]
    mouse_props = managed[mouse_char_path]["org.bluez.GattCharacteristic1"]
    assert mouse_props["Flags"].value == ["read", "notify"]
    assert mouse_props["Value"].value == MOUSE_INPUT_REPORT.encode_value(bytes(4))
    boot_char_path = "/com/example/hid/service0000/char0007"
    assert "org.bluez.GattCharacteristic1" in managed[boot_char_path]
    boot_props = managed[boot_char_path]["org.bluez.GattCharacteristic1"]
    assert boot_props["Flags"].value == ["read", "notify"]
    assert boot_props["Value"].value == bytes(8)
    boot_output_char_path = "/com/example/hid/service0000/char0008"
    assert "org.bluez.GattCharacteristic1" in managed[boot_output_char_path]
    boot_output_props = managed[boot_output_char_path]["org.bluez.GattCharacteristic1"]
    assert boot_output_props["Flags"].value == ["read", "write", "write-without-response"]
    assert boot_output_props["Value"].value == bytes(1)
    battery_char_path = "/com/example/hid/service0002/char0000"
    assert managed[battery_char_path]["org.bluez.GattCharacteristic1"]["Value"].value == bytes([100])

    consumer_app = build_hid_gatt_application("/com/example/consumer", include_consumer=True)
    consumer_managed = _managed_objects(consumer_app, _FakeVariant)
    consumer_char_path = "/com/example/consumer/service0000/char0007"
    assert "org.bluez.GattCharacteristic1" in consumer_managed[consumer_char_path]
    consumer_props = consumer_managed[consumer_char_path]["org.bluez.GattCharacteristic1"]
    assert consumer_props["Flags"].value == ["read", "notify"]
    assert consumer_props["Value"].value == CONSUMER_INPUT_REPORT.encode_value(bytes(2))

    await adapter.register_application(app)
    assert adapter.status().registered is True
    assert adapter.application.path == "/com/example/hid"

    await adapter.notify_keyboard_report(report)
    status = adapter.status()
    assert status.registered is True
    assert status.notifications == 1
    assert status.last_report_hex == report.hex()

    await adapter.notify_keyboard_report(bytes(8))
    status = adapter.status()
    assert status.notifications == 2
    assert status.last_report_hex == bytes(8).hex()

    await adapter.notify_mouse_report(bytes.fromhex("0001ff00"))
    status = adapter.status()
    assert status.notifications == 3
    assert status.last_report_hex == "0001ff00"

    await adapter.notify_consumer_report(bytes.fromhex("e900"))
    status = adapter.status()
    assert status.notifications == 4
    assert status.last_report_hex == "e900"

    try:
        await adapter.notify_keyboard_report(bytes(7))
    except ValueError as exc:
        assert "8 bytes" in str(exc)
    else:
        raise AssertionError("invalid payload size should fail")

    await adapter.unregister_application()
    assert adapter.status().registered is False

    assert isinstance(build_gatt_adapter(), DryRunGattRegistrationAdapter)
    assert isinstance(build_gatt_adapter("dry-run"), DryRunGattRegistrationAdapter)
    assert isinstance(build_gatt_adapter("bluez-dbus"), BlueZDbusGattRegistrationAdapter)
    assert _keyboard_input_null_value(HID_REPORT_UUID) == KEYBOARD_INPUT_REPORT.encode_value(bytes(8))
    assert _keyboard_input_null_value(BOOT_KEYBOARD_INPUT_REPORT_UUID) == bytes(8)
    assert _keyboard_input_null_value("00002a19-0000-1000-8000-00805f9b34fb") is None
    default_service = app.services[0]
    default_reports = [characteristic for characteristic in default_service.characteristics if characteristic.uuid == HID_REPORT_UUID]
    assert _input_null_value(default_reports[0]) == KEYBOARD_INPUT_REPORT.encode_value(bytes(8))
    assert _input_null_value(default_reports[2]) == MOUSE_INPUT_REPORT.encode_value(bytes(4))
    consumer_service = consumer_app.services[0]
    consumer_reports = [characteristic for characteristic in consumer_service.characteristics if characteristic.uuid == HID_REPORT_UUID]
    assert _input_null_value(consumer_reports[3]) == CONSUMER_INPUT_REPORT.encode_value(bytes(2))

    dbus_reset_adapter = BlueZDbusGattRegistrationAdapter(dependency_name="sys")
    class _FakeCharacteristic:
        def __init__(self, notifying: bool = True) -> None:
            self.notifying = notifying
            self.value = b""
            self.changed: list[dict[str, object]] = []

        def update_value(self, value: bytes) -> None:
            self.value = bytes(value)

        def emit_properties_changed(self, changed: dict[str, object]) -> None:
            self.changed.append(changed)

    input_char = _FakeCharacteristic(notifying=True)
    boot_char = _FakeCharacteristic(notifying=True)
    mouse_char = _FakeCharacteristic(notifying=True)
    consumer_char = _FakeCharacteristic(notifying=True)
    dbus_reset_adapter._keyboard_characteristics = [
        (HID_REPORT_UUID, input_char),
        (BOOT_KEYBOARD_INPUT_REPORT_UUID, boot_char),
    ]
    dbus_reset_adapter._mouse_characteristics = [mouse_char]
    dbus_reset_adapter._consumer_characteristics = [consumer_char]
    await dbus_reset_adapter.reset_keyboard_input()
    await dbus_reset_adapter.reset_mouse_input()
    await dbus_reset_adapter.reset_consumer_input()
    assert input_char.value == KEYBOARD_INPUT_REPORT.encode_value(bytes(8))
    assert boot_char.value == bytes(8)
    assert mouse_char.value == MOUSE_INPUT_REPORT.encode_value(bytes(4))
    assert consumer_char.value == CONSUMER_INPUT_REPORT.encode_value(bytes(2))
    assert input_char.notifying is False
    assert boot_char.notifying is False
    assert dbus_reset_adapter.status().last_report_hex == bytes(2).hex()

    dbus_adapter = BlueZDbusGattRegistrationAdapter(dependency_name="definitely_missing_dbus_module")
    dbus_status = dbus_adapter.status()
    assert dbus_status.adapter_kind == "bluez-dbus"
    assert dbus_status.notifying is False
    assert dbus_status.available is False
    assert "not installed" in dbus_status.error
    try:
        await dbus_adapter.register_application(app)
    except BlueZGattAdapterUnavailable as exc:
        assert "not installed" in str(exc)
    else:
        raise AssertionError("missing D-Bus dependency should fail explicitly")

    try:
        build_gatt_adapter("invalid")
    except ValueError as exc:
        assert "unknown GATT adapter kind" in str(exc)
    else:
        raise AssertionError("invalid adapter kind should fail")

    print("ok: btd GATT registration adapter")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
