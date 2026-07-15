#!/usr/bin/env python3
"""Regression tests for side-effect-free BLE HID GATT application model."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from btd.gatt_app import DEFAULT_APP_PATH, build_hid_gatt_application, normalize_gatt_security  # noqa: E402
from btd.gatt_hid import (  # noqa: E402
    BATTERY_LEVEL_UUID,
    BATTERY_SERVICE_UUID,
    BOOT_KEYBOARD_INPUT_REPORT_UUID,
    BOOT_KEYBOARD_OUTPUT_REPORT_UUID,
    CLIENT_CHARACTERISTIC_CONFIGURATION_UUID,
    CONSUMER_INPUT_REPORT,
    DEFAULT_BATTERY_LEVEL,
    DEVICE_INFORMATION_SERVICE_UUID,
    HID_CONTROL_POINT_UUID,
    HID_INFORMATION,
    HID_INFORMATION_UUID,
    HID_PROTOCOL_MODE_UUID,
    HID_REPORT_MAP_UUID,
    HID_REPORT_UUID,
    HID_SERVICE_UUID,
    KEYBOARD_INPUT_REPORT,
    KEYBOARD_OUTPUT_REPORT,
    KEYBOARD_REPORT_MAP,
    MANUFACTURER_NAME,
    MANUFACTURER_NAME_UUID,
    MODEL_NUMBER,
    MODEL_NUMBER_UUID,
    MOUSE_INPUT_REPORT,
    PNP_ID,
    PNP_ID_UUID,
    REPORT_REFERENCE_DESCRIPTOR_UUID,
    REPORT_TYPE_INPUT,
    REPORT_TYPE_OUTPUT,
)


def main() -> None:
    assert DEFAULT_APP_PATH == "/org/hidloom/btd"
    app = build_hid_gatt_application()
    assert app.path == DEFAULT_APP_PATH
    assert len(app.services) == 3

    service = app.services[0]
    assert service.path == f"{DEFAULT_APP_PATH}/service0000"
    assert service.uuid == HID_SERVICE_UUID
    assert service.primary is True
    assert len(service.characteristics) == 9

    by_uuid = {characteristic.uuid: characteristic for characteristic in service.characteristics if characteristic.uuid != HID_REPORT_UUID}
    report_characteristics = [characteristic for characteristic in service.characteristics if characteristic.uuid == HID_REPORT_UUID]
    assert by_uuid[HID_INFORMATION_UUID].flags == ("read",)
    assert by_uuid[HID_INFORMATION_UUID].value == HID_INFORMATION
    assert by_uuid[HID_REPORT_MAP_UUID].flags == ("read",)
    assert by_uuid[HID_REPORT_MAP_UUID].value == KEYBOARD_REPORT_MAP
    assert by_uuid[HID_CONTROL_POINT_UUID].flags == ("write-without-response",)
    assert by_uuid[HID_PROTOCOL_MODE_UUID].value == bytes([0x01])

    assert len(report_characteristics) == 3
    input_report = next(
        characteristic
        for characteristic in report_characteristics
        if _report_reference_value(characteristic) == bytes([1, REPORT_TYPE_INPUT])
    )
    assert input_report.flags == ("read", "notify")
    assert input_report.value == KEYBOARD_INPUT_REPORT.encode_value(bytes(KEYBOARD_INPUT_REPORT.payload_size))
    assert len(input_report.descriptors) == 2

    desc_by_uuid = {descriptor.uuid: descriptor for descriptor in input_report.descriptors}
    assert desc_by_uuid[REPORT_REFERENCE_DESCRIPTOR_UUID].value == KEYBOARD_INPUT_REPORT.report_reference
    assert desc_by_uuid[CLIENT_CHARACTERISTIC_CONFIGURATION_UUID].value == bytes([0x00, 0x00])
    output_report = next(
        characteristic
        for characteristic in report_characteristics
        if _report_reference_value(characteristic) == bytes([1, REPORT_TYPE_OUTPUT])
    )
    assert output_report.flags == ("read", "write", "write-without-response")
    assert output_report.value == KEYBOARD_OUTPUT_REPORT.encode_value(bytes(KEYBOARD_OUTPUT_REPORT.payload_size))
    assert len(output_report.descriptors) == 1
    assert output_report.descriptors[0].uuid == REPORT_REFERENCE_DESCRIPTOR_UUID
    mouse_report = next(
        characteristic
        for characteristic in report_characteristics
        if _report_reference_value(characteristic) == bytes([2, REPORT_TYPE_INPUT])
    )
    assert mouse_report.flags == ("read", "notify")
    assert mouse_report.value == MOUSE_INPUT_REPORT.encode_value(bytes(MOUSE_INPUT_REPORT.payload_size))
    assert len(mouse_report.descriptors) == 2
    assert not any(
        _report_reference_value(characteristic) == bytes([3, REPORT_TYPE_INPUT])
        for characteristic in report_characteristics
    )

    boot_input_report = by_uuid[BOOT_KEYBOARD_INPUT_REPORT_UUID]
    assert boot_input_report.flags == ("read", "notify")
    assert boot_input_report.value == bytes(KEYBOARD_INPUT_REPORT.payload_size)
    assert boot_input_report.descriptors[0].uuid == CLIENT_CHARACTERISTIC_CONFIGURATION_UUID
    boot_output_report = by_uuid[BOOT_KEYBOARD_OUTPUT_REPORT_UUID]
    assert boot_output_report.flags == ("read", "write", "write-without-response")
    assert boot_output_report.value == bytes(KEYBOARD_OUTPUT_REPORT.payload_size)

    paths = app.object_paths()
    assert paths[0] == DEFAULT_APP_PATH
    assert service.path in paths
    assert input_report.path in paths
    assert desc_by_uuid[REPORT_REFERENCE_DESCRIPTOR_UUID].path in paths
    device_information = app.services[1]
    assert device_information.path == f"{DEFAULT_APP_PATH}/service0001"
    assert device_information.uuid == DEVICE_INFORMATION_SERVICE_UUID
    dis_by_uuid = {characteristic.uuid: characteristic for characteristic in device_information.characteristics}
    assert dis_by_uuid[MANUFACTURER_NAME_UUID].value == MANUFACTURER_NAME
    assert dis_by_uuid[MODEL_NUMBER_UUID].value == MODEL_NUMBER
    assert dis_by_uuid[PNP_ID_UUID].value == PNP_ID

    battery = app.services[2]
    assert battery.path == f"{DEFAULT_APP_PATH}/service0002"
    assert battery.uuid == BATTERY_SERVICE_UUID
    battery_level = battery.characteristics[0]
    assert battery_level.uuid == BATTERY_LEVEL_UUID
    assert battery_level.flags == ("read", "notify")
    assert battery_level.value == DEFAULT_BATTERY_LEVEL
    assert battery_level.descriptors[0].uuid == CLIENT_CHARACTERISTIC_CONFIGURATION_UUID

    assert len(paths) == 1 + 3 + 14 + 6

    custom = build_hid_gatt_application("/com/example/test")
    assert custom.services[0].path == "/com/example/test/service0000"

    consumer_app = build_hid_gatt_application("/com/example/consumer", include_consumer=True)
    consumer_service = consumer_app.services[0]
    consumer_reports = [characteristic for characteristic in consumer_service.characteristics if characteristic.uuid == HID_REPORT_UUID]
    consumer_report = next(
        characteristic
        for characteristic in consumer_reports
        if _report_reference_value(characteristic) == bytes([3, REPORT_TYPE_INPUT])
    )
    assert consumer_report.flags == ("read", "notify")
    assert consumer_report.value == CONSUMER_INPUT_REPORT.encode_value(bytes(CONSUMER_INPUT_REPORT.payload_size))
    assert len(consumer_report.descriptors) == 2
    assert len(consumer_service.characteristics) == 10

    encrypted = build_hid_gatt_application("/com/example/secure", security="encrypt")
    secure_by_uuid = {characteristic.uuid: characteristic for characteristic in encrypted.services[0].characteristics if characteristic.uuid != HID_REPORT_UUID}
    secure_reports = [characteristic for characteristic in encrypted.services[0].characteristics if characteristic.uuid == HID_REPORT_UUID]
    assert secure_by_uuid[HID_REPORT_MAP_UUID].flags == ("encrypt-read",)
    secure_input = next(
        characteristic
        for characteristic in secure_reports
        if _report_reference_value(characteristic) == bytes([1, REPORT_TYPE_INPUT])
    )
    assert secure_input.flags == ("encrypt-read", "notify", "encrypt-notify")
    assert normalize_gatt_security(None) == "none"
    assert normalize_gatt_security("authenticated") == "authenticated"
    try:
        normalize_gatt_security("bad")
    except ValueError as exc:
        assert "invalid GATT security mode" in str(exc)
    else:
        raise AssertionError("invalid GATT security mode should fail")

    print("ok: btd BLE GATT application model")


def _report_reference_value(characteristic) -> bytes:
    for descriptor in characteristic.descriptors:
        if descriptor.uuid == REPORT_REFERENCE_DESCRIPTOR_UUID:
            return descriptor.value
    return b""


if __name__ == "__main__":
    main()
