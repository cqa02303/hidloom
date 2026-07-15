#!/usr/bin/env python3
"""Inject repeatable matrix tap events for logicd performance measurements."""
from __future__ import annotations

import argparse
import json
import socket
import time
from pathlib import Path
from typing import Any


def _hex_digit(value: int) -> int:
    if not 0 <= value <= 15:
        raise ValueError(f"matrix row/col must be in 0..15, got {value}")
    return ord(f"{value:X}")


def matrix_packet(kind: str, row: int, col: int) -> bytes:
    if kind not in {"P", "R"}:
        raise ValueError(f"kind must be P or R, got {kind!r}")
    return bytes([ord(kind), _hex_digit(row), _hex_digit(col), 0x00])


def json_request(sock_path: str, msg: dict[str, Any], *, timeout: float = 3.0) -> dict[str, Any]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(sock_path)
        sock.sendall((json.dumps(msg, separators=(",", ":")) + "\n").encode())
        data = b""
        while not data.endswith(b"\n"):
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
    return json.loads(data.decode()) if data else {}


def get_action(ctrl_sock: str, layer: int, row: int, col: int) -> str:
    keymap = json_request(ctrl_sock, {"t": "G"})
    layers = keymap.get("layers", [])
    if not isinstance(layers, list) or layer >= len(layers):
        return "KC_NONE"
    layer_map = layers[layer]
    if not isinstance(layer_map, dict):
        return "KC_NONE"
    return str(layer_map.get(f"{row},{col}", "KC_NONE"))


def set_action(ctrl_sock: str, layer: int, row: int, col: int, action: str) -> dict[str, Any]:
    return json_request(ctrl_sock, {"t": "M", "l": layer, "r": row, "c": col, "a": action})


def inject_taps(matrix_sock: str, *, row: int, col: int, count: int, rate_hz: float, hold_sec: float) -> float:
    if count < 1:
        raise ValueError("count must be >= 1")
    if rate_hz <= 0:
        raise ValueError("rate-hz must be > 0")
    if hold_sec < 0:
        raise ValueError("hold-sec must be >= 0")
    interval = 1.0 / rate_hz
    press = matrix_packet("P", row, col)
    release = matrix_packet("R", row, col)
    started = time.monotonic()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(3.0)
        sock.connect(matrix_sock)
        for index in range(count):
            due = started + (index * interval)
            now = time.monotonic()
            if due > now:
                time.sleep(due - now)
            sock.sendall(press)
            if hold_sec:
                time.sleep(min(hold_sec, interval))
            sock.sendall(release)
    return time.monotonic() - started


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", help="temporary action, e.g. KC_A, KC_CONNAUTO, KC_SH3")
    parser.add_argument("--layer", type=int, default=0)
    parser.add_argument("--row", type=int, default=7)
    parser.add_argument("--col", type=int, default=0)
    parser.add_argument("--count", type=int, default=100, help="number of tap events")
    parser.add_argument("--rate-hz", type=float, default=20.0, help="tap start rate")
    parser.add_argument("--hold-sec", type=float, default=0.02, help="seconds between press and release")
    parser.add_argument("--ctrl", default="/tmp/ctrl_events.sock")
    parser.add_argument("--matrix", default="/tmp/matrix_events.sock")
    parser.add_argument("--no-restore", action="store_true", help="leave the temporary action assigned")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for path in (args.ctrl, args.matrix):
        if not Path(path).exists():
            raise SystemExit(f"socket not found: {path}")

    original = get_action(args.ctrl, args.layer, args.row, args.col)
    summary: dict[str, Any] = {
        "layer": args.layer,
        "row": args.row,
        "col": args.col,
        "original": original,
        "temporary": args.action,
        "count": args.count,
        "rate_hz": args.rate_hz,
        "hold_sec": args.hold_sec,
    }
    try:
        resp = set_action(args.ctrl, args.layer, args.row, args.col, args.action)
        if resp.get("result") != "ok":
            raise SystemExit(f"temporary remap failed: {resp}")
        elapsed = inject_taps(
            args.matrix,
            row=args.row,
            col=args.col,
            count=args.count,
            rate_hz=args.rate_hz,
            hold_sec=args.hold_sec,
        )
        summary["elapsed_sec"] = round(elapsed, 3)
        summary["events_per_sec"] = round(args.count / elapsed, 3) if elapsed > 0 else 0.0
        summary["result"] = "ok"
    finally:
        if not args.no_restore:
            resp = set_action(args.ctrl, args.layer, args.row, args.col, original)
            summary["restore_result"] = resp.get("result", "unknown")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
