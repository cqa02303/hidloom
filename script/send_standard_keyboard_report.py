#!/usr/bin/env python3
"""Send one standard USB HID keyboard tap report to /dev/hidg0.

The current USB gadget uses /dev/hidg0 as a multi-report HID function, so the
default live report includes keyboard Report ID 1 before the 8-byte keyboard
payload. Use --no-report-id only when talking to an older dedicated keyboard
endpoint.
"""
from __future__ import annotations

import argparse
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.hid_report import HID_REPORT_ID_KEYBOARD, KEYCODE, HidState, add_hid_report_id  # noqa: E402
from usbd.hid_report_broker import KIND_KEYBOARD, KIND_US_SUB_KEYBOARD, encode_hid_report_request  # noqa: E402

DEFAULT_DEVICE = Path("/dev/hidg0")
DEFAULT_SOCKET = Path("/tmp/usbd_hid_reports.sock")


def _keycode_for_action(action: str) -> int:
    code = KEYCODE.get(action)
    if code is None:
        known = ", ".join(sorted(name for name in KEYCODE if name.startswith("KC_")))
        raise SystemExit(f"unsupported keyboard action: {action!r}\nknown actions: {known}")
    return code


def _reports_for_action(
    action: str,
    modifiers: list[str] | None = None,
    *,
    report_id: int | None = None,
) -> tuple[bytes, bytes]:
    modifier_codes = [_keycode_for_action(modifier) for modifier in (modifiers or [])]
    code = _keycode_for_action(action)
    state = HidState()
    for modifier_code in modifier_codes:
        state.press(modifier_code)
    state.press(code)
    press = state.build()
    state.release(code)
    for modifier_code in reversed(modifier_codes):
        state.release(modifier_code)
    release = state.build()
    if report_id is not None:
        press = add_hid_report_id(report_id, press)
        release = add_hid_report_id(report_id, release)
    return press, release


def _write_reports(device: Path, reports: list[bytes], hold_sec: float) -> None:
    with device.open("wb", buffering=0) as fh:
        fh.write(reports[0])
        if len(reports) > 1:
            time.sleep(hold_sec)
            fh.write(reports[1])


def _send_reports_to_socket(socket_path: Path, reports: list[bytes], hold_sec: float, *, kind: int = KIND_KEYBOARD) -> None:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        sock.sendto(encode_hid_report_request(kind, reports[0]), str(socket_path))
        if len(reports) > 1:
            time.sleep(hold_sec)
            sock.sendto(encode_hid_report_request(kind, reports[1]), str(socket_path))
    finally:
        sock.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", help="keyboard action such as KC_HENKAN, KC_MUHENKAN, KC_LANG1, or KC_LANG2")
    parser.add_argument("--modifier", action="append", default=[], help="modifier action to hold, e.g. KC_LALT")
    parser.add_argument("--device", type=Path, default=DEFAULT_DEVICE, help="standard keyboard HID device path")
    parser.add_argument("--socket", type=Path, default=DEFAULT_SOCKET, help="usbd HID report broker socket path")
    parser.add_argument(
        "--transport",
        choices=("auto", "socket", "direct"),
        default="auto",
        help="auto uses usbd socket when available, otherwise direct HID write",
    )
    parser.add_argument(
        "--broker-kind",
        choices=("keyboard", "us_sub_keyboard"),
        default="keyboard",
        help="canonical broker report kind for --transport socket",
    )
    parser.add_argument("--hold-sec", type=float, default=0.030, help="delay between press and release for tap mode")
    parser.add_argument("--press-only", action="store_true", help="send only the press report")
    parser.add_argument("--release-only", action="store_true", help="send only the release report")
    parser.add_argument("--dry-run", action="store_true", help="print report bytes without opening the HID device")
    parser.add_argument(
        "--report-id",
        type=lambda value: int(value, 0),
        default=HID_REPORT_ID_KEYBOARD,
        help="HID Report ID to prefix; default is 1 for the current multi-report /dev/hidg0",
    )
    parser.add_argument(
        "--no-report-id",
        action="store_true",
        help="send the legacy 8-byte keyboard payload without a Report ID",
    )
    args = parser.parse_args()

    if args.press_only and args.release_only:
        raise SystemExit("--press-only and --release-only are mutually exclusive")
    if args.hold_sec < 0:
        raise SystemExit("--hold-sec must be non-negative")
    if args.report_id < 1 or args.report_id > 255:
        raise SystemExit("--report-id must be in 1..255")

    report_id = None if args.no_report_id else args.report_id
    press_payload, release_payload = _reports_for_action(args.action, args.modifier, report_id=None)
    press, release = (
        (press_payload, release_payload)
        if report_id is None
        else (add_hid_report_id(report_id, press_payload), add_hid_report_id(report_id, release_payload))
    )
    if args.press_only:
        reports = [press]
        payload_reports = [press_payload]
    elif args.release_only:
        reports = [release]
        payload_reports = [release_payload]
    else:
        reports = [press, release]
        payload_reports = [press_payload, release_payload]

    if args.dry_run:
        for report in reports:
            print(report.hex())
        return

    use_socket = args.transport == "socket" or (args.transport == "auto" and args.socket.exists())
    if use_socket:
        if not args.socket.exists():
            raise SystemExit(f"usbd HID report broker socket is not available: {args.socket}")
        if args.no_report_id:
            raise SystemExit("--no-report-id is only valid with --transport direct")
        broker_kind_name = args.broker_kind
        broker_kind = KIND_US_SUB_KEYBOARD if broker_kind_name == "us_sub_keyboard" else KIND_KEYBOARD
        _send_reports_to_socket(args.socket, payload_reports, args.hold_sec, kind=broker_kind)
        print(
            f"sent {args.action} kind={broker_kind_name} "
            f"canonical_reports={[report.hex() for report in payload_reports]} -> {args.socket}"
        )
        return

    if not args.device.exists():
        raise SystemExit(f"standard keyboard HID device is not available: {args.device}")

    _write_reports(args.device, reports, args.hold_sec)
    print(f"sent {args.action} reports={[report.hex() for report in reports]} -> {args.device}")


if __name__ == "__main__":
    main()
