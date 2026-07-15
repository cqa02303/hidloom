#!/usr/bin/env python3
"""Smoke tests for Windows US IME custom HID routing helpers."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.windows_ime_custom_hid import (  # noqa: E402
    build_windows_ime_custom_hid_plan,
    decode_windows_ime_custom_hid_report,
    encode_windows_ime_custom_hid_report,
    is_windows_ime_custom_hid_action,
    windows_ime_custom_hid_warning_metadata,
)


def assert_equal(actual, expected):
    assert actual == expected, f"{actual!r} != {expected!r}"


def main() -> None:
    for action in (
        "KC_INT4",
        "KC_INT5",
        "KC_LANG1",
        "KC_LANG2",
        "KC_HENK",
        "KC_HENKAN",
        "KC_MHEN",
        "KC_MUHENKAN",
        "kc_mhen",
    ):
        assert is_windows_ime_custom_hid_action(action), action
    assert not is_windows_ime_custom_hid_action("KC_A")

    normal = build_windows_ime_custom_hid_plan("KC_A")
    assert_equal(normal.route, "keyboard")
    assert_equal(normal.enabled, False)
    assert_equal(normal.blocked_reason, "not_custom_hid_action")
    normal_meta = windows_ime_custom_hid_warning_metadata(normal)
    assert_equal(normal_meta["family"], "windows_ime_custom_hid")
    assert_equal(normal_meta["requires_custom_hid_endpoint"], False)

    wrong_profile = build_windows_ime_custom_hid_plan("KC_LANG1", host_profile="windows_us")
    assert_equal(wrong_profile.route, "custom_hid")
    assert_equal(wrong_profile.enabled, False)
    assert_equal(wrong_profile.blocked_reason, "host_profile_required")
    assert_equal(wrong_profile.command_id, 0x12)
    wrong_meta = windows_ime_custom_hid_warning_metadata(wrong_profile)
    assert_equal(wrong_meta["requires_host_profile"], "windows_us_custom_hid_ime")
    assert wrong_meta["warning"]

    disabled = build_windows_ime_custom_hid_plan(
        "KC_LANG1",
        host_profile="windows_us_custom_hid_ime",
        enabled=False,
        receiver_available=True,
    )
    assert_equal(disabled.blocked_reason, "custom_hid_route_disabled")

    no_receiver = build_windows_ime_custom_hid_plan(
        "KC_LANG1",
        host_profile="windows_us_custom_hid_ime",
        enabled=True,
        receiver_available=False,
    )
    assert_equal(no_receiver.blocked_reason, "receiver_required")
    no_receiver_meta = windows_ime_custom_hid_warning_metadata(no_receiver)
    assert_equal(no_receiver_meta["safe_to_send_without_receiver"], False)

    ready = build_windows_ime_custom_hid_plan(
        "KC_LANG1",
        host_profile="windows_us_custom_hid_ime",
        enabled=True,
        receiver_available=True,
    )
    assert_equal(ready.enabled, True)
    assert_equal(ready.blocked_reason, None)
    assert_equal(ready.command_id, 0x12)
    ready_meta = windows_ime_custom_hid_warning_metadata(ready)
    assert_equal(ready_meta["warning"], "")

    report = encode_windows_ime_custom_hid_report(ready.command_id, is_press=True, sequence_id=0x1234)
    assert_equal(len(report), 8)
    decoded = decode_windows_ime_custom_hid_report(report)
    assert_equal(decoded["command_id"], 0x12)
    assert_equal(decoded["is_press"], True)
    assert_equal(decoded["sequence_id"], 0x1234)

    release = encode_windows_ime_custom_hid_report(0x12, is_press=False, sequence_id=0x1235)
    assert_equal(decode_windows_ime_custom_hid_report(release)["is_press"], False)

    try:
        decode_windows_ime_custom_hid_report(report[:-1])
    except ValueError:
        pass
    else:
        raise AssertionError("short report should fail")

    corrupted = bytearray(report)
    corrupted[-1] ^= 0xFF
    try:
        decode_windows_ime_custom_hid_report(bytes(corrupted))
    except ValueError:
        pass
    else:
        raise AssertionError("bad checksum should fail")


if __name__ == "__main__":
    main()
