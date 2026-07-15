#!/usr/bin/env python3
"""Socket-level smoke test for the first-pass VialRGB implementation."""
from __future__ import annotations

import argparse
import socket
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vialrgb_effects import VIALRGB_SUPPORTED_EFFECTS  # noqa: E402

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


def set_mode(sock: socket.socket, mode: int, speed: int, h: int, s: int, v: int) -> None:
    exchange(sock, b"\x07\x41" + struct.pack("<HBBBB", mode, speed, h, s, v))


def direct_fastset(sock: socket.socket, first: int, pixels: list[tuple[int, int, int]]) -> None:
    payload = b"\x07\x42" + struct.pack("<HB", first, len(pixels))
    payload += b"".join(bytes(pixel) for pixel in pixels)
    exchange(sock, payload)


def read_mode(sock: socket.socket) -> tuple[int, int, int, int, int]:
    response = exchange(sock, b"\x08\x41")
    return struct.unpack("<HBBBB", response[2:8])


def read_supported_effects(sock: socket.socket) -> list[int]:
    effects: list[int] = []
    requested = 0
    while requested < 0xFFFF:
        response = exchange(sock, b"\x08\x42" + struct.pack("<H", requested))
        page: list[int] = []
        for idx in range(2, REPORT_SIZE, 2):
            value = struct.unpack("<H", response[idx:idx + 2])[0]
            if value == 0xFFFF:
                if page:
                    if page != sorted(page):
                        raise RuntimeError(f"VialRGB supported effects page is not sorted: {page}")
                    if effects and page[0] <= effects[-1]:
                        raise RuntimeError(f"VialRGB supported effects did not advance: previous={effects[-1]} page={page}")
                    effects.extend(page)
                return effects
            if value != 0:
                page.append(value)
        if not page:
            raise RuntimeError(f"VialRGB supported effects page did not include terminator after {requested}")
        if page != sorted(page):
            raise RuntimeError(f"VialRGB supported effects page is not sorted: {page}")
        if effects and page[0] <= effects[-1]:
            raise RuntimeError(f"VialRGB supported effects did not advance: previous={effects[-1]} page={page}")
        effects.extend(page)
        requested = page[-1]
    raise RuntimeError("VialRGB supported effects list did not terminate")


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test first-pass VialRGB protocol")
    parser.add_argument("--socket", default="/tmp/viald_events.sock")
    args = parser.parse_args()

    sock_path = Path(args.socket)
    if not sock_path.exists():
        raise SystemExit(f"socket not found: {sock_path}")

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(str(sock_path))

        info = exchange(sock, b"\x08\x40")
        assert info[:5] == b"\x08\x40\x01\x00\xff"

        assert read_supported_effects(sock) == list(VIALRGB_SUPPORTED_EFFECTS)

        led_count_resp = exchange(sock, b"\x08\x43")
        led_count = struct.unpack("<H", led_count_resp[2:4])[0]
        assert led_count > 0

        led_info = exchange(sock, b"\x08\x44\x00\x00")
        assert led_info[:2] == b"\x08\x44"
        assert led_info[4] == 0x04

        original = read_mode(sock)
        try:
            set_mode(sock, 2, 64, 0, 255, 96)
            assert read_mode(sock) == (2, 64, 0, 255, 96)

            set_mode(sock, 1, 64, 0, 0, 0)
            direct_fastset(sock, 0, [(0, 255, 32), (85, 255, 32)])
            assert read_mode(sock) == (1, 64, 0, 0, 0)

            set_mode(sock, 0, 64, 0, 0, 0)
            assert read_mode(sock) == (0, 64, 0, 0, 0)
        finally:
            set_mode(sock, *original)

    print("ok: first-pass VialRGB protocol responses are coherent")


if __name__ == "__main__":
    main()
