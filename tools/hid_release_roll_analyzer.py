#!/usr/bin/env python3
"""Analyze hidloom-hidd NDJSON logs for release/next-press roll hazards."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ZERO_REPORTS = {"0000000000000000", "010000000000000000"}
DEFAULT_THRESHOLDS_MS = (5.0, 10.0, 16.0, 25.0)


def load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            events.append({"t": "parse_error", "line": line_number, "error": str(exc)})
            continue
        events.append(event)
    return events


def keyboard_writes(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events if event.get("t") == "hidd_keyboard_write"]


def release_summary(events: list[dict[str, Any]]) -> dict[str, int]:
    keys = (
        "hidd_keyboard_release_pending",
        "hidd_keyboard_release_merged",
        "hidd_keyboard_release_preserved",
        "hidd_keyboard_release_flush",
        "hidd_keyboard_dedup_drop",
        "parse_error",
    )
    return {key: sum(event.get("t") == key for event in events) for key in keys}


def zero_to_next_press(
    writes: list[dict[str, Any]],
    threshold_ms: float,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for index, event in enumerate(writes):
        report = event.get("report")
        endpoint = event.get("endpoint")
        if report not in ZERO_REPORTS:
            continue
        next_item = next(
            (
                (next_index, candidate)
                for next_index, candidate in enumerate(writes[index + 1 :], start=index + 1)
                if candidate.get("endpoint") == endpoint
            ),
            None,
        )
        if next_item is None:
            continue
        next_index, next_event = next_item
        next_report = next_event.get("report")
        if next_report in ZERO_REPORTS:
            continue
        dt_ms = (int(next_event.get("unix_us", 0)) - int(event.get("unix_us", 0))) / 1000.0
        if 0 <= dt_ms < threshold_ms:
            matches.append(
                {
                    "dt_ms": round(dt_ms, 3),
                    "index": index,
                    "next_index": next_index,
                    "endpoint": endpoint,
                    "zero_report": report,
                    "next_report": next_report,
                }
            )
    return matches


def analyze(path: Path, thresholds_ms: list[float]) -> dict[str, Any]:
    events = load_events(path)
    writes = keyboard_writes(events)
    close = {str(threshold): zero_to_next_press(writes, threshold) for threshold in thresholds_ms}
    return {
        "schema": "hid-release-roll-analysis.v1",
        "path": str(path),
        "events": len(events),
        "keyboard_writes": len(writes),
        "release_summary": release_summary(events),
        "zero_to_next_press": close,
    }


def format_text(payload: dict[str, Any]) -> str:
    lines = [
        f"path: {payload['path']}",
        f"events: {payload['events']}",
        f"keyboard_writes: {payload['keyboard_writes']}",
        "release_summary:",
    ]
    for key, value in payload["release_summary"].items():
        lines.append(f"  {key}: {value}")
    lines.append("zero_to_next_press:")
    for threshold, matches in payload["zero_to_next_press"].items():
        lines.append(f"  under {threshold}ms: {len(matches)}")
        for match in matches[:10]:
            lines.append(
                "    "
                f"dt={match['dt_ms']}ms endpoint={match['endpoint']} "
                f"zero={match['zero_report']} next={match['next_report']} "
                f"index={match['index']}->{match['next_index']}"
            )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        nargs="?",
        default="/run/hidloom/input-capture/hidd.ndjson",
        help="hidloom-hidd frame log NDJSON path",
    )
    parser.add_argument(
        "--threshold-ms",
        type=float,
        action="append",
        dest="thresholds",
        help="close zero-to-next threshold in ms; can be passed more than once",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    thresholds = args.thresholds if args.thresholds else list(DEFAULT_THRESHOLDS_MS)
    payload = analyze(Path(args.path), thresholds)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_text(payload))


if __name__ == "__main__":
    main()
