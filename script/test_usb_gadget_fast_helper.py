#!/usr/bin/env python3
"""Regression checks for the native USB gadget fast-path helper."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "tools" / "hidloom_usb_gadget_fast" / "hidloom_usb_gadget_fast.c"


def _c_array_bytes(name: str) -> bytes:
    text = HELPER.read_text(encoding="utf-8")
    match = re.search(rf"static const uint8_t {re.escape(name)}\[\] = \{{(.*?)\}};", text, re.S)
    if not match:
        raise AssertionError(f"C descriptor array not found: {name}")
    values = re.findall(r"0x([0-9A-Fa-f]{2})", match.group(1))
    if not values:
        raise AssertionError(f"C descriptor array is empty: {name}")
    return bytes(int(value, 16) for value in values)


def _shell_descriptor_bytes_for(function_name: str) -> bytes:
    script = (ROOT / "system" / "install" / "setup_usb_gadget.sh").read_text(encoding="utf-8")
    start = script.find(f"mkdir -p functions/{function_name}")
    if start < 0:
        raise AssertionError(f"function block for {function_name} not found")
    if function_name == "hid.usb0":
        end = script.find("# /dev/hidg1", start)
    elif function_name == "hid.usb1":
        end = script.find('if [[ "$US_SUB_KEYBOARD_ENABLED"', start)
    else:
        end = -1
    body = script[start:] if end < 0 else script[start:end]
    matches = re.findall(r"echo -ne '([^']+)' > report_desc", body)
    if not matches:
        raise AssertionError(f"shell report descriptor for {function_name} not found")
    descriptor = max(matches, key=len)
    return descriptor.encode("utf-8").decode("unicode_escape").encode("latin1")


def _shell_variable_bytes(name: str) -> bytes:
    script = (ROOT / "system" / "install" / "setup_usb_gadget.sh").read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(name)}='([^']+)'$", script, re.MULTILINE)
    if not match:
        raise AssertionError(f"shell variable {name} not found")
    return match.group(1).encode("utf-8").decode("unicode_escape").encode("latin1")


def main() -> None:
    text = HELPER.read_text(encoding="utf-8")
    assert "HIDLOOM_USB_GADGET_ROOT" in text
    assert "HIDLOOM_USB_VENDOR_ID" in text
    assert "HIDLOOM_USB_PRODUCT_ID" in text
    assert "HIDLOOM_USB_MANUFACTURER" in text
    assert "HIDLOOM_USB_PRODUCT_NAME" in text
    assert "HIDLOOM_USB_SERIAL" in text
    assert "HIDLOOM_USB_US_SUB_KEYBOARD" in text
    assert "HIDLOOM_WINDOWS_IME_CUSTOM_HID" in text
    assert "DEFAULT_US_IDENTITY" not in text
    assert "json" not in text.lower()
    assert "regex" not in text.lower()
    assert 'write_child_text(dir, "manufacturer", cfg->manufacturer);' in text
    assert 'write_child_text(dir, "product", cfg->product_name);' in text
    assert text.count("resolve_hostname_placeholder(") == 4
    assert 'strcmp(value, "__HOSTNAME__") == 0' in text
    assert text.index('"HIDLOOM_USB_SERIAL", DEFAULT_SERIAL') < text.index(
        'getenv("HIDLOOM_USB_SERIAL_SUFFIX")'
    )

    assert _c_array_bytes("HID_USB0_REPORT_DESC") == _shell_descriptor_bytes_for("hid.usb0")
    assert _c_array_bytes("HID_USB1_REPORT_DESC") == _shell_descriptor_bytes_for("hid.usb1")
    assert _c_array_bytes("HID_USB2_REPORT_DESC") == _shell_variable_bytes("US_SUB_KEYBOARD_REPORT_DESC")
    assert _c_array_bytes("HID_USB4_REPORT_DESC") == _shell_variable_bytes("WINDOWS_IME_CUSTOM_HID_REPORT_DESC")

    print("ok: USB gadget native fast helper")


if __name__ == "__main__":
    main()
