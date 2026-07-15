"""Dry-run helpers for Windows US IME custom HID routing."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

REPORT_MAGIC: Final[int] = 0xC1
REPORT_VERSION: Final[int] = 0x01
REPORT_SIZE: Final[int] = 8

COMMAND_BY_ACTION: Final[dict[str, int]] = {
    "KC_INT4": 0x10,
    "INT4": 0x10,
    "KC_INT5": 0x11,
    "INT5": 0x11,
    "KC_LANG1": 0x12,
    "KC_LANGUAGE_1": 0x12,
    "LANG1": 0x12,
    "KC_LANG2": 0x13,
    "KC_LANGUAGE_2": 0x13,
    "LANG2": 0x13,
    "KC_HENK": 0x20,
    "KC_HENKAN": 0x20,
    "KC_MHEN": 0x21,
    "KC_MUHENKAN": 0x21,
}

WARNING_TEXT_BY_REASON: Final[dict[str, str]] = {
    "host_profile_required": "Enable the windows_us_custom_hid_ime host profile before using the custom HID route.",
    "custom_hid_route_disabled": "Custom HID IME routing is disabled for this profile.",
    "receiver_required": "A Windows companion receiver must be available before custom HID IME routing is enabled.",
    "not_custom_hid_action": "This action is not routed through the Windows IME custom HID path.",
}


@dataclass(frozen=True)
class WindowsImeCustomHidPlan:
    route: str
    action: str
    enabled: bool
    blocked_reason: str | None = None
    command_id: int | None = None
    report_size: int = REPORT_SIZE


def normalize_action(action: str) -> str:
    return str(action or "").strip().upper()


def is_windows_ime_custom_hid_action(action: str) -> bool:
    return normalize_action(action) in COMMAND_BY_ACTION


def build_windows_ime_custom_hid_plan(
    action: str,
    *,
    host_profile: str | None = None,
    enabled: bool = False,
    receiver_available: bool = False,
) -> WindowsImeCustomHidPlan:
    normalized = normalize_action(action)
    command_id = COMMAND_BY_ACTION.get(normalized)
    if command_id is None:
        return WindowsImeCustomHidPlan("keyboard", normalized, False, "not_custom_hid_action")
    if str(host_profile or "").strip().lower() != "windows_us_custom_hid_ime":
        return WindowsImeCustomHidPlan("custom_hid", normalized, False, "host_profile_required", command_id)
    if not enabled:
        return WindowsImeCustomHidPlan("custom_hid", normalized, False, "custom_hid_route_disabled", command_id)
    if not receiver_available:
        return WindowsImeCustomHidPlan("custom_hid", normalized, False, "receiver_required", command_id)
    return WindowsImeCustomHidPlan("custom_hid", normalized, True, None, command_id)


def windows_ime_custom_hid_warning_metadata(plan: WindowsImeCustomHidPlan) -> dict[str, object]:
    reason = plan.blocked_reason
    return {
        "family": "windows_ime_custom_hid",
        "action": plan.action,
        "route": plan.route,
        "enabled": plan.enabled,
        "blocked_reason": reason,
        "warning": WARNING_TEXT_BY_REASON.get(reason or "", "") if not plan.enabled else "",
        "requires_host_profile": "windows_us_custom_hid_ime" if plan.route == "custom_hid" else None,
        "requires_custom_hid_endpoint": plan.route == "custom_hid",
        "requires_windows_receiver": plan.route == "custom_hid",
        "safe_to_send_without_receiver": False if plan.route == "custom_hid" else None,
    }


def _checksum(first_seven: bytes) -> int:
    value = 0
    for byte in first_seven:
        value ^= byte
    return value & 0xFF


def encode_windows_ime_custom_hid_report(command_id: int, *, is_press: bool, sequence_id: int = 0) -> bytes:
    if not 0 <= int(command_id) <= 0xFF:
        raise ValueError(f"command_id out of range: {command_id!r}")
    seq = int(sequence_id) & 0xFFFF
    first = bytes([
        REPORT_MAGIC,
        REPORT_VERSION,
        int(command_id) & 0xFF,
        0x01 if is_press else 0x00,
        seq & 0xFF,
        (seq >> 8) & 0xFF,
        0x00,
    ])
    return first + bytes([_checksum(first)])


def decode_windows_ime_custom_hid_report(report: bytes) -> dict[str, int | bool]:
    data = bytes(report)
    if len(data) != REPORT_SIZE:
        raise ValueError(f"report length must be {REPORT_SIZE}, got {len(data)}")
    if data[0] != REPORT_MAGIC:
        raise ValueError("invalid report magic")
    if data[1] != REPORT_VERSION:
        raise ValueError("unsupported report version")
    if _checksum(data[:7]) != data[7]:
        raise ValueError("invalid report checksum")
    return {
        "command_id": data[2],
        "is_press": bool(data[3] & 0x01),
        "sequence_id": data[4] | (data[5] << 8),
        "reserved": data[6],
    }
