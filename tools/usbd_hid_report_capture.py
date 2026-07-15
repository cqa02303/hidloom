#!/usr/bin/env python3
"""Capture usbd HID report broker datagrams as NDJSON."""
from __future__ import annotations

import argparse
import json
import socket
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT / "daemon"))

from usbd.hid_report_broker import decode_hid_report_request  # noqa: E402


def capture_frames(socket_path: Path, *, count: int, timeout: float) -> list[dict[str, Any]]:
    if socket_path.exists():
        socket_path.unlink()
    frames: list[dict[str, Any]] = []
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.bind(str(socket_path))
        for seq in range(1, count + 1):
            raw = sock.recv(64)
            request = decode_hid_report_request(raw)
            frames.append(
                {
                    "t": "broker_frame",
                    "seq": seq,
                    "kind": request.kind,
                    "kind_name": request.kind_name,
                    "payload": request.payload.hex(),
                    "frame": raw.hex(),
                }
            )
    return frames


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    frames = capture_frames(args.socket, count=args.count, timeout=args.timeout)
    if args.output.parent:
        args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(frame, sort_keys=True) + "\n" for frame in frames),
        encoding="utf-8",
    )
    print(json.dumps({"result": "ok", "frames": len(frames), "output": str(args.output)}, sort_keys=True))


if __name__ == "__main__":
    main()
