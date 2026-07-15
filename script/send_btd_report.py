#!/usr/bin/env python3
"""Send a test HID report to the btd Unix socket."""
from __future__ import annotations

import argparse
import socket

DEFAULT_SOCKET = "/tmp/btd_events.sock"


def parse_hex_report(text: str) -> bytes:
    cleaned = text.replace(" ", "").replace(":", "").replace(",", "")
    if len(cleaned) % 2 != 0:
        raise ValueError("hex report must contain an even number of digits")
    return bytes.fromhex(cleaned)


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a HID report candidate to btd")
    parser.add_argument("report", nargs="?", default="0000000000000000", help="hex bytes, default is keyboard null report")
    parser.add_argument("--socket", default=DEFAULT_SOCKET)
    args = parser.parse_args()

    payload = parse_hex_report(args.report)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(2.0)
        sock.connect(args.socket)
        sock.sendall(payload)
    print(f"sent {len(payload)} bytes to {args.socket}: {payload.hex()}")


if __name__ == "__main__":
    main()
