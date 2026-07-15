#!/usr/bin/env python3
"""Static checks for the Windows IME custom HID descriptor dry-run helper."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from script.describe_windows_ime_custom_hid_descriptor import (  # noqa: E402
    CUSTOM_HID_DEVICE,
    CUSTOM_HID_FUNCTION,
    REPORT_DESCRIPTOR,
    REPORT_LENGTH,
    descriptor_shell_literal,
)


def main() -> None:
    assert CUSTOM_HID_FUNCTION == "hid.usb4"
    assert CUSTOM_HID_DEVICE == "/dev/hidg4"
    assert REPORT_LENGTH == 8
    assert len(REPORT_DESCRIPTOR) > 0

    # Vendor-defined usage page 0xFF70, application collection.
    assert REPORT_DESCRIPTOR[:6] == bytes([0x06, 0x70, 0xFF, 0x09, 0x01, 0xA1])
    assert REPORT_DESCRIPTOR[-1] == 0xC0

    shell = descriptor_shell_literal()
    assert shell.startswith("\\x06\\x70\\xff")
    assert shell.endswith("\\xc0")
    assert "hid.usb4" not in shell

    # The descriptor should contain one 8-byte input and one 8-byte output report.
    assert shell.count("\\x95\\x08") == 2
    assert "\\x81\\x02" in shell
    assert "\\x91\\x02" in shell


if __name__ == "__main__":
    main()
