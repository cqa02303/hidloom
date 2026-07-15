#!/usr/bin/env python3
"""Dry-run or explicitly send a bounded Unicode / Send String smoke sequence.

The default mode is dry-run.  Real HID output requires both --send and the
confirmation phrase, because the focused host application receives the keys.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.text_send_safety import (  # noqa: E402
    TEXT_SEND_RUNNER_CANCEL_PATH,
    TEXT_SEND_RUNNER_METHOD,
    TEXT_SEND_RUNNER_TARGET,
    build_text_send_real_send_plan,
)
from script.send_standard_keyboard_report import (  # noqa: E402
    DEFAULT_SOCKET,
    _reports_for_action,
    _send_reports_to_socket,
)
from usbd.hid_report_broker import KIND_KEYBOARD, KIND_US_SUB_KEYBOARD  # noqa: E402

CONFIRM_PHRASE = "SEND_TEXT_SMOKE_TO_FOCUSED_HOST"


def _ready_smoke_settings() -> dict[str, Any]:
    return {
        "unicode": {"mode": "windows_ime_hex_f5", "host_profile": "win11-ime"},
        "text_send_runner": {
            "connected": True,
            "method": TEXT_SEND_RUNNER_METHOD,
            "target": TEXT_SEND_RUNNER_TARGET,
            "cancel_path": TEXT_SEND_RUNNER_CANCEL_PATH,
            "zero_report_on_cancel": True,
            "timeout_sec": 2.0,
        },
        "send_strings": {"kana_a": {"text": "\u3042", "enabled": True}},
    }


def _settings_from_file(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"settings file must contain a JSON object: {path}")
    settings = data.get("settings")
    if isinstance(settings, dict):
        return settings
    return data


def _tap_summary(plan: dict[str, Any]) -> list[dict[str, Any]]:
    dry_run = plan.get("tap_dry_run") if isinstance(plan.get("tap_dry_run"), dict) else {}
    sequences = dry_run.get("sequences") if isinstance(dry_run.get("sequences"), list) else []
    taps: list[dict[str, Any]] = []
    for sequence in sequences:
        if not isinstance(sequence, dict):
            continue
        for tap in sequence.get("taps", []):
            if isinstance(tap, dict):
                taps.append({"action": tap.get("action") or tap.get("key"), "modifiers": tap.get("modifiers", [])})
    return taps


def _send_taps(
    taps: list[dict[str, Any]],
    *,
    socket_path: Path,
    broker_kind_name: str,
    hold_sec: float,
    gap_sec: float,
) -> None:
    kind = KIND_US_SUB_KEYBOARD if broker_kind_name == "us_sub_keyboard" else KIND_KEYBOARD
    for index, tap in enumerate(taps):
        action = tap.get("action")
        modifiers = tap.get("modifiers", [])
        if not isinstance(action, str):
            raise SystemExit(f"tap {index} is missing action: {tap!r}")
        if not isinstance(modifiers, list) or not all(isinstance(item, str) for item in modifiers):
            raise SystemExit(f"tap {index} has invalid modifiers: {tap!r}")
        press, release = _reports_for_action(action, modifiers, report_id=None)
        _send_reports_to_socket(socket_path, [press, release], hold_sec, kind=kind)
        if index + 1 < len(taps):
            time.sleep(gap_sec)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", default="U+3042", help="text action such as U+3042 or TEXT(kana_a)")
    parser.add_argument(
        "--settings",
        type=Path,
        help="JSON settings file. If omitted, a bounded ready smoke fixture is used.",
    )
    parser.add_argument("--socket", type=Path, default=DEFAULT_SOCKET, help="usbd HID report broker socket")
    parser.add_argument(
        "--broker-kind",
        choices=("keyboard", "us_sub_keyboard"),
        default="us_sub_keyboard",
        help="broker kind used for real send; us_sub_keyboard mirrors the normal Windows IME text route",
    )
    parser.add_argument("--hold-sec", type=float, default=0.030, help="press/release hold time")
    parser.add_argument("--gap-sec", type=float, default=0.180, help="gap between taps")
    parser.add_argument("--send", action="store_true", help="send the sequence to the focused host")
    parser.add_argument("--confirm", default="", help=f"required phrase for --send: {CONFIRM_PHRASE}")
    args = parser.parse_args()

    if args.hold_sec < 0 or args.gap_sec < 0:
        raise SystemExit("--hold-sec and --gap-sec must be non-negative")

    settings = _settings_from_file(args.settings) if args.settings else _ready_smoke_settings()
    plan = build_text_send_real_send_plan(args.action, settings)
    taps = _tap_summary(plan)
    output = {
        "schema": "text_send.smoke_sequence.v1",
        "action": args.action,
        "source": str(args.settings) if args.settings else "bounded_ready_smoke_fixture",
        "dry_run": not args.send,
        "real_send_allowed": plan.get("real_send_allowed"),
        "blocking_reasons": plan.get("blocking_reasons", []),
        "broker_kind": args.broker_kind,
        "socket": str(args.socket),
        "hold_sec": args.hold_sec,
        "gap_sec": args.gap_sec,
        "tap_count": len(taps),
        "taps": taps,
    }

    if not args.send:
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    if args.confirm != CONFIRM_PHRASE:
        raise SystemExit(f"--send requires --confirm {CONFIRM_PHRASE!r}")
    if plan.get("real_send_allowed") is not True:
        print(json.dumps(output, ensure_ascii=False, indent=2))
        raise SystemExit("text send smoke plan is not allowed")
    if not args.socket.exists():
        raise SystemExit(f"usbd HID report broker socket is not available: {args.socket}")

    _send_taps(taps, socket_path=args.socket, broker_kind_name=args.broker_kind, hold_sec=args.hold_sec, gap_sec=args.gap_sec)
    output["sent"] = True
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
