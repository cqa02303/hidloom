#!/usr/bin/env python3
"""Regression checks for usbd USB HID report broker helpers."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from usbd.hid_report_broker import (  # noqa: E402
    CHECKSUM_OFFSET,
    FRAME_MAGIC,
    FRAME_SIZE,
    FRAME_VERSION,
    KIND_CONSUMER,
    KIND_KEYBOARD,
    KIND_MOUSE,
    KIND_US_SUB_KEYBOARD,
    adapt_current_multi_report_profile,
    decode_hid_report_request,
    encode_hid_report_request,
)


def _assert_raises(message: str, func) -> None:
    try:
        func()
    except ValueError as exc:
        assert message in str(exc), str(exc)
        return
    raise AssertionError(f"expected ValueError containing {message!r}")


def main() -> None:
    keyboard_payload = bytes.fromhex("0000040000000000")
    frame = encode_hid_report_request(KIND_KEYBOARD, keyboard_payload)
    assert len(frame) == FRAME_SIZE
    assert frame[:4] == FRAME_MAGIC
    assert frame[4] == FRAME_VERSION
    assert frame[5] == KIND_KEYBOARD
    assert frame[6] == 8
    assert frame[7] == 0
    assert frame[8:16] == keyboard_payload
    assert frame[16:CHECKSUM_OFFSET] == bytes(CHECKSUM_OFFSET - 16)
    request = decode_hid_report_request(frame)
    assert request.kind == KIND_KEYBOARD
    assert request.kind_name == "keyboard"
    assert request.payload == keyboard_payload
    usb = adapt_current_multi_report_profile(request)
    assert usb.endpoint == "/dev/hidg0"
    assert usb.kind_name == "keyboard"
    assert usb.report == bytes.fromhex("010000040000000000")

    mouse = adapt_current_multi_report_profile(
        decode_hid_report_request(encode_hid_report_request(KIND_MOUSE, bytes.fromhex("01020304")))
    )
    assert mouse.report == bytes.fromhex("0201020304")

    consumer = adapt_current_multi_report_profile(
        decode_hid_report_request(encode_hid_report_request(KIND_CONSUMER, bytes.fromhex("e900")))
    )
    assert consumer.report == bytes.fromhex("03e900")

    us_sub_request = decode_hid_report_request(encode_hid_report_request(KIND_US_SUB_KEYBOARD, bytes.fromhex("0000900000000000")))
    us_sub_keyboard = adapt_current_multi_report_profile(us_sub_request)
    assert us_sub_keyboard.endpoint == "/dev/hidg2"
    assert us_sub_keyboard.kind_name == "us_sub_keyboard"
    assert us_sub_keyboard.report == bytes.fromhex("0000900000000000")

    _assert_raises("invalid keyboard payload length", lambda: encode_hid_report_request(KIND_KEYBOARD, bytes(7)))
    _assert_raises("unsupported HID report kind", lambda: encode_hid_report_request(0x99, bytes(1)))
    _assert_raises("invalid HID report request size", lambda: decode_hid_report_request(frame[:-1]))

    bad = bytearray(frame)
    bad[0:4] = b"NOPE"
    _assert_raises("invalid HID report request magic", lambda: decode_hid_report_request(bytes(bad)))

    bad = bytearray(frame)
    bad[CHECKSUM_OFFSET] ^= 0xFF
    _assert_raises("invalid HID report request checksum", lambda: decode_hid_report_request(bytes(bad)))

    bad = bytearray(frame)
    bad[20] = 1
    bad[CHECKSUM_OFFSET] = 0
    checksum = 0
    for byte in bad[:CHECKSUM_OFFSET]:
        checksum ^= byte
    bad[CHECKSUM_OFFSET] = checksum
    _assert_raises("reserved bytes must be zero", lambda: decode_hid_report_request(bytes(bad)))

    print("ok: usbd HID report broker helpers")


if __name__ == "__main__":
    main()
