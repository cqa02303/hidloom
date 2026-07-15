#!/usr/bin/env python3
"""Preview implemented VialRGB effects on a running keyboard."""
from __future__ import annotations

import argparse
import socket
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vialrgb_effects import VIALRGB_PREVIEW_EFFECTS, VIALRGB_PREVIEW_GROUPS  # noqa: E402

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
    sock.sendall(payload[:REPORT_SIZE].ljust(REPORT_SIZE, b"\x00"))
    return recv_exact(sock, REPORT_SIZE)


def set_mode(sock: socket.socket, mode: int, speed: int, h: int, s: int, v: int) -> None:
    exchange(sock, b"\x07\x41" + struct.pack("<HBBBB", mode, speed, h, s, v))


def read_mode(sock: socket.socket) -> tuple[int, int, int, int, int]:
    response = exchange(sock, b"\x08\x41")
    return struct.unpack("<HBBBB", response[2:8])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview VialRGB effects in sequence")
    parser.add_argument("--socket", default="/tmp/viald_events.sock")
    parser.add_argument("--seconds", type=float, default=6.0)
    parser.add_argument("--group", choices=sorted(VIALRGB_PREVIEW_GROUPS), action="append")
    parser.add_argument("--restore", action="store_true", help="restore the original VialRGB mode at the end")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sock_path = Path(args.socket)
    if not sock_path.exists():
        raise SystemExit(f"socket not found: {sock_path}")

    selected = VIALRGB_PREVIEW_EFFECTS
    if args.group:
        allowed = set().union(*(VIALRGB_PREVIEW_GROUPS[name] for name in args.group))
        selected = [effect for effect in VIALRGB_PREVIEW_EFFECTS if effect[0] in allowed]

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(str(sock_path))
        original = read_mode(sock)
        try:
            for mode, name, speed, h, s, v in selected:
                print(f"mode={mode:2d} {name} speed={speed} hsv=({h},{s},{v})", flush=True)
                set_mode(sock, mode, speed, h, s, v)
                time.sleep(max(0.2, args.seconds))
        finally:
            if args.restore:
                set_mode(sock, *original)
                print(f"restored mode={original[0]} speed={original[1]} hsv={original[2:]}", flush=True)


if __name__ == "__main__":
    main()
