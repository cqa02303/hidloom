#!/usr/bin/env python3
"""Exercise Vial unlock through running viald/logicd sockets."""
from __future__ import annotations

import argparse
import json
import lzma
import socket
import struct
import time

REPORT_SIZE = 32
CMD_VIA_VIAL_PREFIX = 0xFE
CMD_VIAL_GET_UNLOCK_STATUS = 0x05
CMD_VIAL_GET_SIZE = 0x01
CMD_VIAL_GET_DEFINITION = 0x02
CMD_VIAL_UNLOCK_START = 0x06
CMD_VIAL_UNLOCK_POLL = 0x07
CMD_VIAL_LOCK = 0x08


def _exchange(path: str, payload: bytes) -> bytes:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        sock.connect(path)
        sock.sendall(payload.ljust(REPORT_SIZE, b"\x00"))
        return sock.recv(REPORT_SIZE)


def _matrix_event(path: str, kind: str, row: int, col: int) -> None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        sock.connect(path)
        sock.sendall(f"{kind}{row:X}{col:X}\n".encode("ascii"))


def _status(vial_path: str) -> bytes:
    return _exchange(vial_path, bytes([CMD_VIA_VIAL_PREFIX, CMD_VIAL_GET_UNLOCK_STATUS]))


def _definition(vial_path: str) -> dict:
    size_resp = _exchange(vial_path, bytes([CMD_VIA_VIAL_PREFIX, CMD_VIAL_GET_SIZE]))
    size = struct.unpack("<I", size_resp[:4])[0]
    payload = bytearray()
    block = 0
    while len(payload) < size:
        payload.extend(_exchange(
            vial_path,
            bytes([CMD_VIA_VIAL_PREFIX, CMD_VIAL_GET_DEFINITION]) + struct.pack("<I", block),
        ))
        block += 1
    return json.loads(lzma.decompress(bytes(payload[:size])))


def _parse_keys(value: str) -> list[tuple[int, int]]:
    keys = []
    for part in value.split(";"):
        row_s, col_s = part.split(",", 1)
        keys.append((int(row_s), int(col_s)))
    return keys


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vial", default="/tmp/viald_events.sock")
    parser.add_argument("--matrix", default="/tmp/matrix_events.sock")
    parser.add_argument("--keys")
    parser.add_argument("--polls", type=int, default=30)
    args = parser.parse_args()

    if args.keys:
        keys = _parse_keys(args.keys)
    else:
        definition = _definition(args.vial)
        keys = [tuple(item) for item in definition.get("vial", {}).get("unlockKeys", [])]

    _exchange(args.vial, bytes([CMD_VIA_VIAL_PREFIX, CMD_VIAL_LOCK]))
    before = _status(args.vial)
    assert before[0] == 0, before.hex()

    _exchange(args.vial, bytes([CMD_VIA_VIAL_PREFIX, CMD_VIAL_UNLOCK_START]))
    try:
        for row, col in keys:
            _matrix_event(args.matrix, "P", row, col)
        time.sleep(0.05)

        poll = b""
        for _ in range(args.polls):
            poll = _exchange(args.vial, bytes([CMD_VIA_VIAL_PREFIX, CMD_VIAL_UNLOCK_POLL]))
            if poll[0] == 1:
                break
        assert poll[0] == 1, poll.hex()
    finally:
        for row, col in keys:
            _matrix_event(args.matrix, "R", row, col)

    after = _status(args.vial)
    assert after[0] == 1, after.hex()

    print("before:", before[:8].hex())
    print("poll:", poll[:8].hex())
    print("after:", after[:8].hex())


if __name__ == "__main__":
    main()
