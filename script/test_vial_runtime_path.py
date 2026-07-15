#!/usr/bin/env python3
"""Exercise Vial SET through logicd's runtime key path on the Raspberry Pi."""
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


def vial_exchange(sock: socket.socket, payload: bytes) -> bytes:
    sock.sendall(payload.ljust(REPORT_SIZE, b"\x00"))
    return recv_exact(sock, REPORT_SIZE)


def keymap_read(sock: socket.socket, *, layer: int, row: int, col: int, rows: int, cols: int) -> int:
    offset = (layer * rows * cols + row * cols + col) * 2
    response = vial_exchange(sock, bytes([0x12]) + struct.pack(">HB", offset, 2))
    return struct.unpack(">H", response[4:6])[0]


def vial_set(sock: socket.socket, *, layer: int, row: int, col: int, keycode: int) -> None:
    vial_exchange(sock, bytes([0x05, layer, row, col]) + struct.pack(">H", keycode))


def read_vial_matrix_size(sock: socket.socket) -> tuple[int, int]:
    size_resp = vial_exchange(sock, b"\xfe\x01")
    size = struct.unpack("<I", size_resp[:4])[0]
    payload = bytearray()
    block = 0
    while len(payload) < size:
        payload.extend(vial_exchange(sock, b"\xfe\x02" + struct.pack("<I", block)))
        block += 1
    definition = json.loads(lzma.decompress(bytes(payload[:size])))
    matrix = definition.get("matrix", {})
    return int(matrix["rows"]), int(matrix["cols"])


def matrix_event(sock: socket.socket, kind: str, row: int, col: int) -> None:
    sock.sendall(bytes([ord(kind), ord(format(row, "X")), ord(format(col, "X")), 0]))


def read_key_event(sock: socket.socket) -> tuple[str, int, int]:
    packet = recv_exact(sock, 4)
    return chr(packet[0]), packet[1], packet[2]


def main() -> None:
    parser = argparse.ArgumentParser(description="Test Vial SET -> logicd -> key output path")
    parser.add_argument("--vial-socket", default="/tmp/viald_events.sock")
    parser.add_argument("--matrix-socket", default="/tmp/matrix_events.sock")
    parser.add_argument("--key-event-socket", default="/tmp/key_events.sock")
    parser.add_argument("--rows", type=int)
    parser.add_argument("--cols", type=int)
    parser.add_argument("--layer", type=int, default=0)
    parser.add_argument("--row", type=int, default=0)
    parser.add_argument("--col", type=int, default=1)
    parser.add_argument("--temporary-keycode", type=lambda s: int(s, 0), default=0x0004)
    parser.add_argument("--expected-original", type=lambda s: int(s, 0))
    args = parser.parse_args()

    for path in (args.vial_socket, args.matrix_socket, args.key_event_socket):
        if not Path(path).exists():
            raise SystemExit(f"socket not found: {path}")

    with (
        socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as vial,
        socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as matrix,
        socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as key_events,
    ):
        vial.settimeout(2.0)
        key_events.settimeout(2.0)
        vial.connect(args.vial_socket)
        matrix.connect(args.matrix_socket)
        key_events.connect(args.key_event_socket)
        rows, cols = (args.rows, args.cols) if args.rows and args.cols else read_vial_matrix_size(vial)

        original = keymap_read(
            vial,
            layer=args.layer,
            row=args.row,
            col=args.col,
            rows=rows,
            cols=cols,
        )
        if args.expected_original is not None and original != args.expected_original:
            raise SystemExit(
                f"unexpected original keycode at ({args.row},{args.col}): "
                f"got 0x{original:04x}, expected 0x{args.expected_original:04x}"
            )
        if original == args.temporary_keycode:
            raise SystemExit(
                f"temporary keycode already present at ({args.row},{args.col}): "
                f"0x{original:04x}"
            )

        pressed = False
        try:
            vial_set(
                vial,
                layer=args.layer,
                row=args.row,
                col=args.col,
                keycode=args.temporary_keycode,
            )
            remapped = keymap_read(
                vial,
                layer=args.layer,
                row=args.row,
                col=args.col,
                rows=rows,
                cols=cols,
            )
            if remapped != args.temporary_keycode:
                raise SystemExit(
                    f"remap readback mismatch: got 0x{remapped:04x}, "
                    f"expected 0x{args.temporary_keycode:04x}"
                )

            matrix_event(matrix, "P", args.row, args.col)
            pressed = True
            matrix_event(matrix, "R", args.row, args.col)
            pressed = False
            press = read_key_event(key_events)
            release = read_key_event(key_events)
            expected = args.temporary_keycode & 0xFF
            if press != ("P", expected, 0) or release != ("R", expected, 0):
                raise SystemExit(
                    "runtime output mismatch: "
                    f"press={press!r} release={release!r} expected keycode=0x{expected:02x}"
                )
        finally:
            if pressed:
                matrix_event(matrix, "R", args.row, args.col)
            vial_set(vial, layer=args.layer, row=args.row, col=args.col, keycode=original)

        restored = keymap_read(
            vial,
            layer=args.layer,
            row=args.row,
            col=args.col,
            rows=rows,
            cols=cols,
        )
        if restored != original:
            raise SystemExit(f"restore failed: got 0x{restored:04x}, expected 0x{original:04x}")

    print(
        "ok: Vial SET changed runtime key output and restored original "
        f"0x{original:04x}"
    )


if __name__ == "__main__":
    main()
