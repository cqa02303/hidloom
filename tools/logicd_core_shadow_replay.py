#!/usr/bin/env python3
"""Replay recorded matrix packets into a logicd-core shadow socket."""
from __future__ import annotations

import argparse
import json
import socket
import time
from pathlib import Path
from typing import Any


def validate_matrix_stream(data: bytes) -> int:
    if len(data) % 4 != 0:
        raise ValueError(f"matrix stream length must be a multiple of 4: {len(data)}")
    for index in range(0, len(data), 4):
        packet = data[index : index + 4]
        if packet[0] not in (ord("P"), ord("R")):
            raise ValueError(f"invalid event type at packet {index // 4}: 0x{packet[0]:02x}")
        for label, value in (("row", packet[1]), ("col", packet[2])):
            try:
                int(chr(value), 16)
            except ValueError as exc:
                raise ValueError(
                    f"invalid {label} at packet {index // 4}: 0x{value:02x}"
                ) from exc
        if packet[3] not in (0, ord("\n")):
            raise ValueError(f"invalid terminator at packet {index // 4}: 0x{packet[3]:02x}")
    return len(data) // 4


def read_status(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def wait_for_counter(path: Path, counter: str, target: int, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        if path.exists():
            last = read_status(path)
            value = last.get("counters", {}).get(counter, 0)
            if isinstance(value, int) and value >= target:
                return last
        time.sleep(0.05)
    raise TimeoutError(f"{path} did not reach counters.{counter}>={target}; last={last}")


def replay_packets(socket_path: Path, data: bytes, chunk_packets: int) -> None:
    chunk_size = max(1, chunk_packets) * 4
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(3.0)
        sock.connect(str(socket_path))
        for offset in range(0, len(data), chunk_size):
            sock.sendall(data[offset : offset + chunk_size])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replay_file", type=Path, help="binary stream of 4-byte matrix packets")
    parser.add_argument(
        "--socket",
        type=Path,
        default=Path("/tmp/matrix_events_shadow.sock"),
        help="logicd-core shadow matrix socket",
    )
    parser.add_argument("--chunk-packets", type=int, default=64)
    parser.add_argument("--status", type=Path, help="optional logicd-core status JSON to wait on")
    parser.add_argument("--timeout", type=float, default=3.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data = args.replay_file.read_bytes()
    packet_count = validate_matrix_stream(data)
    replay_packets(args.socket, data, args.chunk_packets)
    summary: dict[str, Any] = {
        "result": "ok",
        "socket": str(args.socket),
        "replay_file": str(args.replay_file),
        "packets": packet_count,
    }
    if args.status:
        summary["status"] = wait_for_counter(
            args.status,
            "matrix_events",
            packet_count,
            args.timeout,
        )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
