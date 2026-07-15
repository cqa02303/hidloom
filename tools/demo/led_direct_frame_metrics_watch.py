#!/usr/bin/env python3
"""Watch ledd direct-frame metrics without requiring HTTP UI.

This is a lightweight helper for long-run LED video / direct-frame observation.
It reads the same JSON status file that HTTP `/api/status` exposes through
`ledd_direct_frame_status()`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

DEFAULT_STATUS_PATH = Path(os.environ.get("LEDD_DIRECT_FRAME_STATUS", "/tmp/ledd_direct_frame_status.json"))


def _load_status(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"available": False, "metrics_source": "missing", "path": str(path)}
    except json.JSONDecodeError as exc:
        return {"available": False, "metrics_source": "invalid", "path": str(path), "error": str(exc)}
    except OSError as exc:
        return {"available": False, "metrics_source": "error", "path": str(path), "error": str(exc)}


def _num(data: dict[str, Any], key: str) -> int:
    try:
        return int(data.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _delta_rate(now_value: int, prev_value: int, elapsed: float) -> float:
    if elapsed <= 0:
        return 0.0
    return max(0.0, (now_value - prev_value) / elapsed)


def format_metrics(current: dict[str, Any], previous: dict[str, Any] | None, elapsed: float) -> str:
    accepted = _num(current, "accepted_frames")
    applied = _num(current, "applied_frames")
    ignored = _num(current, "ignored_frames")
    rejected = _num(current, "rejected_frames")
    bytes_received = _num(current, "bytes_received")
    last_frame = current.get("last_applied_frame_id", current.get("last_frame_id", "-"))
    active = bool(current.get("direct_frame_active"))
    source = current.get("metrics_source", "json_file")
    if previous is None:
        accepted_rate = applied_rate = byte_rate = 0.0
    else:
        accepted_rate = _delta_rate(accepted, _num(previous, "accepted_frames"), elapsed)
        applied_rate = _delta_rate(applied, _num(previous, "applied_frames"), elapsed)
        byte_rate = _delta_rate(bytes_received, _num(previous, "bytes_received"), elapsed)
    return (
        f"active={int(active)} source={source} "
        f"accepted={accepted}({accepted_rate:.1f}/s) "
        f"applied={applied}({applied_rate:.1f}/s) "
        f"ignored={ignored} rejected={rejected} "
        f"bytes={bytes_received}({byte_rate:.0f}/s) last={last_frame} "
        f"err={current.get('last_error') or current.get('error') or '-'}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS_PATH, help="direct-frame status JSON path")
    parser.add_argument("--interval", type=float, default=1.0, help="print interval seconds")
    parser.add_argument("--count", type=int, default=0, help="number of samples; 0 means forever")
    args = parser.parse_args()

    previous: dict[str, Any] | None = None
    previous_time = time.monotonic()
    sample = 0
    while True:
        now = time.monotonic()
        current = _load_status(args.status)
        print(format_metrics(current, previous, now - previous_time), flush=True)
        previous = current
        previous_time = now
        sample += 1
        if args.count and sample >= args.count:
            return 0
        time.sleep(max(0.1, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
