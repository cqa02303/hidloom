#!/usr/bin/env python3
"""Regression tests for USB host LED Output Report parsing."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.host_led_reader import host_led_report_from_payload  # noqa: E402


def main() -> None:
    assert host_led_report_from_payload(bytes([0x00])) == 0x00
    assert host_led_report_from_payload(bytes([0x07])) == 0x07
    assert host_led_report_from_payload(bytes([0xFF, 0xAA])) == 0xFF
    assert host_led_report_from_payload(bytes([0x01, 0x02])) == 0x02
    assert host_led_report_from_payload(bytes([0x01, 0x07, 0xAA])) == 0x07
    try:
        host_led_report_from_payload(b"")
    except ValueError:
        pass
    else:
        raise AssertionError("empty host LED output report should fail")

    print("ok: logicd host LED reader")


if __name__ == "__main__":
    main()
