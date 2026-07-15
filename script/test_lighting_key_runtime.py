#!/usr/bin/env python3
"""Runtime smoke test for Lighting key actions through logicd."""
from __future__ import annotations

import argparse
import json
import socket
import struct
import time
from pathlib import Path

REPORT_SIZE = 32


def json_request(sock_path: str, msg: dict) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(sock_path)
        sock.sendall((json.dumps(msg) + "\n").encode())
        data = b""
        while not data.endswith(b"\n"):
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
    return json.loads(data.decode()) if data else {}


def vial_exchange(sock_path: str, payload: bytes) -> bytes:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(sock_path)
        sock.sendall(payload.ljust(REPORT_SIZE, b"\x00"))
        return sock.recv(REPORT_SIZE)


def read_mode(sock_path: str) -> tuple[int, int, int, int, int]:
    response = vial_exchange(sock_path, b"\x08\x41")
    return struct.unpack("<HBBBB", response[2:8])


def set_mode(sock_path: str, mode: tuple[int, int, int, int, int]) -> None:
    vial_exchange(sock_path, b"\x07\x41" + struct.pack("<HBBBB", *mode))


def send_matrix_event(sock_path: str, kind: str, row: int, col: int) -> None:
    packet = bytes([ord(kind), ord(f"{row:X}"), ord(f"{col:X}"), ord("\n")])
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(sock_path)
        sock.sendall(packet)


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test RGB_VAI through runtime keymap")
    parser.add_argument("--ctrl", default="/tmp/ctrl_events.sock")
    parser.add_argument("--matrix", default="/tmp/matrix_events.sock")
    parser.add_argument("--vial", default="/tmp/viald_events.sock")
    parser.add_argument("--row", type=int, default=7)
    parser.add_argument("--col", type=int, default=0)
    args = parser.parse_args()

    for path in (args.ctrl, args.matrix, args.vial):
        if not Path(path).exists():
            raise SystemExit(f"socket not found: {path}")

    key = f"{args.row},{args.col}"
    keymap = json_request(args.ctrl, {"t": "G"})
    original = keymap.get("layers", [{}])[0].get(key, "KC_NONE")
    before = read_mode(args.vial)
    baseline = (2, before[1], before[2], before[3], 64)

    pressed = False
    try:
        set_mode(args.vial, baseline)
        json_request(args.ctrl, {"t": "M", "l": 0, "r": args.row, "c": args.col, "a": "RGB_VAI"})
        send_matrix_event(args.matrix, "P", args.row, args.col)
        pressed = True
        time.sleep(0.5)
        after = read_mode(args.vial)
        print({"before": baseline, "after": after, "original": original})
        if after[4] <= baseline[4]:
            raise SystemExit(f"expected value brightness to increase, got before={baseline}, after={after}")
    finally:
        if pressed:
            send_matrix_event(args.matrix, "R", args.row, args.col)
        json_request(args.ctrl, {"t": "M", "l": 0, "r": args.row, "c": args.col, "a": original})
        set_mode(args.vial, before)


if __name__ == "__main__":
    main()
