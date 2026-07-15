#!/usr/bin/env python3
"""Regression tests for BLE HID over GATT constants."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from btd.gatt_hid import (  # noqa: E402
    BATTERY_LEVEL_UUID,
    BATTERY_SERVICE_UUID,
    BOOT_KEYBOARD_INPUT_REPORT_UUID,
    BOOT_KEYBOARD_OUTPUT_REPORT_UUID,
    CLIENT_CHARACTERISTIC_CONFIGURATION_UUID,
    CONSUMER_GATT_REPORT_VALUE_SIZE,
    CONSUMER_INPUT_REPORT,
    CONSUMER_INPUT_REPORT_ID,
    CONSUMER_INPUT_REPORT_SIZE,
    DEFAULT_BATTERY_LEVEL,
    DEVICE_INFORMATION_SERVICE_UUID,
    HID_INFORMATION,
    HID_INFORMATION_UUID,
    HID_PROTOCOL_MODE_UUID,
    HID_REPORT_MAP_UUID,
    HID_REPORT_UUID,
    HID_SERVICE_UUID,
    KEYBOARD_INPUT_REPORT,
    KEYBOARD_INPUT_REPORT_ID,
    KEYBOARD_INPUT_REPORT_SIZE,
    KEYBOARD_GATT_REPORT_VALUE_SIZE,
    KEYBOARD_OUTPUT_REPORT,
    KEYBOARD_OUTPUT_REPORT_ID,
    KEYBOARD_OUTPUT_REPORT_SIZE,
    KEYBOARD_REPORT_MAP,
    MANUFACTURER_NAME,
    MANUFACTURER_NAME_UUID,
    MODEL_NUMBER,
    MODEL_NUMBER_UUID,
    MOUSE_GATT_REPORT_VALUE_SIZE,
    MOUSE_INPUT_REPORT,
    MOUSE_INPUT_REPORT_ID,
    MOUSE_INPUT_REPORT_SIZE,
    PNP_ID,
    PNP_ID_UUID,
    REPORT_REFERENCE_DESCRIPTOR_UUID,
    REPORT_TYPE_INPUT,
    REPORT_TYPE_OUTPUT,
    build_pnp_id,
    hid_report_map,
    validate_keyboard_report_payload,
    validate_consumer_report_payload,
    validate_mouse_report_payload,
)
from btd.protocol import CONSUMER_REPORT_SIZE, KEYBOARD_REPORT_SIZE, MOUSE_REPORT_SIZE, parse_raw_consumer_report, parse_raw_keyboard_report, parse_raw_mouse_report  # noqa: E402


def main() -> None:
    assert HID_SERVICE_UUID.startswith("00001812")
    assert HID_INFORMATION_UUID.startswith("00002a4a")
    assert HID_REPORT_MAP_UUID.startswith("00002a4b")
    assert HID_REPORT_UUID.startswith("00002a4d")
    assert HID_PROTOCOL_MODE_UUID.startswith("00002a4e")
    assert BOOT_KEYBOARD_INPUT_REPORT_UUID.startswith("00002a22")
    assert BOOT_KEYBOARD_OUTPUT_REPORT_UUID.startswith("00002a32")
    assert REPORT_REFERENCE_DESCRIPTOR_UUID.startswith("00002908")
    assert CLIENT_CHARACTERISTIC_CONFIGURATION_UUID.startswith("00002902")
    assert DEVICE_INFORMATION_SERVICE_UUID.startswith("0000180a")
    assert MANUFACTURER_NAME_UUID.startswith("00002a29")
    assert MODEL_NUMBER_UUID.startswith("00002a24")
    assert PNP_ID_UUID.startswith("00002a50")
    assert BATTERY_SERVICE_UUID.startswith("0000180f")
    assert BATTERY_LEVEL_UUID.startswith("00002a19")

    assert len(HID_INFORMATION) == 4
    assert MANUFACTURER_NAME == b"HIDloom"
    assert MODEL_NUMBER
    assert PNP_ID == bytes([0x02, 0x6B, 0x1D, 0x05, 0x01, 0x01, 0x00])
    assert build_pnp_id(0x1209, 0x484C) == bytes([0x02, 0x09, 0x12, 0x4C, 0x48, 0x01, 0x00])
    for invalid in (-1, 0x10000):
        try:
            build_pnp_id(invalid, 0x0105)
        except ValueError:
            pass
        else:
            raise AssertionError("out-of-range PnP ID should fail")
    assert DEFAULT_BATTERY_LEVEL == bytes([100])
    assert KEYBOARD_INPUT_REPORT_ID == 1
    assert KEYBOARD_OUTPUT_REPORT_ID == 1
    assert KEYBOARD_INPUT_REPORT_SIZE == KEYBOARD_REPORT_SIZE == 8
    assert MOUSE_INPUT_REPORT_ID == 2
    assert MOUSE_INPUT_REPORT_SIZE == MOUSE_REPORT_SIZE == 4
    assert MOUSE_GATT_REPORT_VALUE_SIZE == 4
    assert CONSUMER_INPUT_REPORT_ID == 3
    assert CONSUMER_INPUT_REPORT_SIZE == CONSUMER_REPORT_SIZE == 2
    assert CONSUMER_GATT_REPORT_VALUE_SIZE == 2
    assert KEYBOARD_OUTPUT_REPORT_SIZE == 1
    assert KEYBOARD_GATT_REPORT_VALUE_SIZE == 8
    assert KEYBOARD_INPUT_REPORT.report_type == REPORT_TYPE_INPUT
    assert KEYBOARD_INPUT_REPORT.report_reference == bytes([1, REPORT_TYPE_INPUT])
    assert KEYBOARD_INPUT_REPORT.value_size == 8
    assert KEYBOARD_INPUT_REPORT.encode_value(bytes.fromhex("0000040000000000")) == bytes.fromhex("0000040000000000")
    assert KEYBOARD_OUTPUT_REPORT.report_type == REPORT_TYPE_OUTPUT
    assert KEYBOARD_OUTPUT_REPORT.report_reference == bytes([1, REPORT_TYPE_OUTPUT])
    assert KEYBOARD_OUTPUT_REPORT.value_size == 1
    assert KEYBOARD_OUTPUT_REPORT.encode_value(bytes([0x02])) == bytes([0x02])
    assert MOUSE_INPUT_REPORT.report_type == REPORT_TYPE_INPUT
    assert MOUSE_INPUT_REPORT.report_reference == bytes([2, REPORT_TYPE_INPUT])
    assert MOUSE_INPUT_REPORT.value_size == 4
    assert MOUSE_INPUT_REPORT.encode_value(bytes.fromhex("0001ff00")) == bytes.fromhex("0001ff00")
    assert CONSUMER_INPUT_REPORT.report_type == REPORT_TYPE_INPUT
    assert CONSUMER_INPUT_REPORT.report_reference == bytes([3, REPORT_TYPE_INPUT])
    assert CONSUMER_INPUT_REPORT.value_size == 2
    assert CONSUMER_INPUT_REPORT.encode_value(bytes.fromhex("e900")) == bytes.fromhex("e900")

    # Report Reference descriptors and Report Map should agree on Report ID 1.
    assert bytes([0x85, 0x01]) in KEYBOARD_REPORT_MAP
    assert bytes([0x85, 0x02]) in KEYBOARD_REPORT_MAP
    assert bytes([0x85, 0x03]) not in KEYBOARD_REPORT_MAP
    assert bytes([0x05, 0x0C]) not in KEYBOARD_REPORT_MAP
    assert bytes([0x95, 0x06]) in KEYBOARD_REPORT_MAP
    assert bytes([0x26, 0xFF, 0x00]) in KEYBOARD_REPORT_MAP
    assert bytes([0x2A, 0xFF, 0x00]) in KEYBOARD_REPORT_MAP
    assert bytes([0x25, 0x65]) not in KEYBOARD_REPORT_MAP
    assert bytes([0x29, 0x65]) not in KEYBOARD_REPORT_MAP
    assert bytes([0x05, 0x08]) in KEYBOARD_REPORT_MAP
    assert bytes([0x91, 0x02]) in KEYBOARD_REPORT_MAP
    assert KEYBOARD_REPORT_MAP[-1] == 0xC0
    consumer_map = hid_report_map(include_consumer=True)
    assert consumer_map.startswith(KEYBOARD_REPORT_MAP)
    assert bytes([0x85, 0x03]) in consumer_map
    assert bytes([0x05, 0x0C]) in consumer_map

    report = parse_raw_keyboard_report(bytes.fromhex("0000040000000000"))
    validate_keyboard_report_payload(report.report)
    validate_keyboard_report_payload(bytes(8))
    mouse_report = parse_raw_mouse_report(bytes.fromhex("0001ff00"))
    validate_mouse_report_payload(mouse_report.report)
    validate_mouse_report_payload(bytes(4))
    consumer_report = parse_raw_consumer_report(bytes.fromhex("e900"))
    validate_consumer_report_payload(consumer_report.report)
    validate_consumer_report_payload(bytes(2))

    try:
        validate_keyboard_report_payload(bytes(7))
    except ValueError as exc:
        assert "8 bytes" in str(exc)
    else:
        raise AssertionError("short payload should fail")

    try:
        validate_keyboard_report_payload(bytes(9))
    except ValueError as exc:
        assert "8 bytes" in str(exc)
    else:
        raise AssertionError("long payload should fail")

    try:
        validate_mouse_report_payload(bytes(3))
    except ValueError as exc:
        assert "4 bytes" in str(exc)
    else:
        raise AssertionError("short mouse payload should fail")

    try:
        validate_consumer_report_payload(bytes(1))
    except ValueError as exc:
        assert "2 bytes" in str(exc)
    else:
        raise AssertionError("short consumer payload should fail")

    print("ok: btd BLE GATT HID constants")


if __name__ == "__main__":
    main()
