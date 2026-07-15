#!/usr/bin/env python3
"""Exercise VialRGB mode save/read over the viald socket."""
from __future__ import annotations

import argparse
import socket
import struct
import time
from pathlib import Path

REPORT_SIZE = 32


def recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise RuntimeError("socket closed before full response")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def exchange(sock: socket.socket, payload: bytes) -> bytes:
    sock.sendall(payload.ljust(REPORT_SIZE, b"\x00"))
    return recv_exact(sock, REPORT_SIZE)


def read_mode(sock: socket.socket) -> tuple[int, int, int, int, int]:
    response = exchange(sock, b"\x08\x41")
    return struct.unpack("<HBBBB", response[2:8])


def set_mode(sock: socket.socket, mode: tuple[int, int, int, int, int]) -> None:
    exchange(sock, b"\x07\x41" + struct.pack("<HBBBB", *mode))


def main() -> None:
    parser = argparse.ArgumentParser(description="Set/save/read VialRGB mode")
    parser.add_argument("--socket", default="/tmp/viald_events.sock")
    parser.add_argument("--set", nargs=5, type=int, metavar=("MODE", "SPEED", "H", "S", "V"))
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--expect", nargs=5, type=int, metavar=("MODE", "SPEED", "H", "S", "V"))
    parser.add_argument("--sleep", type=float, default=0.0)
    args = parser.parse_args()

    sock_path = Path(args.socket)
    if not sock_path.exists():
        raise SystemExit(f"socket not found: {sock_path}")

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(str(sock_path))
        if args.set is not None:
            set_mode(sock, tuple(args.set))
        if args.save:
            exchange(sock, b"\x09")
        if args.sleep:
            time.sleep(args.sleep)
        mode = read_mode(sock)

    print(mode)
    if args.expect is not None and mode != tuple(args.expect):
        raise SystemExit(f"expected {tuple(args.expect)}, got {mode}")


if __name__ == "__main__":
    main()
