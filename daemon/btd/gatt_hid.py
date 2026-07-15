"""BLE HID over GATT constants used by the btd BlueZ backend.

The GATT registration adapter imports this tested boundary for UUIDs, report
metadata, and Device Information values.

Design constraints:
- Preserve legacy raw fixed 8-byte keyboard reports while supporting framed
  keyboard and mouse reports.
- The BLE keyboard Input Report payload must match btd.protocol.KeyboardReport.report.
- The BLE mouse Input Report payload must match btd.protocol.MouseReport.report.
"""
from __future__ import annotations

from dataclasses import dataclass
import os

from .protocol import CONSUMER_REPORT_SIZE, KEYBOARD_REPORT_SIZE, MOUSE_REPORT_SIZE

# Standard GATT / HID UUIDs used by HID over GATT Profile.
HID_SERVICE_UUID = "00001812-0000-1000-8000-00805f9b34fb"
HID_INFORMATION_UUID = "00002a4a-0000-1000-8000-00805f9b34fb"
HID_REPORT_MAP_UUID = "00002a4b-0000-1000-8000-00805f9b34fb"
HID_CONTROL_POINT_UUID = "00002a4c-0000-1000-8000-00805f9b34fb"
HID_REPORT_UUID = "00002a4d-0000-1000-8000-00805f9b34fb"
HID_PROTOCOL_MODE_UUID = "00002a4e-0000-1000-8000-00805f9b34fb"
BOOT_KEYBOARD_INPUT_REPORT_UUID = "00002a22-0000-1000-8000-00805f9b34fb"
BOOT_KEYBOARD_OUTPUT_REPORT_UUID = "00002a32-0000-1000-8000-00805f9b34fb"
REPORT_REFERENCE_DESCRIPTOR_UUID = "00002908-0000-1000-8000-00805f9b34fb"
CLIENT_CHARACTERISTIC_CONFIGURATION_UUID = "00002902-0000-1000-8000-00805f9b34fb"
DEVICE_INFORMATION_SERVICE_UUID = "0000180a-0000-1000-8000-00805f9b34fb"
MANUFACTURER_NAME_UUID = "00002a29-0000-1000-8000-00805f9b34fb"
MODEL_NUMBER_UUID = "00002a24-0000-1000-8000-00805f9b34fb"
PNP_ID_UUID = "00002a50-0000-1000-8000-00805f9b34fb"
BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"
BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"

# Report Reference descriptor type values.
REPORT_TYPE_INPUT = 0x01
REPORT_TYPE_OUTPUT = 0x02
REPORT_TYPE_FEATURE = 0x03

# HOGP hosts identify Report characteristics through Report Reference
# descriptors.  Use an explicit report ID in the map/descriptor while keeping
# the GATT Report value itself as the 8-byte keyboard payload.
KEYBOARD_INPUT_REPORT_ID = 1
KEYBOARD_OUTPUT_REPORT_ID = 1
MOUSE_INPUT_REPORT_ID = 2
CONSUMER_INPUT_REPORT_ID = 3
KEYBOARD_INPUT_REPORT_SIZE = KEYBOARD_REPORT_SIZE
MOUSE_INPUT_REPORT_SIZE = MOUSE_REPORT_SIZE
CONSUMER_INPUT_REPORT_SIZE = CONSUMER_REPORT_SIZE
KEYBOARD_OUTPUT_REPORT_SIZE = 1
KEYBOARD_GATT_REPORT_VALUE_SIZE = KEYBOARD_REPORT_SIZE
MOUSE_GATT_REPORT_VALUE_SIZE = MOUSE_REPORT_SIZE
CONSUMER_GATT_REPORT_VALUE_SIZE = CONSUMER_REPORT_SIZE
BOOT_KEYBOARD_INPUT_REPORT_SIZE = KEYBOARD_REPORT_SIZE
BOOT_KEYBOARD_OUTPUT_REPORT_SIZE = KEYBOARD_OUTPUT_REPORT_SIZE

# HID Information characteristic: bcdHID 1.11, country=not localized, flags=normally connectable.
HID_INFORMATION = bytes([0x11, 0x01, 0x00, 0x02])
MANUFACTURER_NAME = b"HIDloom"
MODEL_NUMBER = b"cqa02303v5"

def _env_u16(name: str, default: int) -> int:
    value = os.environ.get(name)
    parsed = default if value is None or value.strip() == "" else int(value, 0)
    if not 0 <= parsed <= 0xFFFF:
        raise ValueError(f"{name} must fit in 16 bits")
    return parsed


def build_pnp_id(vendor_id: int, product_id: int, product_version: int = 0x0001) -> bytes:
    """Build a USB-IF-source PnP ID characteristic in little-endian order."""
    values = (vendor_id, product_id, product_version)
    if any(not 0 <= value <= 0xFFFF for value in values):
        raise ValueError("PnP ID values must fit in 16 bits")
    return bytes(
        [
            0x02,
            vendor_id & 0xFF,
            (vendor_id >> 8) & 0xFF,
            product_id & 0xFF,
            (product_id >> 8) & 0xFF,
            product_version & 0xFF,
            (product_version >> 8) & 0xFF,
        ]
    )


# The active USB identity profile supplies these shared environment values.
# The defaults preserve the private development profile until pid.codes assigns
# the public profile; release readiness blocks that development VID.
PNP_ID = build_pnp_id(
    _env_u16("HIDLOOM_USB_VENDOR_ID", 0x1D6B),
    _env_u16("HIDLOOM_USB_PRODUCT_ID", 0x0105),
)
DEFAULT_BATTERY_LEVEL = bytes([100])

# HID Report Map for a boot-like 8-byte keyboard input report and a relative
# 4-byte mouse input report:
#   modifier: 1 byte
#   reserved: 1 byte
#   keys: 6 bytes
#   LED output: 1 byte
#   mouse: buttons, x, y, wheel
# This intentionally mirrors logicd.hid_report.HidState.build() and MouseState.
# The key array uses 8-bit Keyboard/Keypad usages.  Advertise the full
# 0x00-0xFF logical/usage range so BLE hosts accept JIS-specific keys such as
# Keyboard International4/5 (0x8A/0x8B) and LANG1/2 (0x90/0x91).
KEYBOARD_REPORT_MAP = bytes([
    0x05, 0x01,        # Usage Page (Generic Desktop)
    0x09, 0x06,        # Usage (Keyboard)
    0xA1, 0x01,        # Collection (Application)
    0x85, KEYBOARD_INPUT_REPORT_ID,  #   Report ID (1)
    0x05, 0x07,        #   Usage Page (Keyboard/Keypad)
    0x19, 0xE0,        #   Usage Minimum (Keyboard LeftControl)
    0x29, 0xE7,        #   Usage Maximum (Keyboard Right GUI)
    0x15, 0x00,        #   Logical Minimum (0)
    0x25, 0x01,        #   Logical Maximum (1)
    0x75, 0x01,        #   Report Size (1)
    0x95, 0x08,        #   Report Count (8)
    0x81, 0x02,        #   Input (Data, Variable, Absolute) ; modifier
    0x75, 0x08,        #   Report Size (8)
    0x95, 0x01,        #   Report Count (1)
    0x81, 0x01,        #   Input (Constant) ; reserved
    0x15, 0x00,        #   Logical Minimum (0)
    0x26, 0xFF, 0x00,  #   Logical Maximum (0xFF)
    0x05, 0x07,        #   Usage Page (Keyboard/Keypad)
    0x19, 0x00,        #   Usage Minimum (Reserved)
    0x2A, 0xFF, 0x00,  #   Usage Maximum (0xFF)
    0x75, 0x08,        #   Report Size (8)
    0x95, 0x06,        #   Report Count (6)
    0x81, 0x00,        #   Input (Data, Array)
    0x05, 0x08,        #   Usage Page (LEDs)
    0x19, 0x01,        #   Usage Minimum (Num Lock)
    0x29, 0x05,        #   Usage Maximum (Kana)
    0x75, 0x01,        #   Report Size (1)
    0x95, 0x05,        #   Report Count (5)
    0x91, 0x02,        #   Output (Data, Variable, Absolute) ; LEDs
    0x75, 0x03,        #   Report Size (3)
    0x95, 0x01,        #   Report Count (1)
    0x91, 0x01,        #   Output (Constant) ; LED padding
    0xC0,              # End Collection

    0x05, 0x01,        # Usage Page (Generic Desktop)
    0x09, 0x02,        # Usage (Mouse)
    0xA1, 0x01,        # Collection (Application)
    0x85, MOUSE_INPUT_REPORT_ID,  #   Report ID (2)
    0x09, 0x01,        #   Usage (Pointer)
    0xA1, 0x00,        #   Collection (Physical)
    0x05, 0x09,        #     Usage Page (Button)
    0x19, 0x01,        #     Usage Minimum (Button 1)
    0x29, 0x05,        #     Usage Maximum (Button 5)
    0x15, 0x00,        #     Logical Minimum (0)
    0x25, 0x01,        #     Logical Maximum (1)
    0x75, 0x01,        #     Report Size (1)
    0x95, 0x05,        #     Report Count (5)
    0x81, 0x02,        #     Input (Data, Variable, Absolute)
    0x75, 0x03,        #     Report Size (3)
    0x95, 0x01,        #     Report Count (1)
    0x81, 0x01,        #     Input (Constant)
    0x05, 0x01,        #     Usage Page (Generic Desktop)
    0x09, 0x30,        #     Usage (X)
    0x09, 0x31,        #     Usage (Y)
    0x09, 0x38,        #     Usage (Wheel)
    0x15, 0x81,        #     Logical Minimum (-127)
    0x25, 0x7F,        #     Logical Maximum (127)
    0x75, 0x08,        #     Report Size (8)
    0x95, 0x03,        #     Report Count (3)
    0x81, 0x06,        #     Input (Data, Variable, Relative)
    0xC0,              #   End Collection
    0xC0,              # End Collection
])

CONSUMER_REPORT_MAP = bytes([
    0x05, 0x0C,        # Usage Page (Consumer)
    0x09, 0x01,        # Usage (Consumer Control)
    0xA1, 0x01,        # Collection (Application)
    0x85, CONSUMER_INPUT_REPORT_ID,  #   Report ID (3)
    0x15, 0x00,        #   Logical Minimum (0)
    0x26, 0xFF, 0x03,  #   Logical Maximum (0x03FF)
    0x19, 0x00,        #   Usage Minimum (0)
    0x2A, 0xFF, 0x03,  #   Usage Maximum (0x03FF)
    0x75, 0x10,        #   Report Size (16)
    0x95, 0x01,        #   Report Count (1)
    0x81, 0x00,        #   Input (Data, Array, Absolute)
    0xC0,              # End Collection
])


def hid_report_map(*, include_consumer: bool = False) -> bytes:
    """Return the HID Report Map exposed to hosts.

    Consumer Control changes the host-visible HID descriptor and can require
    re-pairing on already-bonded iOS hosts. Keep it opt-in until host cache
    behavior is verified.
    """
    if include_consumer:
        return KEYBOARD_REPORT_MAP + CONSUMER_REPORT_MAP
    return KEYBOARD_REPORT_MAP


@dataclass(frozen=True)
class GattInputReportSpec:
    """Metadata for one BLE HID report characteristic."""

    report_id: int
    report_type: int
    payload_size: int
    value_size: int

    @property
    def report_reference(self) -> bytes:
        return bytes([self.report_id, self.report_type])

    def encode_value(self, payload: bytes) -> bytes:
        if len(payload) != self.payload_size:
            raise ValueError(f"BLE report {self.report_id} must be {self.payload_size} bytes, got {len(payload)}")
        return bytes(payload)


KEYBOARD_INPUT_REPORT = GattInputReportSpec(
    report_id=KEYBOARD_INPUT_REPORT_ID,
    report_type=REPORT_TYPE_INPUT,
    payload_size=KEYBOARD_INPUT_REPORT_SIZE,
    value_size=KEYBOARD_GATT_REPORT_VALUE_SIZE,
)

KEYBOARD_OUTPUT_REPORT = GattInputReportSpec(
    report_id=KEYBOARD_OUTPUT_REPORT_ID,
    report_type=REPORT_TYPE_OUTPUT,
    payload_size=KEYBOARD_OUTPUT_REPORT_SIZE,
    value_size=KEYBOARD_OUTPUT_REPORT_SIZE,
)

MOUSE_INPUT_REPORT = GattInputReportSpec(
    report_id=MOUSE_INPUT_REPORT_ID,
    report_type=REPORT_TYPE_INPUT,
    payload_size=MOUSE_INPUT_REPORT_SIZE,
    value_size=MOUSE_GATT_REPORT_VALUE_SIZE,
)

CONSUMER_INPUT_REPORT = GattInputReportSpec(
    report_id=CONSUMER_INPUT_REPORT_ID,
    report_type=REPORT_TYPE_INPUT,
    payload_size=CONSUMER_INPUT_REPORT_SIZE,
    value_size=CONSUMER_GATT_REPORT_VALUE_SIZE,
)


def validate_keyboard_report_payload(payload: bytes) -> None:
    """Validate payload size before sending it as BLE keyboard input report."""
    if len(payload) != KEYBOARD_INPUT_REPORT.payload_size:
        raise ValueError(
            f"keyboard BLE input report must be {KEYBOARD_INPUT_REPORT.payload_size} bytes, got {len(payload)}"
        )


def validate_mouse_report_payload(payload: bytes) -> None:
    """Validate payload size before sending it as BLE mouse input report."""
    if len(payload) != MOUSE_INPUT_REPORT.payload_size:
        raise ValueError(
            f"mouse BLE input report must be {MOUSE_INPUT_REPORT.payload_size} bytes, got {len(payload)}"
        )


def validate_consumer_report_payload(payload: bytes) -> None:
    """Validate payload size before sending it as BLE Consumer Control input report."""
    if len(payload) != CONSUMER_INPUT_REPORT.payload_size:
        raise ValueError(
            f"consumer BLE input report must be {CONSUMER_INPUT_REPORT.payload_size} bytes, got {len(payload)}"
        )
