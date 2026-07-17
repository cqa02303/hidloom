#!/usr/bin/env python3
"""Regression tests for the native hidloom-uidd uinput report sink."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from usbd.hid_report_broker import (  # noqa: E402
    KIND_KEYBOARD,
    KIND_MOUSE,
    KIND_US_SUB_KEYBOARD,
    encode_hid_report_request,
)

TOOL_DIR = ROOT / "tools" / "hidloom_uidd"
BIN = TOOL_DIR / "target" / "release" / "hidloom-uidd"


def build_tool() -> None:
    subprocess.run(["make", "-C", str(TOOL_DIR)], check=True)


def wait_for_socket(path: Path) -> None:
    deadline = time.time() + 2.0
    while time.time() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    raise AssertionError(f"socket did not appear: {path}")


def run_uidd(tmp: Path, frames: list[bytes]) -> tuple[list[dict], dict]:
    sock_path = tmp / "uidd_reports.sock"
    status_path = tmp / "uidd-status.json"
    event_log = tmp / "uidd-events.ndjson"
    env = os.environ.copy()
    env.update(
        {
            "UIDD_REPORT_SOCKET": str(sock_path),
            "UIDD_STATUS_PATH": str(status_path),
            "UIDD_EVENT_LOG_PATH": str(event_log),
            "UIDD_DRY_RUN": "1",
        }
    )
    proc = subprocess.Popen([str(BIN), "--frames", str(len(frames))], env=env)
    wait_for_socket(sock_path)
    sender = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        for frame in frames:
            sender.sendto(frame, str(sock_path))
            time.sleep(0.005)
    finally:
        sender.close()
    try:
        proc.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise
    assert proc.returncode == 0
    if event_log.exists():
        events = [json.loads(line) for line in event_log.read_text(encoding="utf-8").splitlines()]
    else:
        events = []
    status = json.loads(status_path.read_text(encoding="utf-8"))
    return events, status


def compact_events(events: list[dict]) -> list[tuple[int, int, int]]:
    return [(event["type"], event["code"], event["value"]) for event in events]


def test_keyboard_report_diff_to_linux_events() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        events, status = run_uidd(
            Path(tmpdir),
            [
                encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000040000000000")),
                encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000040000000000")),
                encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000050000000000")),
                encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000000000000000")),
            ],
        )
    assert compact_events(events) == [
        (1, 30, 1),
        (0, 0, 0),
        (1, 30, 0),
        (1, 48, 1),
        (0, 0, 0),
        (1, 48, 0),
        (0, 0, 0),
    ]
    assert status["dry_run"] is True
    assert status["counters"]["frames_received"] == 4
    assert status["counters"]["keyboard_reports"] == 4
    assert status["counters"]["key_events"] == 4
    assert status["counters"]["sync_events"] == 3


def test_modifier_and_us_sub_keyboard_reports_share_diff_state() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        events, status = run_uidd(
            Path(tmpdir),
            [
                encode_hid_report_request(KIND_US_SUB_KEYBOARD, bytes.fromhex("0200040000000000")),
                encode_hid_report_request(KIND_US_SUB_KEYBOARD, bytes.fromhex("0000040000000000")),
                encode_hid_report_request(KIND_US_SUB_KEYBOARD, bytes.fromhex("0000000000000000")),
            ],
        )
    assert compact_events(events) == [
        (1, 42, 1),
        (1, 30, 1),
        (0, 0, 0),
        (1, 42, 0),
        (0, 0, 0),
        (1, 30, 0),
        (0, 0, 0),
    ]
    assert status["counters"]["frames_received"] == 3
    assert status["counters"]["us_sub_keyboard_reports"] == 3


def test_login_sequence_preserves_pi_and_enter_events() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        events, status = run_uidd(
            Path(tmpdir),
            [
                encode_hid_report_request(KIND_US_SUB_KEYBOARD, bytes.fromhex("0000130000000000")),
                encode_hid_report_request(KIND_US_SUB_KEYBOARD, bytes(8)),
                encode_hid_report_request(KIND_US_SUB_KEYBOARD, bytes.fromhex("00000c0000000000")),
                encode_hid_report_request(KIND_US_SUB_KEYBOARD, bytes(8)),
                encode_hid_report_request(KIND_US_SUB_KEYBOARD, bytes.fromhex("0000280000000000")),
                encode_hid_report_request(KIND_US_SUB_KEYBOARD, bytes(8)),
            ],
        )
    assert compact_events(events) == [
        (1, 25, 1),
        (0, 0, 0),
        (1, 25, 0),
        (0, 0, 0),
        (1, 23, 1),
        (0, 0, 0),
        (1, 23, 0),
        (0, 0, 0),
        (1, 28, 1),
        (0, 0, 0),
        (1, 28, 0),
        (0, 0, 0),
    ]
    assert status["counters"]["frames_received"] == 6
    assert status["counters"]["key_events"] == 6


def test_invalid_frame_is_counted_without_events() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        events, status = run_uidd(Path(tmpdir), [b"not-a-valid-frame"])
    assert events == []
    assert status["counters"]["frames_received"] == 0
    assert status["counters"]["invalid_frames"] == 1
    assert status["uinput"]["last_error"] == "invalid frame size"


def test_unsupported_frame_kind_is_counted_without_events() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        events, status = run_uidd(
            Path(tmpdir),
            [encode_hid_report_request(KIND_MOUSE, bytes.fromhex("01020304"))],
        )
    assert events == []
    assert status["counters"]["frames_received"] == 0
    assert status["counters"]["unsupported_frames"] == 1
    assert status["counters"]["invalid_frames"] == 0
    assert status["uinput"]["last_error"] == "unsupported kind"


def test_status_schema_and_paths_are_reported() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        events, status = run_uidd(
            tmp,
            [encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000000000000000"))],
        )
    assert events == []
    assert status["schema"] == "hidloom.uidd.status.v1"
    assert status["process"] is True
    assert status["dry_run"] is True
    assert status["socket"] == {"path": str(tmp / "uidd_reports.sock"), "listening": True}
    assert status["uinput"] == {
        "path": "/dev/uinput",
        "open": False,
        "last_error": "dry_run",
    }
    assert status["counters"]["frames_received"] == 1
    assert status["counters"]["keyboard_reports"] == 1
    assert status["counters"]["key_events"] == 0
    assert status["counters"]["sync_events"] == 0


def main() -> None:
    build_tool()
    test_keyboard_report_diff_to_linux_events()
    test_modifier_and_us_sub_keyboard_reports_share_diff_state()
    test_login_sequence_preserves_pi_and_enter_events()
    test_invalid_frame_is_counted_without_events()
    test_unsupported_frame_kind_is_counted_without_events()
    test_status_schema_and_paths_are_reported()
    print("ok: hidloom-uidd native dry-run sink")


if __name__ == "__main__":
    main()
