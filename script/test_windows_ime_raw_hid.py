#!/usr/bin/env python3
"""Tests for Windows IME Raw HID multiplex frames."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.windows_ime_custom_hid import encode_windows_ime_custom_hid_report  # noqa: E402
from logicd.windows_ime_raw_hid import (  # noqa: E402
    RAW_HID_MAGIC,
    RAW_HID_REPORT_SIZE,
    WINDOWS_IME_CHANNEL,
    decode_windows_ime_raw_hid_frame,
    encode_windows_ime_raw_hid_frame,
)


def main() -> None:
    payload = encode_windows_ime_custom_hid_report(0x20, is_press=True, sequence_id=7)
    frame = encode_windows_ime_raw_hid_frame(payload)
    assert len(frame) == RAW_HID_REPORT_SIZE
    assert frame[:4] == RAW_HID_MAGIC
    assert frame[4] == WINDOWS_IME_CHANNEL
    assert frame[5] == len(payload)
    assert frame[6:14] == payload
    assert frame[14:31] == bytes(17)

    decoded = decode_windows_ime_raw_hid_frame(frame)
    assert decoded["channel"] == "windows_ime"
    assert decoded["payload"] == payload
    assert decoded["decoded_payload"]["command_id"] == 0x20
    assert decoded["decoded_payload"]["is_press"] is True

    for bad in (frame[:-1], b"bad" + frame[3:]):
        try:
            decode_windows_ime_raw_hid_frame(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid frame should fail")

    corrupted = bytearray(frame)
    corrupted[31] ^= 0x01
    try:
        decode_windows_ime_raw_hid_frame(bytes(corrupted))
    except ValueError:
        pass
    else:
        raise AssertionError("bad checksum should fail")

    print("ok: Windows IME Raw HID multiplex frame")


if __name__ == "__main__":
    main()
