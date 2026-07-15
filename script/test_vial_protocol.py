#!/usr/bin/env python3
"""Socket-level smoke test for Stage 2 Vial protocol responses."""
from __future__ import annotations

import argparse
import json
import lzma
import socket
import struct
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test Stage 2 Vial protocol")
    parser.add_argument("--socket", default="/tmp/viald_events.sock")
    args = parser.parse_args()

    sock_path = Path(args.socket)
    if not sock_path.exists():
        raise SystemExit(f"socket not found: {sock_path}")

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(str(sock_path))

        version = exchange(sock, b"\x01")
        assert version[:3] == b"\x01\x00\x09"

        identity = exchange(sock, b"\xfe\x00")
        vial_protocol, uid = struct.unpack("<IQ", identity[:12])
        assert vial_protocol == 5
        assert uid > 0

        qmk_settings = exchange(sock, b"\xfe\x09\x00\x00")
        assert [struct.unpack("<H", qmk_settings[idx:idx + 2])[0] for idx in range(0, 8, 2)] == [2, 7, 23, 0xFFFF]

        dynamic_counts = exchange(sock, b"\xfe\x0d\x00")
        assert dynamic_counts[0] >= 1
        assert dynamic_counts[1] >= 1
        assert dynamic_counts[2] >= 1
        assert dynamic_counts[3] == 0

        size_resp = exchange(sock, b"\xfe\x01")
        size = struct.unpack("<I", size_resp[:4])[0]
        payload = bytearray()
        block = 0
        while len(payload) < size:
            payload.extend(exchange(sock, b"\xfe\x02" + struct.pack("<I", block)))
            block += 1
        definition = json.loads(lzma.decompress(bytes(payload[:size])))
        assert definition["name"] in {
            "CQA02303v5 Keyboard",
            "CQA02303v5-40 Touch Panel (waveshare-8.8)",
            "CQA02303v5-40 Touch Panel (osoyoo-4.3)",
        }
        assert definition["uid"] == uid

        layer_count = exchange(sock, b"\x11")
        assert layer_count[0] == 0x11
        assert layer_count[1] >= 1

        layout_options = exchange(sock, b"\x02\x02")
        assert layout_options[:6] == b"\x02\x02\x00\x00\x00\x00"

        unlock = exchange(sock, b"\xfe\x05")
        assert unlock[0] in (0, 1)
        assert unlock[1] in (0, 1)
        if unlock[0] == 0:
            unlock_keys = definition.get("vial", {}).get("unlockKeys", [])
            expected = bytes(value for pair in unlock_keys[:15] for value in pair)
            assert unlock[2:2 + len(expected)] == expected

    print("ok: Stage 2 Vial protocol responses are coherent")


if __name__ == "__main__":
    main()
