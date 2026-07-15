#!/usr/bin/env python3
"""Regression tests for the native hidloom-hidd HID report broker."""
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
    KIND_CONSUMER,
    KIND_KEYBOARD,
    KIND_MOUSE,
    KIND_US_SUB_KEYBOARD,
    encode_hid_report_request,
)

TOOL_DIR = ROOT / "tools" / "hidloom_hidd"
BIN = TOOL_DIR / "target" / "release" / "hidloom-hidd"


def build_tool() -> None:
    subprocess.run(["make", "-C", str(TOOL_DIR)], check=True)


def wait_for_socket(path: Path) -> None:
    deadline = time.time() + 2.0
    while time.time() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    raise AssertionError(f"socket did not appear: {path}")


def run_hidd(tmp: Path, frames: list[bytes], *, extra_env: dict[str, str] | None = None) -> tuple[bytes, bytes, dict]:
    sock_path = tmp / "usbd_hid_reports.sock"
    hidg0 = tmp / "hidg0"
    hidg2 = tmp / "hidg2"
    status = tmp / "hidd-status.json"
    hidg0.write_bytes(b"")
    hidg2.write_bytes(b"")

    env = os.environ.copy()
    env.update(
        {
            "USBD_HID_REPORT_SOCKET": str(sock_path),
            "USBD_HID_REPORT_PATH": str(hidg0),
            "USBD_US_SUB_HID_REPORT_PATH": str(hidg2),
            "HIDD_STATUS_PATH": str(status),
            "USBD_HID_WRITE_RETRY_TIMEOUT_SEC": "0.02",
            "USBD_HID_WRITE_RETRY_INTERVAL_SEC": "0.001",
            "USBD_KEYBOARD_REPORT_HZ": "2000",
            "USBD_MOUSE_REPORT_HZ": "1000",
        }
    )
    if extra_env:
        env.update(extra_env)

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
    status_payload = json.loads(status.read_text(encoding="utf-8"))
    return hidg0.read_bytes(), hidg2.read_bytes(), status_payload


def test_basic_report_mapping() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        hidg0, hidg2, status = run_hidd(
            Path(tmpdir),
            [
                encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000040000000000")),
                encode_hid_report_request(KIND_US_SUB_KEYBOARD, bytes.fromhex("0000900000000000")),
                encode_hid_report_request(KIND_MOUSE, bytes.fromhex("01020304")),
                encode_hid_report_request(KIND_CONSUMER, bytes.fromhex("e900")),
            ],
        )
    assert hidg0 == (
        bytes.fromhex("010000040000000000")
        + bytes.fromhex("0201020304")
        + bytes.fromhex("03e900")
    )
    assert hidg2 == bytes.fromhex("0000900000000000")
    assert status["counters"]["frames_received"] == 4
    assert status["counters"]["keyboard_reports"] == 1
    assert status["counters"]["us_sub_keyboard_reports"] == 1
    assert status["counters"]["mouse_reports"] == 1
    assert status["counters"]["consumer_reports"] == 1


def test_keyboard_release_merge() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        hidg0, _hidg2, status = run_hidd(
            Path(tmpdir),
            [
                encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000040000000000")),
                encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000000000000000")),
                encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000050000000000")),
            ],
            extra_env={"USBD_KEYBOARD_RELEASE_MERGE_WINDOW_SEC": "0.050"},
        )
    assert hidg0 == (
        bytes.fromhex("010000040000000000")
        + bytes.fromhex("010000050000000000")
    )
    assert status["counters"]["keyboard_reports"] == 2


def test_keyboard_release_overlap_preserves_release_before_next_state() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        hidg0, _hidg2, status = run_hidd(
            Path(tmpdir),
            [
                encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000040000000000")),
                encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000000000000000")),
                encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000040500000000")),
            ],
            extra_env={"USBD_KEYBOARD_RELEASE_MERGE_WINDOW_SEC": "0.050"},
        )
    assert hidg0 == (
        bytes.fromhex("010000040000000000")
        + bytes.fromhex("010000000000000000")
        + bytes.fromhex("010000040500000000")
    )
    assert status["counters"]["keyboard_reports"] == 3


def test_keyboard_release_default_window_merges_fast_roll() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        hidg0, _hidg2, status = run_hidd(
            Path(tmpdir),
            [
                encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000040000000000")),
                encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000000000000000")),
                encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000050000000000")),
            ],
        )
    assert hidg0 == (
        bytes.fromhex("010000040000000000")
        + bytes.fromhex("010000050000000000")
    )
    assert status["counters"]["keyboard_reports"] == 2


def test_keyboard_release_same_state_repress_preserves_release() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        hidg0, _hidg2, status = run_hidd(
            Path(tmpdir),
            [
                encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000040000000000")),
                encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000000000000000")),
                encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000040000000000")),
            ],
            extra_env={"USBD_KEYBOARD_RELEASE_MERGE_WINDOW_SEC": "0.050"},
        )
    assert hidg0 == (
        bytes.fromhex("010000040000000000")
        + bytes.fromhex("010000000000000000")
        + bytes.fromhex("010000040000000000")
    )
    assert status["counters"]["keyboard_reports"] == 3


def test_keyboard_release_modifier_repress_preserves_release() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        hidg0, _hidg2, status = run_hidd(
            Path(tmpdir),
            [
                encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0200000000000000")),
                encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000000000000000")),
                encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0200000000000000")),
            ],
            extra_env={"USBD_KEYBOARD_RELEASE_MERGE_WINDOW_SEC": "0.050"},
        )
    assert hidg0 == (
        bytes.fromhex("010200000000000000")
        + bytes.fromhex("010000000000000000")
        + bytes.fromhex("010200000000000000")
    )
    assert status["counters"]["keyboard_reports"] == 3


def test_frame_log_records_release_merge_decision() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        frame_log = tmp / "hidd-frames.ndjson"
        hidg0, _hidg2, status = run_hidd(
            tmp,
            [
                encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000040000000000")),
                encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000000000000000")),
                encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000050000000000")),
            ],
            extra_env={
                "USBD_KEYBOARD_RELEASE_MERGE_WINDOW_SEC": "0.050",
                "HIDD_FRAME_LOG_PATH": str(frame_log),
            },
        )
        events = [json.loads(line) for line in frame_log.read_text(encoding="utf-8").splitlines()]
    assert hidg0 == (
        bytes.fromhex("010000040000000000")
        + bytes.fromhex("010000050000000000")
    )
    assert status["counters"]["keyboard_reports"] == 2
    assert [event["t"] for event in events].count("hidd_frame_received") == 3
    assert any(event["t"] == "hidd_keyboard_release_pending" for event in events)
    merged = [event for event in events if event["t"] == "hidd_keyboard_release_merged"]
    assert merged
    assert merged[0]["dropped_release"] == "010000000000000000"
    assert merged[0]["next_report"] == "010000050000000000"


def test_invalid_frame_is_counted_without_endpoint_write() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        hidg0, hidg2, status = run_hidd(Path(tmpdir), [b"not-a-valid-frame"])
    assert hidg0 == b""
    assert hidg2 == b""
    assert status["counters"]["frames_received"] == 0
    assert status["counters"]["invalid_frames"] == 1


def test_live_status_updates_before_exit() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        sock_path = tmp / "usbd_hid_reports.sock"
        hidg0 = tmp / "hidg0"
        hidg2 = tmp / "hidg2"
        status = tmp / "hidd-status.json"
        hidg0.write_bytes(b"")
        hidg2.write_bytes(b"")

        env = os.environ.copy()
        env.update(
            {
                "USBD_HID_REPORT_SOCKET": str(sock_path),
                "USBD_HID_REPORT_PATH": str(hidg0),
                "USBD_US_SUB_HID_REPORT_PATH": str(hidg2),
                "HIDD_STATUS_PATH": str(status),
                "USBD_KEYBOARD_REPORT_HZ": "2000",
            }
        )

        proc = subprocess.Popen([str(BIN)], env=env)
        try:
            wait_for_socket(sock_path)
            sender = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            try:
                sender.sendto(
                    encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000040000000000")),
                    str(sock_path),
                )
            finally:
                sender.close()

            deadline = time.time() + 2.0
            while time.time() < deadline:
                payload = json.loads(status.read_text(encoding="utf-8"))
                if payload["counters"]["frames_received"] == 1:
                    break
                time.sleep(0.01)
            else:
                raise AssertionError("live status counter did not update before process exit")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=1.0)


def test_keyboard_release_merge_default_window_is_roll_friendly() -> None:
    rust_source = (TOOL_DIR / "src" / "main.rs").read_text(encoding="utf-8")
    python_source = (ROOT / "daemon" / "usbd" / "usbd.py").read_text(encoding="utf-8")
    assert '"USBD_KEYBOARD_RELEASE_MERGE_WINDOW_SEC",\n            0.016,' in rust_source
    assert 'KEYBOARD_RELEASE_MERGE_WINDOW_SEC = _env_float("USBD_KEYBOARD_RELEASE_MERGE_WINDOW_SEC", 0.016' in python_source


def main() -> None:
    build_tool()
    test_basic_report_mapping()
    test_keyboard_release_merge()
    test_keyboard_release_overlap_preserves_release_before_next_state()
    test_keyboard_release_default_window_merges_fast_roll()
    test_keyboard_release_same_state_repress_preserves_release()
    test_keyboard_release_modifier_repress_preserves_release()
    test_frame_log_records_release_merge_decision()
    test_invalid_frame_is_counted_without_endpoint_write()
    test_live_status_updates_before_exit()
    test_keyboard_release_merge_default_window_is_roll_friendly()
    print("ok: hidloom-hidd native broker")


if __name__ == "__main__":
    main()
