#!/usr/bin/env python3
"""Stage 1 socket-level smoke test for viald.

This validates viald's fixed-size framing and echo behavior without requiring
USB gadget hardware. It intentionally tests viald directly; the real
/dev/hidg1 <-> usbd <-> viald bridge still needs an on-device integration test.
"""
from __future__ import annotations

import argparse
import socket
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


def make_packet(seed: int) -> bytes:
    return bytes((seed + i) % 256 for i in range(REPORT_SIZE))


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test viald Stage 1 echo transport")
    parser.add_argument("--socket", default="/tmp/viald_events.sock", help="viald Unix socket path")
    parser.add_argument("--count", type=int, default=8, help="number of packets to send")
    args = parser.parse_args()

    sock_path = Path(args.socket)
    if not sock_path.exists():
        raise SystemExit(f"socket not found: {sock_path}")

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(str(sock_path))
        for i in range(args.count):
            request = make_packet(i * 17)
            sock.sendall(request)
            response = recv_exact(sock, REPORT_SIZE)
            if response != request:
                raise SystemExit(f"packet {i}: echo mismatch")

    print(f"ok: {args.count} packet(s) echoed with {REPORT_SIZE}-byte framing")


if __name__ == "__main__":
    main()
