#!/usr/bin/env python3
"""Live smoke for the default native logicd-core owner path.

This injects short matrix-event sequences into the active
``/tmp/matrix_events.sock`` listener and verifies that logicd-core and hidloom-hidd
both observe the resulting HID report path. It does not change systemd owner
state.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from logicd_core_active_owner_smoke import flatten_keymap, load_json_with_fallback, load_keycodes  # noqa: E402

MATRIX_SOCKET = Path("/tmp/matrix_events.sock")
CORE_CTRL_SOCKET = Path("/tmp/logicd_core_ctrl.sock")
CORE_STATUS = Path("/run/hidloom/logicd-core-status.json")
HIDD_STATUS = Path("/run/hidloom/hidd-status.json")

DEFAULT_SEQUENCES = (
    ("modifier-only", ("KC_LSFT",)),
    ("overlap-basic", ("KC_A", "KC_B")),
    ("us-sub-lang", ("KC_LANG1",)),
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def counters(payload: dict[str, Any]) -> dict[str, int]:
    raw = payload.get("counters", {})
    return {str(key): int(value) for key, value in raw.items()} if isinstance(raw, dict) else {}


def packet(kind: str, row: int, col: int) -> bytes:
    if not (0 <= row <= 15 and 0 <= col <= 15):
        raise ValueError(f"matrix coordinate out of hex packet range: row={row} col={col}")
    return bytes([ord(kind), ord(f"{row:X}"), ord(f"{col:X}"), 0])


def action_coords(repo_root: Path) -> dict[str, tuple[int, int]]:
    if repo_root == ROOT:
        keymap = load_json_with_fallback(Path("/mnt/p3/keymap.json"), repo_root / "config/default/keymap.json")
        keycodes = load_keycodes(repo_root)
    else:
        keymap = load_json(repo_root / "config/default/keymap.json")
        keycodes = {
            str(name): int(value["hid"] if isinstance(value, dict) else value)
            for name, value in load_json(repo_root / "config/default/keycodes.json").items()
            if not str(name).startswith("_")
        }
    base = flatten_keymap(keymap)[0]
    coords: dict[str, tuple[int, int]] = {}
    for coord, action in base.items():
        if action not in keycodes:
            continue
        try:
            row_s, col_s = coord.split(",", 1)
            coords.setdefault(action, (int(row_s), int(col_s)))
        except ValueError:
            continue
    return coords


def choose_sequences(repo_root: Path) -> list[tuple[str, list[tuple[str, int, int]]]]:
    coords = action_coords(repo_root)
    sequences: list[tuple[str, list[tuple[str, int, int]]]] = []
    missing: list[str] = []
    for label, actions in DEFAULT_SEQUENCES:
        entries: list[tuple[str, int, int]] = []
        for action in actions:
            coord = coords.get(action)
            if coord is None:
                missing.append(action)
                entries = []
                break
            entries.append((action, coord[0], coord[1]))
        if entries:
            sequences.append((label, entries))
    if missing:
        # Missing optional LANG1 is acceptable on variants, but a modifier/basic
        # smoke without layer-0 keys would not prove the default path.
        required = {"KC_LSFT", "KC_A", "KC_B"}
        required_missing = required.intersection(missing)
        if required_missing:
            raise RuntimeError(f"missing required smoke action(s): {sorted(required_missing)}")
    return sequences


def send_sequence(entries: list[tuple[str, int, int]], *, hold_sec: float, gap_sec: float) -> None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(3.0)
        sock.connect(str(MATRIX_SOCKET))
        for _action, row, col in entries:
            sock.sendall(packet("P", row, col))
            time.sleep(gap_sec)
        time.sleep(hold_sec)
        for _action, row, col in reversed(entries):
            sock.sendall(packet("R", row, col))
            time.sleep(gap_sec)


def wait_for_counter(path: Path, key: str, minimum: int, *, timeout_sec: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_sec
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            last = load_json(path)
            if counters(last).get(key, 0) >= minimum:
                return last
        except Exception:
            pass
        time.sleep(0.05)
    raise RuntimeError(f"{path} counter {key} did not reach {minimum}; last={last}")


def ctrl_request(path: Path, payload: dict[str, Any], *, timeout_sec: float) -> dict[str, Any]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout_sec)
        sock.connect(str(path))
        sock.sendall((json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8"))
        data = b""
        while not data.endswith(b"\n"):
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
    if not data:
        raise RuntimeError(f"ctrl request returned empty response: {path}")
    return json.loads(data.decode("utf-8"))


def cleanup_pressed_state(*, timeout_sec: float) -> dict[str, Any]:
    result: dict[str, Any] = {"attempted": False}
    try:
        before = load_json(CORE_STATUS)
        state = before.get("state", {}) if isinstance(before.get("state"), dict) else {}
        if state.get("pressed_matrix") == 0 and state.get("pressed_keys") == 0:
            result["needed"] = False
            return result
        result.update({"attempted": True, "needed": True, "before": state})
        result["response"] = ctrl_request(CORE_CTRL_SOCKET, {"t": "release_all"}, timeout_sec=timeout_sec)
        time.sleep(0.1)
        after = load_json(CORE_STATUS)
        result["after"] = after.get("state", {}) if isinstance(after.get("state"), dict) else {}
        return result
    except Exception as exc:
        result["error"] = str(exc)
        return result


def run_smoke(*, repo_root: Path, hold_sec: float, gap_sec: float, timeout_sec: float) -> dict[str, Any]:
    sequences = choose_sequences(repo_root)
    if not MATRIX_SOCKET.exists():
        raise RuntimeError(f"matrix socket does not exist: {MATRIX_SOCKET}")
    core_before = load_json(CORE_STATUS)
    hidd_before = load_json(HIDD_STATUS)
    core_count = counters(core_before).get("matrix_events", 0)
    hidd_count = counters(hidd_before).get("frames_received", 0)
    sequence_results: list[dict[str, Any]] = []

    for label, entries in sequences:
        expected_events = len(entries) * 2
        send_sequence(entries, hold_sec=hold_sec, gap_sec=gap_sec)
        core_count += expected_events
        hidd_count += expected_events
        core_after = wait_for_counter(CORE_STATUS, "matrix_events", core_count, timeout_sec=timeout_sec)
        hidd_after = wait_for_counter(HIDD_STATUS, "frames_received", hidd_count, timeout_sec=timeout_sec)
        sequence_results.append(
            {
                "label": label,
                "actions": [{"action": action, "row": row, "col": col} for action, row, col in entries],
                "core_counters": counters(core_after),
                "hidd_counters": counters(hidd_after),
            }
        )

    final_core = load_json(CORE_STATUS)
    final_hidd = load_json(HIDD_STATUS)
    state = final_core.get("state", {}) if isinstance(final_core.get("state"), dict) else {}
    hidd_counters = counters(final_hidd)
    issues: list[str] = []
    if state.get("pressed_matrix") != 0 or state.get("pressed_keys") != 0:
        issues.append(f"core pressed state is not clear: {state}")
    if hidd_counters.get("write_errors", 0) != counters(hidd_before).get("write_errors", 0):
        issues.append("hidd write_errors changed")
    if hidd_counters.get("dropped_reports", 0) != counters(hidd_before).get("dropped_reports", 0):
        issues.append("hidd dropped_reports changed")
    if counters(final_core).get("matrix_tap_errors", 0) != counters(core_before).get("matrix_tap_errors", 0):
        issues.append("core matrix_tap_errors changed")
    cleanup = cleanup_pressed_state(timeout_sec=timeout_sec) if issues else {"attempted": False, "needed": False}
    return {
        "schema": "logicd-core.native-owner-live-smoke.v1",
        "ok": not issues,
        "issues": issues,
        "cleanup": cleanup,
        "sequences": sequence_results,
        "core_before": counters(core_before),
        "core_after": counters(final_core),
        "hidd_before": counters(hidd_before),
        "hidd_after": hidd_counters,
        "final_state": state,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="send live matrix events")
    parser.add_argument("--json", action="store_true", help="print compact JSON")
    parser.add_argument("--hold-sec", type=float, default=0.04)
    parser.add_argument("--gap-sec", type=float, default=0.015)
    parser.add_argument("--timeout-sec", type=float, default=3.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.hold_sec < 0 or args.gap_sec < 0 or args.timeout_sec <= 0:
        raise SystemExit("timing arguments must be non-negative, and timeout must be > 0")
    if not args.apply:
        payload = {
            "schema": "logicd-core.native-owner-live-smoke.v1",
            "mode": "dry-run",
            "sequences": [
                {"label": label, "actions": list(actions)}
                for label, actions in DEFAULT_SEQUENCES
            ],
        }
    else:
        payload = run_smoke(repo_root=ROOT, hold_sec=args.hold_sec, gap_sec=args.gap_sec, timeout_sec=args.timeout_sec)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    if args.apply and not payload.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
