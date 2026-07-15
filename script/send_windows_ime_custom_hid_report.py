#!/usr/bin/env python3
"""Send a Windows IME custom HID report to the opt-in /dev/hidg4 endpoint."""
from __future__ import annotations

import argparse
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

DEFAULT_DEVICE = Path("/dev/hidg4")


def _command_id_for_action(action: str) -> int:
    normalized = normalize_action(action)
    command_id = COMMAND_BY_ACTION.get(normalized)
    if command_id is None:
        known = ", ".join(sorted(COMMAND_BY_ACTION))
        raise SystemExit(f"unsupported Windows IME custom HID action: {action!r}\nknown actions: {known}")
    return command_id


def _write_report(device: Path, report: bytes) -> None:
    with device.open("wb", buffering=0) as fh:
        fh.write(report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", help="IME action such as KC_HENKAN, KC_MUHENKAN, KC_LANG1, or KC_LANG2")
    parser.add_argument("--device", type=Path, default=DEFAULT_DEVICE, help="custom HID device path")
    parser.add_argument("--sequence-id", type=lambda value: int(value, 0), default=1, help="16-bit sequence id")
    parser.add_argument("--hold-sec", type=float, default=0.030, help="delay between press and release for tap mode")
    parser.add_argument("--press-only", action="store_true", help="send only the press report")
    parser.add_argument("--release-only", action="store_true", help="send only the release report")
    args = parser.parse_args()

    if args.press_only and args.release_only:
        raise SystemExit("--press-only and --release-only are mutually exclusive")
    if args.hold_sec < 0:
        raise SystemExit("--hold-sec must be non-negative")

    command_id = _command_id_for_action(args.action)
    if args.release_only:
        reports = [encode_windows_ime_custom_hid_report(command_id, is_press=False, sequence_id=args.sequence_id)]
    elif args.press_only:
        reports = [encode_windows_ime_custom_hid_report(command_id, is_press=True, sequence_id=args.sequence_id)]
    else:
        reports = [
            encode_windows_ime_custom_hid_report(command_id, is_press=True, sequence_id=args.sequence_id),
            encode_windows_ime_custom_hid_report(command_id, is_press=False, sequence_id=(args.sequence_id + 1) & 0xFFFF),
        ]

    if not args.device.exists():
        raise SystemExit(f"custom HID device is not available: {args.device}")

    _write_report(args.device, reports[0])
    print(f"sent {args.action} {'press' if reports[0][3] else 'release'} {reports[0].hex()} -> {args.device}")
    if len(reports) > 1:
        time.sleep(args.hold_sec)
        _write_report(args.device, reports[1])
        print(f"sent {args.action} release {reports[1].hex()} -> {args.device}")


if __name__ == "__main__":
    main()
