#!/usr/bin/env python3
"""Exercise Vial matrix state through running logicd/viald sockets."""
from __future__ import annotations

import argparse
import json
import socket
import time

REPORT_SIZE = 32
CMD_VIA_GET_KEYBOARD_VALUE = 0x02
VIA_SWITCH_MATRIX_STATE = 0x03


def _ctrl_query(path: str) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        sock.connect(path)
        sock.sendall(b'{"t":"K"}\n')
        data = b""
        while not data.endswith(b"\n"):
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
    return json.loads(data.decode("utf-8"))


def _vial_matrix(path: str) -> bytes:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        sock.connect(path)
        sock.sendall(bytes([CMD_VIA_GET_KEYBOARD_VALUE, VIA_SWITCH_MATRIX_STATE]).ljust(REPORT_SIZE, b"\x00"))
        return sock.recv(REPORT_SIZE)


def _matrix_event(path: str, kind: str, row: int, col: int) -> None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        sock.connect(path)
        sock.sendall(f"{kind}{row:X}{col:X}\n".encode("ascii"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ctrl", default="/tmp/ctrl_events.sock")
    parser.add_argument("--matrix", default="/tmp/matrix_events.sock")
    parser.add_argument("--vial", default="/tmp/viald_events.sock")
    parser.add_argument("--row", type=int, default=9)
    parser.add_argument("--col", type=int, default=9)
    args = parser.parse_args()

    before = _ctrl_query(args.ctrl)
    pressed = False
    try:
        _matrix_event(args.matrix, "P", args.row, args.col)
        pressed = True
        time.sleep(0.05)
        during = _ctrl_query(args.ctrl)
        vial = _vial_matrix(args.vial)
    finally:
        if pressed:
            _matrix_event(args.matrix, "R", args.row, args.col)
    time.sleep(0.05)
    after = _ctrl_query(args.ctrl)

    expected = [args.row, args.col]
    assert expected in during.get("pressed", []), during
    assert expected not in after.get("pressed", []), after
    assert vial[:2] == bytes([CMD_VIA_GET_KEYBOARD_VALUE, VIA_SWITCH_MATRIX_STATE]), vial.hex()

    print("before:", before)
    print("during:", during)
    print("vial:", vial.hex())
    print("after:", after)


if __name__ == "__main__":
    main()
