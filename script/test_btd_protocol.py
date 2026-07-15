#!/usr/bin/env python3
"""Regression tests for btd.protocol."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from btd.protocol import (  # noqa: E402
    KEYBOARD_REPORT_SIZE,
    MOUSE_REPORT_SIZE,
    CONSUMER_REPORT_SIZE,
    ConsumerReport,
    KeyboardReport,
    MouseReport,
    encode_hid_frame,
    null_consumer_report,
    null_keyboard_report,
    null_mouse_report,
    parse_raw_consumer_report,
    parse_raw_keyboard_report,
    parse_raw_mouse_report,
)


def main() -> None:
    assert KEYBOARD_REPORT_SIZE == 8
    assert MOUSE_REPORT_SIZE == 4
    assert CONSUMER_REPORT_SIZE == 2

    null_report = null_keyboard_report()
    assert null_report.is_null
    assert null_report.hex == "0000000000000000"
    null_mouse = null_mouse_report()
    assert null_mouse.is_null
    assert null_mouse.hex == "00000000"
    null_consumer = null_consumer_report()
    assert null_consumer.is_null
    assert null_consumer.hex == "0000"

    a_report = parse_raw_keyboard_report(bytes.fromhex("0000040000000000"))
    assert not a_report.is_null
    assert a_report.hex == "0000040000000000"
    mouse_report = parse_raw_mouse_report(bytes.fromhex("0001ff00"))
    assert not mouse_report.is_null
    assert mouse_report.hex == "0001ff00"
    consumer_report = parse_raw_consumer_report(bytes.fromhex("e900"))
    assert not consumer_report.is_null
    assert consumer_report.hex == "e900"
    assert encode_hid_frame(a_report) == b"btd1" + bytes([1, 8]) + a_report.report
    assert encode_hid_frame(mouse_report) == b"btd1" + bytes([2, 4]) + mouse_report.report
    assert encode_hid_frame(consumer_report) == b"btd1" + bytes([4, 2]) + consumer_report.report

    try:
        KeyboardReport(b"short")
    except ValueError as exc:
        assert "8 bytes" in str(exc)
    else:
        raise AssertionError("short report should fail")

    try:
        MouseReport(b"short")
    except ValueError as exc:
        assert "4 bytes" in str(exc)
    else:
        raise AssertionError("long mouse report should fail")

    try:
        ConsumerReport(b"bad")
    except ValueError as exc:
        assert "2 bytes" in str(exc)
    else:
        raise AssertionError("long consumer report should fail")

    print("ok: btd protocol helpers")


if __name__ == "__main__":
    main()
