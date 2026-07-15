#!/usr/bin/env python3
"""Print VialRGB supported effect IDs from a running viald socket."""
from __future__ import annotations

import argparse
import socket
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vialrgb_effects import VIALRGB_EFFECTS  # noqa: E402

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Print VialRGB supported effects from viald")
    parser.add_argument("--socket", default="/tmp/viald_events.sock")
    args = parser.parse_args()

    sock_path = Path(args.socket)
    if not sock_path.exists():
        raise SystemExit(f"socket not found: {sock_path}")

    effects = {0}
    max_effect = 0
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(str(sock_path))
        while max_effect < 0xFFFF:
            response = exchange(sock, b"\x08\x42" + struct.pack("<H", max_effect))
            payload = response[2:]
            for idx in range(0, len(payload), 2):
                value = struct.unpack("<H", payload[idx:idx + 2])[0]
                if value != 0xFFFF:
                    effects.add(value)
                max_effect = max(max_effect, value)

    for effect in sorted(effects):
        print(f"{effect}: {VIALRGB_EFFECTS.get(effect, 'unknown')}")


if __name__ == "__main__":
    main()
