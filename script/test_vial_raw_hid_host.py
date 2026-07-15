#!/usr/bin/env python3
"""Host-side Raw HID smoke test for the Raspberry Pi Vial bridge.

Requires:
    python -m pip install hidapi

On Windows, hidapi write() includes a leading report ID byte even when the
device descriptor has no report IDs, so this script prefixes each 32-byte
payload with 0x00 on write and expects a 32-byte payload on read.
"""
from __future__ import annotations

import argparse
import struct
import hid

VENDOR_ID = 0x1D6B
PRODUCT_ID = 0x0105
RAW_HID_INTERFACE = 1
REPORT_SIZE = 32

CMD_VIA_GET_PROTOCOL_VERSION = 0x01
CMD_VIA_GET_LAYER_COUNT = 0x11
CMD_VIA_VIAL_PREFIX = 0xFE
CMD_VIAL_GET_KEYBOARD_ID = 0x00


def packet(*values: int) -> bytes:
    return bytes(values).ljust(REPORT_SIZE, b"\x00")


def find_raw_hid() -> dict:
    for device in hid.enumerate(VENDOR_ID, PRODUCT_ID):
        if device.get("interface_number") == RAW_HID_INTERFACE:
            return device
    raise SystemExit("raw HID interface MI_01 not found")


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test Vial Raw HID bridge from the host")
    parser.add_argument("--timeout-ms", type=int, default=3000, help="read timeout in milliseconds")
    args = parser.parse_args()

    raw_hid = find_raw_hid()
    dev = hid.device()
    dev.open_path(raw_hid["path"])
    dev.set_nonblocking(False)
    try:
        requests = [
            ("protocol version", packet(CMD_VIA_GET_PROTOCOL_VERSION)),
            ("layer count", packet(CMD_VIA_GET_LAYER_COUNT)),
            ("keyboard id", packet(CMD_VIA_VIAL_PREFIX, CMD_VIAL_GET_KEYBOARD_ID)),
        ]
        responses: dict[str, bytes] = {}
        for name, request in requests:
            written = dev.write(b"\x00" + request)
            response = bytes(dev.read(REPORT_SIZE, args.timeout_ms))
            if written != REPORT_SIZE + 1:
                raise SystemExit(f"{name}: expected {REPORT_SIZE + 1} bytes written, got {written}")
            if len(response) != REPORT_SIZE:
                raise SystemExit(f"{name}: expected {REPORT_SIZE} byte response, got {len(response)}")
            responses[name] = response
    finally:
        dev.close()

    if responses["protocol version"][:3] != bytes([CMD_VIA_GET_PROTOCOL_VERSION, 0x00, 0x09]):
        raise SystemExit(f"protocol version response mismatch: {responses['protocol version'].hex()}")
    if responses["layer count"][0] != CMD_VIA_GET_LAYER_COUNT or responses["layer count"][1] < 1:
        raise SystemExit(f"layer count response mismatch: {responses['layer count'].hex()}")
    vial_protocol, _uid = struct.unpack("<IQ", responses["keyboard id"][:12])
    if vial_protocol != 5:
        raise SystemExit(f"keyboard id response mismatch: {responses['keyboard id'].hex()}")

    print("ok: Vial Raw HID protocol packets crossed the host bridge")


if __name__ == "__main__":
    main()
