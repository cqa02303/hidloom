#!/usr/bin/env python3
"""Print the proposed Windows IME custom HID descriptor dry-run.

This helper intentionally does not touch configfs and does not require a
Raspberry Pi.  It documents the future opt-in /dev/hidg4 interface shape so the
real gadget script can be reviewed before any descriptor-changing work happens.
"""
from __future__ import annotations

CUSTOM_HID_FUNCTION = "hid.usb4"
CUSTOM_HID_DEVICE = "/dev/hidg4"
REPORT_LENGTH = 8

# Vendor-defined usage page 0xFF70, usage 0x01, one 8-byte input and one 8-byte
# output report.  Output is reserved for a future receiver/status handshake; the
# first implementation should only require input reports from Pi to host.
REPORT_DESCRIPTOR = bytes([
    0x06, 0x70, 0xFF,  # Usage Page (Vendor Defined 0xFF70)
    0x09, 0x01,        # Usage (0x01)
    0xA1, 0x01,        # Collection (Application)
    0x15, 0x00,        # Logical Minimum (0)
    0x26, 0xFF, 0x00,  # Logical Maximum (255)
    0x75, 0x08,        # Report Size (8)
    0x95, 0x08,        # Report Count (8)
    0x09, 0x02,        # Usage (Input Report)
    0x81, 0x02,        # Input (Data,Var,Abs)
    0x95, 0x08,        # Report Count (8)
    0x09, 0x03,        # Usage (Output Report)
    0x91, 0x02,        # Output (Data,Var,Abs)
    0xC0,              # End Collection
])


def descriptor_shell_literal() -> str:
    return "".join(f"\\x{byte:02x}" for byte in REPORT_DESCRIPTOR)


def main() -> None:
    print("Windows IME custom HID descriptor dry-run")
    print(f"function:      {CUSTOM_HID_FUNCTION}")
    print(f"device:        {CUSTOM_HID_DEVICE}")
    print(f"report_length: {REPORT_LENGTH}")
    print(f"descriptor:    {descriptor_shell_literal()}")
    print()
    print("setup sketch:")
    print(f"  mkdir -p functions/{CUSTOM_HID_FUNCTION}")
    print(f"  echo 0 > functions/{CUSTOM_HID_FUNCTION}/protocol")
    print(f"  echo 0 > functions/{CUSTOM_HID_FUNCTION}/subclass")
    print(f"  echo {REPORT_LENGTH} > functions/{CUSTOM_HID_FUNCTION}/report_length")
    print(f"  echo -ne '{descriptor_shell_literal()}' > functions/{CUSTOM_HID_FUNCTION}/report_desc")
    print(f"  ln -s functions/{CUSTOM_HID_FUNCTION} configs/c.1/")
    print()
    print("guard: do not add this interface unless an explicit custom HID IME profile is enabled")


if __name__ == "__main__":
    main()
