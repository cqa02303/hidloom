#!/usr/bin/env python3
"""Summarize touch flick IME composition plan coverage without sending input."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "daemon" / "http"))

from touch_panel_flick_api import (  # noqa: E402
    REPO_TOUCH_PANEL_FLICK_CONFIG_FILE,
    TOUCH_FLICK_DIRECTIONS,
    build_touch_flick_composition_plan,
    resolve_flick_pad_action,
    touch_flick_layout_metadata,
)


def analyze_touch_flick_composition(config_path: str | Path = REPO_TOUCH_PANEL_FLICK_CONFIG_FILE) -> dict[str, Any]:
    layout = touch_flick_layout_metadata(config_path)
    rows: list[dict[str, Any]] = []
    blocked = Counter()
    blocking_reason_policy: dict[str, list[str]] = {}
    available_count = 0
    not_applicable_count = 0
    text_total = 0

    for layer in layout.get("layers", []):
        layer_index = int(layer.get("index", 0))
        for pad in layer.get("pads", []):
            key = str(pad.get("key") or "")
            index = int(pad.get("index", 0))
            for direction in TOUCH_FLICK_DIRECTIONS:
                if direction not in (pad.get("actions") or {}):
                    continue
                resolved = resolve_flick_pad_action(key, direction, layer=layer_index, index=index, config_path=config_path)
                plan = build_touch_flick_composition_plan(resolved)
                if not blocking_reason_policy:
                    blocking_reason_policy = {
                        str(reason): list(tags)
                        for reason, tags in (plan.get("blocking_reason_policy") or {}).items()
                        if isinstance(tags, list)
                    }
                reasons = list(plan.get("blocking_reasons") or [])
                action_output = (resolved.get("action") or {}).get("output")
                if action_output == "text":
                    text_total += 1
                if plan.get("not_applicable"):
                    not_applicable_count += 1
                elif plan.get("available"):
                    available_count += 1
                else:
                    blocked.update(reasons or ["unknown"])
                rows.append({
                    "layer": layer_index,
                    "pad": key,
                    "index": index,
                    "direction": direction,
                    "action": (resolved.get("action") or {}).get("action"),
                    "output": action_output,
                    "available": bool(plan.get("available")),
                    "not_applicable": bool(plan.get("not_applicable")),
                    "tap_sequence": [tap.get("key") for tap in plan.get("tap_sequence", [])],
                    "blocking_reasons": reasons,
                })

    known_reasons = set(blocking_reason_policy)
    unclassified = sorted(reason for reason in blocked if reason not in known_reasons)
    return {
        "schema": "touch_panel.flick.composition_smoke.v1",
        "read_only": True,
        "config_path": str(config_path),
        "total": len(rows),
        "text_total": text_total,
        "available": available_count,
        "not_applicable": not_applicable_count,
        "blocked": len(rows) - available_count - not_applicable_count,
        "blocked_reasons": dict(sorted(blocked.items())),
        "blocking_reason_policy": blocking_reason_policy,
        "blocked_policy_complete": not unclassified,
        "unclassified_blocked_reasons": unclassified,
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(REPO_TOUCH_PANEL_FLICK_CONFIG_FILE), help="flick.json path")
    parser.add_argument("--json", action="store_true", help="print full JSON")
    args = parser.parse_args(argv)

    report = analyze_touch_flick_composition(args.config)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    print(
        f"{report['schema']}: total={report['total']} "
        f"text={report['text_total']} available={report['available']} "
        f"not_applicable={report['not_applicable']} blocked={report['blocked']}"
    )
    for reason, count in report["blocked_reasons"].items():
        print(f"blocked {reason}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
