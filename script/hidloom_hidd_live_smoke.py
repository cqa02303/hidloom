#!/usr/bin/env python3
"""Live smoke for the hidloom-hidd broker owner.

This sends short, release-safe HID report frames through the canonical broker
socket. It is intended for on-device use while hidloom-hidd owns the socket.
"""
from __future__ import annotations

import argparse
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.hid_report import KEYCODE, HidState  # noqa: E402
from usbd.hid_report_broker import (  # noqa: E402
    KIND_CONSUMER,
    KIND_KEYBOARD,
    KIND_MOUSE,
    KIND_US_SUB_KEYBOARD,
    encode_hid_report_request,
)


def keyboard_payload(action: str, modifiers: list[str] | None = None) -> tuple[bytes, bytes]:
    state = HidState()
    for modifier in modifiers or []:
        state.press(KEYCODE[modifier])
    state.press(KEYCODE[action])
    press = state.build()
    state.release(KEYCODE[action])
    for modifier in reversed(modifiers or []):
        state.release(KEYCODE[modifier])
    return press, state.build()


def send_frame(sock: socket.socket, path: str, kind: int, payload: bytes, delay: float) -> None:
    sock.sendto(encode_hid_report_request(kind, payload), path)
    if delay > 0:
        time.sleep(delay)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", default="/tmp/usbd_hid_reports.sock")
    parser.add_argument("--delay", type=float, default=0.03)
    parser.add_argument("--malformed-count", type=int, default=0)
    parser.add_argument("--consumer-null-burst", type=int, default=0)
    args = parser.parse_args()

    frames: list[tuple[int, bytes, str]] = []
    for payload in keyboard_payload("KC_A"):
        frames.append((KIND_KEYBOARD, payload, "keyboard KC_A"))
    for payload in keyboard_payload("KC_A", ["KC_LSFT"]):
        frames.append((KIND_KEYBOARD, payload, "keyboard LSFT+KC_A"))
    for payload in keyboard_payload("KC_LANG1"):
        frames.append((KIND_US_SUB_KEYBOARD, payload, "us-sub KC_LANG1"))

    frames.extend(
        [
            (KIND_CONSUMER, bytes.fromhex("e900"), "consumer volume-up"),
            (KIND_CONSUMER, bytes.fromhex("0000"), "consumer null"),
            (KIND_MOUSE, bytes([0, 5, 0, 0]), "mouse dx"),
            (KIND_MOUSE, bytes([0, 0, 0, 0]), "mouse null"),
            (KIND_MOUSE, bytes([1, 0, 0, 0]), "mouse button1"),
            (KIND_MOUSE, bytes([0, 0, 0, 0]), "mouse button null"),
        ]
    )

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        malformed = bytearray(64)
        malformed[:4] = b"CQAU"
        malformed[4] = 1
        malformed[5] = KIND_CONSUMER
        malformed[6] = 2
        malformed[8:10] = b"\xe9\x00"
        for _ in range(max(0, args.malformed_count)):
            sock.sendto(bytes(malformed), args.socket)
        if args.malformed_count:
            print(f"sent: malformed frames count={args.malformed_count}")

        for kind, payload, label in frames:
            send_frame(sock, args.socket, kind, payload, args.delay)
            print(f"sent: {label} kind={kind} payload={payload.hex()}")
        for _ in range(max(0, args.consumer_null_burst)):
            sock.sendto(encode_hid_report_request(KIND_CONSUMER, bytes(2)), args.socket)
        if args.consumer_null_burst:
            print(f"sent: consumer null burst count={args.consumer_null_burst}")
    finally:
        sock.close()

    print(f"ok: sent {len(frames)} hidloom-hidd live smoke frame(s)")


if __name__ == "__main__":
    main()
