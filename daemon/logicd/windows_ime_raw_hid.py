"""Raw HID multiplex frame helpers for Windows IME custom HID reports."""
from __future__ import annotations

from typing import Final

from .windows_ime_custom_hid import REPORT_SIZE as WINDOWS_IME_REPORT_SIZE
from .windows_ime_custom_hid import decode_windows_ime_custom_hid_report

RAW_HID_REPORT_SIZE: Final[int] = 32
RAW_HID_MAGIC: Final[bytes] = b"CQA1"
WINDOWS_IME_CHANNEL: Final[int] = 0x10


def _checksum(first_31: bytes) -> int:
    value = 0
    for byte in first_31:
        value ^= byte
    return value & 0xFF


def encode_windows_ime_raw_hid_frame(payload: bytes) -> bytes:
    data = bytes(payload)
    if len(data) != WINDOWS_IME_REPORT_SIZE:
        raise ValueError(f"Windows IME payload must be {WINDOWS_IME_REPORT_SIZE} bytes, got {len(data)}")
    # Validate the inner report before wrapping it for Raw HID transport.
    decode_windows_ime_custom_hid_report(data)
    first = RAW_HID_MAGIC + bytes([WINDOWS_IME_CHANNEL, len(data)]) + data + bytes(17)
    return first + bytes([_checksum(first)])


def decode_windows_ime_raw_hid_frame(frame: bytes) -> dict[str, object]:
    data = bytes(frame)
    if len(data) != RAW_HID_REPORT_SIZE:
        raise ValueError(f"Raw HID frame must be {RAW_HID_REPORT_SIZE} bytes, got {len(data)}")
    if data[:4] != RAW_HID_MAGIC:
        raise ValueError("invalid Raw HID frame magic")
    if data[4] != WINDOWS_IME_CHANNEL:
        raise ValueError("unsupported Raw HID frame channel")
    payload_len = data[5]
    if payload_len != WINDOWS_IME_REPORT_SIZE:
        raise ValueError(f"unsupported Windows IME payload length: {payload_len}")
    if any(data[14:31]):
        raise ValueError("Raw HID frame reserved bytes must be zero")
    if _checksum(data[:31]) != data[31]:
        raise ValueError("invalid Raw HID frame checksum")
    payload = data[6:14]
    return {
        "channel": "windows_ime",
        "payload": payload,
        "decoded_payload": decode_windows_ime_custom_hid_report(payload),
    }
