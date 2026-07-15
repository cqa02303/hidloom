#!/usr/bin/env python3
"""Temporarily remap one matrix key and inject a matrix tap event."""
from __future__ import annotations

import argparse
import json
import socket
import time
from pathlib import Path


def _hex_digit(value: int) -> int:
    if not 0 <= value <= 15:
        raise ValueError(f"matrix row/col must be in 0..15, got {value}")
    return ord(f"{value:X}")


def json_request(sock_path: str, msg: dict) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(3.0)
        sock.connect(sock_path)
        sock.sendall((json.dumps(msg) + "\n").encode())
        data = b""
        while not data.endswith(b"\n"):
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
    return json.loads(data.decode()) if data else {}


def send_matrix_event(sock_path: str, kind: str, row: int, col: int) -> None:
    if kind not in {"P", "R"}:
        raise ValueError(f"kind must be P or R, got {kind!r}")
    packet = bytes([ord(kind), _hex_digit(row), _hex_digit(col), 0x00])
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(3.0)
        sock.connect(sock_path)
        sock.sendall(packet)


def set_action(ctrl_sock: str, layer: int, row: int, col: int, action: str) -> dict:
    return json_request(ctrl_sock, {"t": "M", "l": layer, "r": row, "c": col, "a": action})


def get_action(ctrl_sock: str, layer: int, row: int, col: int) -> str:
    keymap = json_request(ctrl_sock, {"t": "G"})
    layers = keymap.get("layers", [])
    if not isinstance(layers, list) or layer >= len(layers):
        return "KC_NONE"
    layer_map = layers[layer]
    if not isinstance(layer_map, dict):
        return "KC_NONE"
    return str(layer_map.get(f"{row},{col}", "KC_NONE"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Temporarily assign ACTION to layer,row,col and inject P/R on matrix_events.sock",
    )
    parser.add_argument("action", help="Action string, e.g. BT_STATUS, RGB_TOG, KC_A, LT(1,KC_ESC)")
    parser.add_argument("--layer", type=int, default=0)
    parser.add_argument("--row", type=int, default=7)
    parser.add_argument("--col", type=int, default=0)
    parser.add_argument("--hold", type=float, default=0.08, help="seconds between press and release")
    parser.add_argument("--ctrl", default="/tmp/ctrl_events.sock")
    parser.add_argument("--matrix", default="/tmp/matrix_events.sock")
    parser.add_argument("--no-restore", action="store_true", help="leave the temporary action assigned")
    args = parser.parse_args()

    for path in (args.ctrl, args.matrix):
        if not Path(path).exists():
            raise SystemExit(f"socket not found: {path}")

    original = get_action(args.ctrl, args.layer, args.row, args.col)
    print({
        "layer": args.layer,
        "row": args.row,
        "col": args.col,
        "original": original,
        "temporary": args.action,
    })

    try:
        resp = set_action(args.ctrl, args.layer, args.row, args.col, args.action)
        if resp.get("result") != "ok":
            raise SystemExit(f"temporary remap failed: {resp}")
        send_matrix_event(args.matrix, "P", args.row, args.col)
        time.sleep(max(0.0, args.hold))
        send_matrix_event(args.matrix, "R", args.row, args.col)
        print("ok: matrix tap injected")
    finally:
        if not args.no_restore:
            resp = set_action(args.ctrl, args.layer, args.row, args.col, original)
            if resp.get("result") != "ok":
                print(f"warning: restore failed: {resp}")
            else:
                print({"restored": original})


if __name__ == "__main__":
    main()
