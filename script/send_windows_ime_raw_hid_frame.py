#!/usr/bin/env python3
"""Send a Windows IME Raw HID multiplex frame to usbd."""
from __future__ import annotations

import argparse
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.windows_ime_custom_hid import (  # noqa: E402
    COMMAND_BY_ACTION,
    encode_windows_ime_custom_hid_report,
    normalize_action,
)
from logicd.windows_ime_raw_hid import encode_windows_ime_raw_hid_frame  # noqa: E402

DEFAULT_SOCKET = Path("/tmp/usbd_windows_ime.sock")


def _command_id_for_action(action: str) -> int:
    normalized = normalize_action(action)
    command_id = COMMAND_BY_ACTION.get(normalized)
    if command_id is None:
        known = ", ".join(sorted(COMMAND_BY_ACTION))
        raise SystemExit(f"unsupported Windows IME custom HID action: {action!r}\nknown actions: {known}")
    return command_id


def _send_frame(socket_path: Path, frame: bytes) -> None:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        sock.sendto(frame, str(socket_path))
    finally:
        sock.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", help="IME action such as KC_HENKAN, KC_MUHENKAN, KC_LANG1, or KC_LANG2")
    parser.add_argument("--socket", type=Path, default=DEFAULT_SOCKET, help="usbd Windows IME socket path")
    parser.add_argument("--sequence-id", type=lambda value: int(value, 0), default=1, help="16-bit sequence id")
    parser.add_argument("--hold-sec", type=float, default=0.030, help="delay between press and release for tap mode")
    parser.add_argument("--press-only", action="store_true", help="send only the press frame")
    parser.add_argument("--release-only", action="store_true", help="send only the release frame")
    args = parser.parse_args()

    if args.press_only and args.release_only:
        raise SystemExit("--press-only and --release-only are mutually exclusive")
    if args.hold_sec < 0:
        raise SystemExit("--hold-sec must be non-negative")
    if not args.socket.exists():
        raise SystemExit(f"usbd Windows IME socket is not available: {args.socket}")

    command_id = _command_id_for_action(args.action)
    if args.release_only:
        payloads = [encode_windows_ime_custom_hid_report(command_id, is_press=False, sequence_id=args.sequence_id)]
    elif args.press_only:
        payloads = [encode_windows_ime_custom_hid_report(command_id, is_press=True, sequence_id=args.sequence_id)]
    else:
        payloads = [
            encode_windows_ime_custom_hid_report(command_id, is_press=True, sequence_id=args.sequence_id),
            encode_windows_ime_custom_hid_report(command_id, is_press=False, sequence_id=(args.sequence_id + 1) & 0xFFFF),
        ]

    frame = encode_windows_ime_raw_hid_frame(payloads[0])
    _send_frame(args.socket, frame)
    print(f"sent {args.action} {'press' if payloads[0][3] else 'release'} {frame.hex()} -> {args.socket}")
    if len(payloads) > 1:
        time.sleep(args.hold_sec)
        frame = encode_windows_ime_raw_hid_frame(payloads[1])
        _send_frame(args.socket, frame)
        print(f"sent {args.action} release {frame.hex()} -> {args.socket}")


if __name__ == "__main__":
    main()
