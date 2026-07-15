#!/usr/bin/env python3
"""Set one key through viald and verify keymap readback."""
from __future__ import annotations

import argparse
import socket
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from viald.keycode_codec import KeycodeCodec  # noqa: E402

REPORT_SIZE = 32
CMD_VIA_SET_KEYCODE = 0x05
CMD_VIA_KEYMAP_GET_BUFFER = 0x12


def exchange(sock_path: str, payload: bytes) -> bytes:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(sock_path)
        sock.sendall(payload[:REPORT_SIZE].ljust(REPORT_SIZE, b"\x00"))
        data = b""
        while len(data) < REPORT_SIZE:
            chunk = sock.recv(REPORT_SIZE - len(data))
            if not chunk:
                break
            data += chunk
    return data.ljust(REPORT_SIZE, b"\x00")


def read_keycode(sock_path: str, layer: int, row: int, col: int, rows: int, cols: int) -> int:
    offset = (layer * rows * cols + row * cols + col) * 2
    packet = bytes([CMD_VIA_KEYMAP_GET_BUFFER]) + struct.pack(">HB", offset, 2)
    response = exchange(sock_path, packet)
    return struct.unpack(">H", response[4:6])[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Set and read back a Vial keycode through viald")
    parser.add_argument("action", help="internal action name, e.g. RGB_TOG or KC_A")
    parser.add_argument("--socket", default="/tmp/viald_events.sock")
    parser.add_argument("--layer", type=int, default=0)
    parser.add_argument("--row", type=int, default=0)
    parser.add_argument("--col", type=int, default=1)
    parser.add_argument("--rows", type=int, default=10)
    parser.add_argument("--cols", type=int, default=10)
    args = parser.parse_args()

    codec = KeycodeCodec()
    keycode = codec.action_to_vial(args.action)
    if keycode == 0 and args.action != "KC_NONE":
        raise SystemExit(f"unsupported action: {args.action}")

    before = read_keycode(args.socket, args.layer, args.row, args.col, args.rows, args.cols)
    set_packet = bytes([CMD_VIA_SET_KEYCODE, args.layer, args.row, args.col]) + struct.pack(">H", keycode)
    exchange(args.socket, set_packet)
    after = read_keycode(args.socket, args.layer, args.row, args.col, args.rows, args.cols)

    decoded = codec.vial_to_action(after)
    print({
        "target": args.action,
        "target_keycode": f"0x{keycode:04x}",
        "before_keycode": f"0x{before:04x}",
        "after_keycode": f"0x{after:04x}",
        "after_action": decoded,
        "ok": after == keycode,
    })
    if after != keycode:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
