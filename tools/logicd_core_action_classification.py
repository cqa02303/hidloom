#!/usr/bin/env python3
"""Classify default keymap actions for the native logicd-core owner boundary."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from logicd_core_parity_suite import flatten_keymap, is_supported_key, load_keycodes, parse_layer_action  # noqa: E402


DELEGATED_PREFIXES = (
    "MS_",
    "KC_MS_",
    "KC_BTN",
    "KC_WH_",
    "KC_SH",
    "MACRO:",
    "TEXT(",
    "SEND_STRING(",
)


def delegated_reason(action: str) -> str | None:
    if action in {"KC_NONE", "KC_TRNS", "KC_ZKHK"}:
        return None
    if action.startswith(("LT(", "MT(", "TT(", "TD(")):
        return "timed_or_composite"
    if action.startswith(("COMBO(", "KEY_OVERRIDE(", "LEADER(")):
        return "composite"
    if action.startswith(("MACRO:", "TEXT(", "SEND_STRING(")):
        return "macro_text"
    if action.startswith(("MS_", "KC_MS_", "KC_BTN", "KC_WH_")):
        return "mouse"
    if action.startswith("KC_SH"):
        return "system_or_session"
    if action in {"KC_USB", "KC_BT", "KC_CONNAUTO", "KC_CONSOLE"}:
        return "output_or_console"
    if "(" in action:
        return "wrapper_or_custom"
    return None


def classify_action(action: str, keycodes: dict[str, int]) -> tuple[str, str]:
    if action == "KC_TRNS":
        return "transparent", "transparent"
    if action == "KC_NONE":
        return "noop", "none"
    if action == "KC_ZKHK":
        return "native", "jis_internal"
    if parse_layer_action(action) is not None:
        return "native", "deterministic_layer"
    if is_supported_key(action, keycodes):
        return "native", "keyboard"
    reason = delegated_reason(action)
    if reason is not None:
        return "delegated", reason
    return "unsupported", "unknown"


def classify_keymap(keymap_path: Path, keycodes_path: Path) -> dict[str, Any]:
    layers = flatten_keymap(keymap_path)
    keycodes = load_keycodes(keycodes_path)
    entries: list[dict[str, Any]] = []
    by_owner: Counter[str] = Counter()
    by_reason: Counter[str] = Counter()
    by_action: dict[str, dict[str, Any]] = {}
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for layer_index, layer in enumerate(layers):
        for coord, action in sorted(layer.items()):
            owner, reason = classify_action(action, keycodes)
            entry = {"layer": layer_index, "coord": coord, "action": action, "owner": owner, "reason": reason}
            entries.append(entry)
            by_owner[owner] += 1
            by_reason[f"{owner}:{reason}"] += 1
            by_action.setdefault(action, {"action": action, "owner": owner, "reason": reason, "count": 0})["count"] += 1
            if len(examples[owner]) < 12:
                examples[owner].append(entry)

    delegated_reasons = Counter(entry["reason"] for entry in entries if entry["owner"] == "delegated")
    unsupported = [entry for entry in entries if entry["owner"] == "unsupported"]
    return {
        "schema": "logicd-core.action-classification.v1",
        "layers": len(layers),
        "entries": len(entries),
        "by_owner": dict(sorted(by_owner.items())),
        "by_reason": dict(sorted(by_reason.items())),
        "delegated_reasons": dict(sorted(delegated_reasons.items())),
        "unsupported_actions": len(unsupported),
        "unsupported_examples": unsupported[:24],
        "examples": {key: value for key, value in sorted(examples.items())},
        "actions": sorted(by_action.values(), key=lambda item: item["action"]),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keymap", type=Path, default=ROOT / "config/default/keymap.json")
    parser.add_argument("--keycodes", type=Path, default=ROOT / "config/default/keycodes.json")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = classify_keymap(args.keymap, args.keycodes)
    text = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    if summary["unsupported_actions"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
