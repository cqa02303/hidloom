#!/usr/bin/env python3
"""Regression checks for the USB gadget HID descriptors."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _descriptor_bytes_for(function_name: str) -> bytes:
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
        raise AssertionError(f"report descriptor for {function_name} not found")
    descriptor = max(matches, key=len)
    return descriptor.encode("utf-8").decode("unicode_escape").encode("latin1")


def _shell_variable_bytes(name: str) -> bytes:
    script = (ROOT / "system" / "install" / "setup_usb_gadget.sh").read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(name)}='([^']+)'$", script, re.MULTILINE)
    if not match:
        raise AssertionError(f"shell variable {name} not found")
    return match.group(1).encode("utf-8").decode("unicode_escape").encode("latin1")


def main() -> None:
    script = (ROOT / "system" / "install" / "setup_usb_gadget.sh").read_text(encoding="utf-8")
    wrapper = (ROOT / "setup_usb_gadget.sh").read_text(encoding="utf-8")
    service = (ROOT / "system" / "systemd" / "hidloom-usb-gadget.service").read_text(
        encoding="utf-8"
    )
    config = (ROOT / "config" / "default" / "config.json").read_text(encoding="utf-8")
    documentation = (ROOT / "USB_GADGET_SETUP.md").read_text(encoding="utf-8")
    assert documentation.startswith("# HIDloom USB Gadget Reference\n")
    assert "`0x1d6b:0x0105`" in documentation
    assert "公開Releaseではこの組み合わせを正式IDとして使用しません" in documentation
    assert "pid.codesの`0x1209`" in documentation
    assert "`0x1209:0x484C`" in documentation
    assert "`candidate-unassigned`" in documentation
    assert "tools/pid_codes_application.py" in documentation
    assert "`pid_codes_migration_required`を解除しない" in documentation
    assert "`system/install/setup_usb_gadget.sh`" in documentation
    assert "`system/systemd/hidloom-usb-gadget.service`" in documentation
    assert service.count("EnvironmentFile=-/etc/hidloom/usb-identity.env") == 1
    assert "`/dev/hidg0`" in documentation
    assert "`/dev/hidg1`" in documentation
    assert "`/dev/hidg2`" in documentation
    assert "`/dev/hidg4`" in documentation
    assert "send_key.sh" not in documentation
    assert "CQA02303v5_keyboard_layout.txt" not in documentation
    assert "セットアップ完了" not in documentation
    assert "system/install/setup_usb_gadget.sh" in wrapper
    assert 'HIDLOOM_USB_GADGET_SETUP_BACKEND:-shell' in wrapper
    assert 'bin/hidloom-usb-gadget-fast' in wrapper
    assert "native USB gadget helper is not executable" in wrapper
    assert '"serial_number": "vial:f64c2b3c"' in config
    assert 'if [[ -n "${HIDLOOM_USB_VENDOR_ID:-}" ]]; then' in script
    assert 'if [[ -n "${HIDLOOM_USB_PRODUCT_ID:-}" ]]; then' in script
    assert 'if [[ -n "${HIDLOOM_USB_MANUFACTURER:-}" ]]; then' in script
    assert 'if [[ -n "${HIDLOOM_USB_PRODUCT_NAME:-}" ]]; then' in script
    assert 'if [[ -n "${HIDLOOM_USB_SERIAL:-}" ]]; then' in script
    assert 'VENDOR_ID="$(parse_u16 "USB vendor ID" "$VENDOR_ID")"' in script
    assert 'PRODUCT_ID="$(parse_u16 "USB product ID" "$PRODUCT_ID")"' in script
    assert 'SERIAL_NUMBER="vial:f64c2b3c"' in script
    assert 'sh("SERIAL_NUMBER"; .device.serial_number // "vial:f64c2b3c")' in script
    assert 'SERIAL_NUMBER="${SERIAL_NUMBER//__HOSTNAME__/$NODE_NAME}"' in script
    assert 'SERIAL_NUMBER="${SERIAL_NUMBER}:${HIDLOOM_USB_SERIAL_SUFFIX}"' in script
    assert script.index('if [[ -n "${HIDLOOM_USB_SERIAL:-}" ]]; then') < script.index(
        'SERIAL_NUMBER="${SERIAL_NUMBER//__HOSTNAME__/$NODE_NAME}"'
    ) < script.index('if [[ -n "${HIDLOOM_USB_SERIAL_SUFFIX:-}" ]]; then')
    assert 'echo "$SERIAL_NUMBER" > strings/0x409/serialnumber' in script
    assert '"hid_country_code": 0' in config
    assert '"usb_keyboard_identity_strings": {' in config
    assert '"profile": "default"' in config
    assert 'KEYBOARD_IDENTITY_STRINGS_PROFILE="${HIDLOOM_USB_KEYBOARD_IDENTITY_STRINGS:-default}"' in script
    assert ".settings.usb_keyboard_identity_strings.profile // \"default\"" in script
    assert 'PRODUCT_NAME="${NODE_NAME} 101 US Keyboard"' in script
    assert 'PRODUCT_NAME_JA="${NODE_NAME} 101英語キーボード"' in script
    assert 'PRODUCT_NAME="${NODE_NAME} 106 JP Keyboard"' in script
    assert 'PRODUCT_NAME_JA="${NODE_NAME} 106日本語キーボード"' in script
    assert 'mkdir -p strings/0x411' in script
    assert 'echo "$PRODUCT_NAME_JA" > strings/0x411/product' in script
    assert 'CONFIG_KEYBOARD_LABEL="101 US Keyboard"' in script
    assert 'CONFIG_KEYBOARD_LABEL_JA="101英語キーボード"' in script
    assert 'CONFIG_KEYBOARD_LABEL="106 JP Keyboard"' in script
    assert 'CONFIG_KEYBOARD_LABEL_JA="106日本語キーボード"' in script
    assert 'CONFIG_KEYBOARD_LABEL="HID Keyboard"' in script
    assert 'CONFIG_KEYBOARD_LABEL_JA="HIDキーボード"' in script
    assert 'mkdir -p configs/c.1/strings/0x411' in script
    assert 'Config 1: ${CONFIG_KEYBOARD_LABEL}+Mouse+Consumer+RawHID' in script
    assert 'Config 1: ${CONFIG_KEYBOARD_LABEL_JA}+Mouse+Consumer+RawHID' in script
    assert "HIDLOOM_USB_JP_DRIVER_FALLBACK_STRINGS" in script
    assert '"usb_split_keyboard": {' in config
    assert '"route": "jis_special_us_default"' in config
    assert 'US_SUB_KEYBOARD_ENABLED="${HIDLOOM_USB_US_SUB_KEYBOARD:-0}"' in script
    assert ".settings.us_sub_keyboard.enabled // false" in script
    assert '"windows_ime_custom_hid": {' in config
    assert '"enabled": false' in config
    assert '"us_keyboard": {' in config
    assert '"identity_string": "US101"' in config
    assert '"us_sub_keyboard": {' in config
    assert '"identity_string": "US101"' in config
    assert 'sh("HID_COUNTRY_CODE"; .device.hid_country_code // .device.country_code // 0)' in script
    assert 'parse_u8 "$HID_COUNTRY_CODE"' in script
    assert "apply_hid_country_code" in script
    assert "country_code" in script and "bCountryCode" in script
    assert "does not expose a configfs HID country code attribute" in script
    assert "WINDOWS_IME_CUSTOM_HID_ENABLED=\"${HIDLOOM_WINDOWS_IME_CUSTOM_HID:-0}\"" in script
    assert 'HID_INTERFACE_STRINGS_ENABLED="${HIDLOOM_USB_HID_INTERFACE_STRINGS:-0}"' in script
    assert ".settings.windows_ime_custom_hid.enabled // false" in script
    assert "US_KEYBOARD_IDENTITY_STRING=\"${HIDLOOM_US_KEYBOARD_IDENTITY_STRING:-US101}\"" in script
    assert 'US_SUB_KEYBOARD_ENABLED="${HIDLOOM_USB_US_SUB_KEYBOARD:-0}"' in script
    assert 'US_SUB_KEYBOARD_IDENTITY_STRING="${HIDLOOM_US_SUB_KEYBOARD_IDENTITY_STRING:-US101}"' in script
    assert '.settings.us_keyboard.identity_string // "US101"' in script
    assert '.settings.us_sub_keyboard.identity_string // "US101"' in script
    assert '.settings.us_sub_keyboard.enabled // false' in script
    assert "US_SUB_TEST_USB_ID_ENABLED" not in script
    assert "US_SUB_TEST_VENDOR_ID" not in script
    assert "US_SUB_TEST_PRODUCT_ID" not in script
    assert 'COMPOSITE_PRODUCT_NAME="$PRODUCT_NAME"' in script
    assert "apply_hid_interface_strings" in script
    assert 'HID_INTERFACE_STRINGS_ENABLED="$(parse_bool "$HID_INTERFACE_STRINGS_ENABLED")"' in script
    assert 'if [[ "$HID_INTERFACE_STRINGS_ENABLED" -ne 1 ]]; then' in script
    assert 'apply_hid_interface_strings "$(pwd)" "hid.usb0" "$US_KEYBOARD_IDENTITY_STRING"' in script
    assert 'apply_hid_interface_strings "$(pwd)" "hid.usb2" "$US_SUB_KEYBOARD_IDENTITY_STRING"' in script
    assert 'mkdir -p strings/0x411' in script
    assert 'echo "$PRODUCT_NAME" > strings/0x409/product' in script
    assert 'echo "$PRODUCT_NAME_JA" > strings/0x411/product' in script
    assert 'mkdir -p configs/c.1/strings/0x411' in script
    assert 'CONFIG_EXTRA_LABEL="+UsSubKeyboard"' in script
    assert 'if [[ "$WINDOWS_IME_CUSTOM_HID_ENABLED" -eq 1 ]]; then' in script
    assert "WinImeCustom" in script
    assert 'if [[ "$US_SUB_KEYBOARD_ENABLED" -eq 1 ]]; then' in script
    assert 'CONFIG_EXTRA_LABEL="+WinImeCustom"' in script
    assert 'CONFIG_EXTRA_LABEL="+UsSubKeyboard+WinImeCustom"' in script
    assert "Config 1: ${CONFIG_KEYBOARD_LABEL}+Mouse+Consumer+RawHID${CONFIG_EXTRA_LABEL}" in script
    assert "ln -s functions/hid.usb2 configs/c.1/" in script
    assert "ln -s functions/hid.usb4 configs/c.1/" in script
    assert "hid.usb4" in script
    assert "preflight_extra_hid_functions" in script
    assert "Existing USB gadget was left untouched." in script
    assert "Disable US sub keyboard or Windows IME custom HID on endpoint-limited devices." in script
    assert "expected_hidg=(/dev/hidg0 /dev/hidg1)" in script
    assert "expected_hidg+=(/dev/hidg2)" in script
    assert "expected_hidg+=(/dev/hidg4)" in script
    assert "sleep 1" not in script
    assert "echo 9 > report_length" in script
    assert "mkdir -p functions/hid.usb2" in script
    assert 'cd functions/hid.usb2\n    echo 1 > protocol\n    echo 1 > subclass\n    echo "$US_SUB_KEYBOARD_REPORT_LENGTH" > report_length' in script
    assert "mkdir -p functions/hid.usb3" not in script
    assert "ln -s functions/hid.usb2 configs/c.1/" in script
    assert "ln -s functions/hid.usb3 configs/c.1/" not in script
    assert "hid.usb2 configs/c.1" not in script.split('if [[ "$US_SUB_KEYBOARD_ENABLED" -eq 1 ]]; then')[0]
    assert "strings/0x411/product" not in script.split('if [[ "$US_SUB_KEYBOARD_ENABLED" -eq 1 ]]; then')[0]

    keyboard = _descriptor_bytes_for("hid.usb0")
    assert keyboard.startswith(bytes.fromhex("05 01 09 06 a1 01 85 01"))
    assert bytes.fromhex("15 00 26 ff 00 05 07 19 00 2a ff 00") in keyboard
    assert bytes.fromhex("25 65") not in keyboard
    assert bytes.fromhex("29 65") not in keyboard
    assert bytes.fromhex("05 08 19 01 29 05") in keyboard
    assert bytes.fromhex("95 05 91 02") in keyboard
    assert bytes.fromhex("75 03 95 01 91 03") in keyboard
    assert bytes.fromhex("05 01 09 02 a1 01 85 02") in keyboard
    assert bytes.fromhex("09 30 09 31 09 38") in keyboard
    assert bytes.fromhex("05 0c 09 01 a1 01 85 03") in keyboard
    assert bytes.fromhex("75 10 95 01 81 00") in keyboard
    assert keyboard[-1] == 0xC0

    raw_hid = _descriptor_bytes_for("hid.usb1")
    assert bytes.fromhex("95 20 09 62 81 02") in raw_hid
    assert bytes.fromhex("95 20 09 63 91 02") in raw_hid

    us_sub_keyboard = _shell_variable_bytes("US_SUB_KEYBOARD_REPORT_DESC")
    assert us_sub_keyboard.startswith(bytes.fromhex("05 01 09 06 a1 01"))
    assert bytes.fromhex("19 e0 29 e7") in us_sub_keyboard
    assert bytes.fromhex("19 00 2a ff 00") in us_sub_keyboard
    assert bytes.fromhex("05 08 19 01 29 05") in us_sub_keyboard
    assert bytes.fromhex("95 05 91 02") in us_sub_keyboard
    assert us_sub_keyboard[-1] == 0xC0
    assert 'US_SUB_KEYBOARD_REPORT_LENGTH="8"' in script
    assert 'echo "$US_SUB_KEYBOARD_REPORT_LENGTH" > report_length' in script

    win_ime_custom = _shell_variable_bytes("WINDOWS_IME_CUSTOM_HID_REPORT_DESC")
    from script.describe_windows_ime_custom_hid_descriptor import REPORT_DESCRIPTOR, REPORT_LENGTH

    assert win_ime_custom == REPORT_DESCRIPTOR
    assert f'WINDOWS_IME_CUSTOM_HID_REPORT_LENGTH="{REPORT_LENGTH}"' in script
    assert 'echo "$WINDOWS_IME_CUSTOM_HID_REPORT_LENGTH" > report_length' in script
    assert "hid.usb4 configs/c.1" not in script.split('if [[ "$WINDOWS_IME_CUSTOM_HID_ENABLED" -eq 1 ]]; then')[0]

    print("ok: USB gadget HID descriptors")


if __name__ == "__main__":
    main()
