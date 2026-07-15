#!/usr/bin/env python3
"""Compare logicd-core shadow preview NDJSON with broker-frame NDJSON."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT / "daemon"))

from usbd.hid_report_broker import KIND_KEYBOARD, decode_hid_report_request  # noqa: E402


def read_ndjson(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def core_reports(path: Path) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for item in read_ndjson(path):
        if item.get("t") != "shadow_report":
            continue
        report = item.get("report")
        if isinstance(report, str):
            kind = item.get("kind", KIND_KEYBOARD)
            reports.append({"kind": kind, "payload": report.lower()})
    return reports


def broker_reports(path: Path) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for item in read_ndjson(path):
        if item.get("t") != "broker_frame":
            continue
        kind = item.get("kind")
        payload = item.get("payload")
        if isinstance(kind, int) and isinstance(payload, str):
            reports.append({"kind": kind, "payload": payload.lower()})
            continue
        frame = item.get("frame")
        if isinstance(frame, str):
            request = decode_hid_report_request(bytes.fromhex(frame))
            reports.append({"kind": request.kind, "payload": request.payload.hex()})
    return reports


def compare_reports(core: list[dict[str, Any]], broker: list[dict[str, Any]]) -> dict[str, Any]:
    limit = min(len(core), len(broker))
    mismatches = [
        {"index": index, "core": core[index], "broker": broker[index]}
        for index in range(limit)
        if core[index] != broker[index]
    ]
    return {
        "result": "ok" if not mismatches and len(core) == len(broker) else "mismatch",
        "core_reports": len(core),
        "broker_reports": len(broker),
        "compared": limit,
        "mismatches": mismatches,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-preview", type=Path, required=True)
    parser.add_argument("--broker-frames", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = compare_reports(
        core_reports(args.core_preview),
        broker_reports(args.broker_frames),
    )
    text = json.dumps(summary, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    if summary["result"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
