#!/usr/bin/env python3
"""Run a keymap-derived logicd-core parity suite against Python logicd."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CORE_BIN = ROOT / "bin" / "hidloom-logicd-core"
if not CORE_BIN.exists():
    CORE_BIN = ROOT / "tools" / "hidloom_logicd_core" / "target" / "release" / "hidloom-logicd-core"
PYTHON_REPLAY = ROOT / "tools" / "logicd_python_matrix_replay.py"


def flatten_keymap(path: Path) -> list[dict[str, str]]:
    keymap = json.loads(path.read_text(encoding="utf-8"))
    layers = keymap.get("layers", [])
    layout_def = keymap.get("_layout_def")
    if not isinstance(layers, list):
        return [{}]
    if not isinstance(layout_def, dict):
        return [dict(layer) for layer in layers if isinstance(layer, dict)] or [{}]
    result: list[dict[str, str]] = []
    for layer in layers:
        flat: dict[str, str] = {}
        if not isinstance(layer, dict):
            result.append(flat)
            continue
        for group, coords in layout_def.items():
            actions = layer.get(group, [])
            if not isinstance(coords, list) or not isinstance(actions, list):
                continue
            for coord, action in zip(coords, actions):
                if (
                    isinstance(coord, list)
                    and len(coord) >= 2
                    and isinstance(coord[0], int)
                    and isinstance(coord[1], int)
                    and isinstance(action, str)
                    and action
                ):
                    flat[f"{coord[0]},{coord[1]}"] = action
        result.append(flat)
    return result or [{}]


def load_keycodes(path: Path) -> dict[str, int]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, int] = {}
    for name, value in raw.items():
        if name.startswith("_"):
            continue
        if isinstance(value, int):
            result[name] = value
        elif isinstance(value, dict):
            if value.get("page") == "consumer":
                continue
            hid = value.get("hid")
            if isinstance(hid, int):
                result[name] = hid
    return result


def matrix_packet(kind: str, coord: str) -> bytes:
    row_raw, col_raw = coord.split(",", 1)
    row = int(row_raw)
    col = int(col_raw)
    if not 0 <= row <= 15 or not 0 <= col <= 15:
        raise ValueError(f"matrix coordinate out of M0 range: {coord}")
    return bytes([ord(kind), ord(f"{row:X}"), ord(f"{col:X}"), ord("\n")])


def is_supported_key(action: str, keycodes: dict[str, int]) -> bool:
    code = keycodes.get(action)
    if code is None:
        return False
    return code == 0 or 0 < code < 0xE0 or 0xE0 <= code <= 0xE7


def is_modifier(action: str, keycodes: dict[str, int]) -> bool:
    code = keycodes.get(action)
    return code is not None and 0xE0 <= code <= 0xE7


def is_normal_key(action: str, keycodes: dict[str, int]) -> bool:
    code = keycodes.get(action)
    return code is not None and 0 < code < 0xE0


def parse_layer_action(action: str) -> tuple[str, int] | None:
    if not action.endswith(")"):
        return None
    op = None
    for candidate in ("MO", "TG", "TO", "DF", "OSL"):
        if action.startswith(f"{candidate}("):
            op = candidate
            break
    if op is None:
        return None
    try:
        return op, int(action[len(op) + 1 : -1])
    except ValueError:
        return None


def classify_unsupported(layers: list[dict[str, str]], keycodes: dict[str, int]) -> list[dict[str, Any]]:
    unsupported: list[dict[str, Any]] = []
    for layer_index, layer in enumerate(layers):
        for coord, action in sorted(layer.items()):
            if action in {"KC_TRNS", "KC_NONE"}:
                continue
            if parse_layer_action(action) is not None:
                continue
            if is_supported_key(action, keycodes):
                continue
            unsupported.append({"layer": layer_index, "coord": coord, "action": action})
    return unsupported


def build_sequences(
    layers: list[dict[str, str]],
    keycodes: dict[str, int],
    *,
    max_basic: int,
) -> list[dict[str, Any]]:
    base = layers[0] if layers else {}
    supported = [
        (coord, action)
        for coord, action in sorted(base.items())
        if is_supported_key(action, keycodes) and keycodes.get(action, 0) != 0
    ]
    normal = [(coord, action) for coord, action in supported if is_normal_key(action, keycodes)]
    modifiers = [(coord, action) for coord, action in supported if is_modifier(action, keycodes)]

    sequences: list[dict[str, Any]] = []
    for coord, action in supported[:max_basic]:
        sequences.append(
            {
                "name": f"tap:{action}@{coord}",
                "events": matrix_packet("P", coord) + matrix_packet("R", coord),
                "actions": [action],
            }
        )

    if modifiers and normal:
        mod_coord, mod_action = modifiers[0]
        key_coord, key_action = normal[0]
        sequences.append(
            {
                "name": f"chord:{mod_action}+{key_action}",
                "events": (
                    matrix_packet("P", mod_coord)
                    + matrix_packet("P", key_coord)
                    + matrix_packet("R", key_coord)
                    + matrix_packet("R", mod_coord)
                ),
                "actions": [mod_action, key_action],
            }
        )

    def first_layer_target(layer_index: int, source_coord: str) -> tuple[str, str] | None:
        if layer_index >= len(layers):
            return None
        return next(
            (
                (coord, action)
                for coord, action in sorted(layers[layer_index].items())
                if coord != source_coord and is_normal_key(action, keycodes)
            ),
            None,
        )

    for layer_coord, layer_action in sorted(base.items()):
        parsed = parse_layer_action(layer_action)
        if parsed is None:
            continue
        op, layer_index = parsed
        target = first_layer_target(layer_index, layer_coord)
        if target is None:
            continue
        key_coord, key_action = target
        if op == "MO":
            events = (
                matrix_packet("P", layer_coord)
                + matrix_packet("P", key_coord)
                + matrix_packet("R", key_coord)
                + matrix_packet("R", layer_coord)
            )
        elif op == "TG":
            events = (
                matrix_packet("P", layer_coord)
                + matrix_packet("R", layer_coord)
                + matrix_packet("P", key_coord)
                + matrix_packet("R", key_coord)
                + matrix_packet("P", layer_coord)
                + matrix_packet("R", layer_coord)
            )
        else:
            events = (
                matrix_packet("P", layer_coord)
                + matrix_packet("R", layer_coord)
                + matrix_packet("P", key_coord)
                + matrix_packet("R", key_coord)
            )
        sequences.append(
            {
                "name": f"layer:{layer_action}:{key_action}@{key_coord}",
                "events": events,
                "actions": [layer_action, key_action],
            }
        )
    return sequences


def run_core(replay_path: Path, keymap: Path, keycodes: Path) -> list[str]:
    env = os.environ.copy()
    env.update(
        {
            "HIDLOOM_REPO_ROOT": str(ROOT),
            "LOGICD_CORE_KEYMAP_PATH": str(keymap),
            "LOGICD_CORE_DEFAULT_KEYMAP_PATH": str(keymap),
            "LOGICD_CORE_KEYCODES_PATH": str(keycodes),
            "LOGICD_CORE_DEFAULT_KEYCODES_PATH": str(keycodes),
            "LOGICD_USB_SPLIT_KEYBOARD": "0",
        }
    )
    result = subprocess.run(
        [str(CORE_BIN), "--replay", str(replay_path)],
        check=True,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    reports: list[str] = []
    for line in result.stdout.splitlines():
        if line.strip():
            payload = json.loads(line)
            if payload.get("t") == "keyboard_report":
                reports.append(str(payload["report"]).lower())
    return reports


def run_python(replay_path: Path, output_path: Path, keymap: Path) -> list[str]:
    subprocess.run(
        [
            sys.executable,
            str(PYTHON_REPLAY),
            str(replay_path),
            "--keymap",
            str(keymap),
            "--output",
            str(output_path),
        ],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    reports: list[str] = []
    for line in output_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if payload.get("t") == "broker_frame" and payload.get("kind_name") == "keyboard":
            reports.append(str(payload["payload"]).lower())
    return reports


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keymap", type=Path, default=ROOT / "config/default/keymap.json")
    parser.add_argument("--keycodes", type=Path, default=ROOT / "config/default/keycodes.json")
    parser.add_argument("--max-basic", type=int, default=64)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    layers = flatten_keymap(args.keymap)
    keycodes = load_keycodes(args.keycodes)
    sequences = build_sequences(layers, keycodes, max_basic=args.max_basic)
    unsupported = classify_unsupported(layers, keycodes)
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for index, sequence in enumerate(sequences):
            replay_path = tmp / f"sequence-{index}.bin"
            python_path = tmp / f"python-{index}.ndjson"
            replay_path.write_bytes(sequence["events"])
            core_reports = run_core(replay_path, args.keymap, args.keycodes)
            python_reports = run_python(replay_path, python_path, args.keymap)
            results.append(
                {
                    "name": sequence["name"],
                    "actions": sequence["actions"],
                    "core_reports": len(core_reports),
                    "python_reports": len(python_reports),
                    "match": core_reports == python_reports,
                    "mismatches": [
                        {"index": idx, "core": core, "python": py}
                        for idx, (core, py) in enumerate(zip(core_reports, python_reports))
                        if core != py
                    ],
                }
            )
    summary = {
        "schema": "logicd-core.parity-suite.v1",
        "result": "ok" if all(item["match"] for item in results) else "mismatch",
        "sequences": len(results),
        "matched": sum(1 for item in results if item["match"]),
        "unsupported_actions": len(unsupported),
        "unsupported_examples": unsupported[:24],
        "results": results,
    }
    text = json.dumps(summary, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    if summary["result"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
