#!/usr/bin/env python3
"""Regression tests for the native hidloom-logicd-core fixture path."""
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

from logicd.hid_report import HidState, KEYCODE  # noqa: E402
from usbd.hid_report_broker import KIND_KEYBOARD, KIND_US_SUB_KEYBOARD, encode_hid_report_request  # noqa: E402

TOOL_DIR = ROOT / "tools" / "hidloom_logicd_core"
BIN = TOOL_DIR / "target" / "release" / "hidloom-logicd-core"
SHADOW_REPLAY = ROOT / "tools" / "logicd_core_shadow_replay.py"
BROKER_CAPTURE = ROOT / "tools" / "usbd_hid_report_capture.py"
PARITY_COMPARE = ROOT / "tools" / "logicd_core_parity_compare.py"
PYTHON_REPLAY = ROOT / "tools" / "logicd_python_matrix_replay.py"
PARITY_SUITE = ROOT / "tools" / "logicd_core_parity_suite.py"
ASYNC_IO_TIMEOUT_SECONDS = 10.0


def build_tool() -> None:
    subprocess.run(["make", "-C", str(TOOL_DIR)], check=True)


def run_core_replay(
    tmp: Path,
    keymap: dict,
    packets: bytes,
    *,
    split_keyboard: bool = False,
    split_route: str = "jis_special_us_default",
) -> list[dict]:
    keymap_path = tmp / "keymap.json"
    keymap_path.write_text(json.dumps(keymap), encoding="utf-8")
    replay_path = tmp / "matrix.bin"
    replay_path.write_bytes(packets)
    env = os.environ.copy()
    env.update(
        {
            "HIDLOOM_REPO_ROOT": str(ROOT),
            "LOGICD_CORE_KEYMAP_PATH": str(keymap_path),
            "LOGICD_CORE_DEFAULT_KEYMAP_PATH": str(keymap_path),
            "LOGICD_CORE_KEYCODES_PATH": str(ROOT / "config/default/keycodes.json"),
            "LOGICD_CORE_DEFAULT_KEYCODES_PATH": str(ROOT / "config/default/keycodes.json"),
            "LOGICD_USB_SPLIT_KEYBOARD": "1" if split_keyboard else "0",
            "LOGICD_USB_SPLIT_KEYBOARD_ROUTE": split_route,
        }
    )
    result = subprocess.run(
        [str(BIN), "--replay", str(replay_path)],
        check=True,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def core_env(tmp: Path, keymap: dict) -> dict[str, str]:
    keymap_path = tmp / "keymap.json"
    keymap_path.write_text(json.dumps(keymap), encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "HIDLOOM_REPO_ROOT": str(ROOT),
            "LOGICD_CORE_KEYMAP_PATH": str(keymap_path),
            "LOGICD_CORE_DEFAULT_KEYMAP_PATH": str(keymap_path),
            "LOGICD_CORE_KEYCODES_PATH": str(ROOT / "config/default/keycodes.json"),
            "LOGICD_CORE_DEFAULT_KEYCODES_PATH": str(ROOT / "config/default/keycodes.json"),
            "LOGICD_USB_SPLIT_KEYBOARD": "0",
            "LOGICD_CORE_MATRIX_TAP_SOCKET": "none",
        }
    )
    return env


def wait_for_path(path: Path) -> None:
    deadline = time.monotonic() + ASYNC_IO_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    raise AssertionError(f"path did not appear: {path}")


def wait_for_json(path: Path) -> dict:
    deadline = time.monotonic() + ASYNC_IO_TIMEOUT_SECONDS
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(0.01)
    raise AssertionError(f"json did not become readable: {path} last_error={last_error}")


def wait_for_socket(path: Path) -> None:
    deadline = time.monotonic() + ASYNC_IO_TIMEOUT_SECONDS
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if path.exists():
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.settimeout(0.2)
                    client.connect(str(path))
                return
            except OSError as exc:
                last_error = exc
        time.sleep(0.02)
    raise AssertionError(f"socket did not become connectable: {path} last_error={last_error}")


def ctrl_request(
    sock_path: Path,
    payload: dict,
    *,
    timeout: float = ASYNC_IO_TIMEOUT_SECONDS,
) -> dict:
    if timeout <= 0:
        raise ValueError("ctrl request timeout must be positive")
    started = time.monotonic()
    deadline = started + timeout
    data = b""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        try:
            client.settimeout(timeout)
            client.connect(str(sock_path))
            client.sendall((json.dumps(payload) + "\n").encode())
            while not data.endswith(b"\n"):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("ctrl request deadline expired")
                client.settimeout(remaining)
                chunk = client.recv(4096)
                if not chunk:
                    break
                data += chunk
        except TimeoutError as exc:
            elapsed = time.monotonic() - started
            request = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            raise AssertionError(
                "logicd-core ctrl request timed out "
                f"after {elapsed:.3f}s socket={sock_path} "
                f"request={request} received={data.hex()}"
            ) from exc
    return json.loads(data.decode()) if data else {}


def flat_keymap(layers: list[dict[str, str]]) -> dict:
    return {"layers": layers}


def report_hex(report: bytes) -> str:
    return report.hex()


def test_basic_press_release_matches_python_hid_state() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        events = run_core_replay(
            Path(tmpdir),
            flat_keymap([{"0,0": "KC_A"}]),
            b"P00\nR00\n",
        )
    state = HidState()
    state.press(KEYCODE["KC_A"])
    press = state.build()
    state.release(KEYCODE["KC_A"])
    release = state.build()
    assert [event["report"] for event in events] == [report_hex(press), report_hex(release)]


def test_modifier_chord_matches_python_hid_state() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        events = run_core_replay(
            Path(tmpdir),
            flat_keymap([{"0,0": "KC_LSHIFT", "0,1": "KC_A"}]),
            b"P00\nP01\nR00\nR01\n",
        )
    state = HidState()
    expected: list[str] = []
    for op, code in [
        ("press", KEYCODE["KC_LSHIFT"]),
        ("press", KEYCODE["KC_A"]),
        ("release", KEYCODE["KC_LSHIFT"]),
        ("release", KEYCODE["KC_A"]),
    ]:
        getattr(state, op)(code)
        expected.append(report_hex(state.build()))
    assert [event["report"] for event in events] == expected


def test_momentary_layer_actions_are_native() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        events = run_core_replay(
            Path(tmpdir),
            flat_keymap([
                {"0,0": "KC_A", "0,1": "MO(1)"},
                {"0,0": "KC_B"},
            ]),
            b"P01\nP00\nR01\nR00\n",
        )
    assert [(event["t"], event["report"]) for event in events] == [
        ("keyboard_report", "0000050000000000"),
        ("keyboard_report", "0000000000000000"),
    ]


def test_toggle_to_default_and_oneshot_layer_actions_are_native() -> None:
    keymap = flat_keymap([
        {
            "0,0": "KC_A",
            "0,1": "TG(1)",
            "0,2": "TO(2)",
            "0,3": "DF(1)",
            "0,4": "OSL(2)",
        },
        {"0,0": "KC_B"},
        {"0,0": "KC_C"},
    ])
    cases = [
        (b"P01\nR01\nP00\nR00\n", ["0000050000000000", "0000000000000000"]),
        (b"P02\nR02\nP00\nR00\n", ["0000060000000000", "0000000000000000"]),
        (b"P03\nR03\nP00\nR00\n", ["0000050000000000", "0000000000000000"]),
        (
            b"P04\nR04\nP00\nR00\nP00\nR00\n",
            [
                "0000060000000000",
                "0000000000000000",
                "0000040000000000",
                "0000000000000000",
            ],
        ),
    ]
    for packets, expected in cases:
        with tempfile.TemporaryDirectory() as tmpdir:
            events = run_core_replay(Path(tmpdir), keymap, packets)
        assert [event["report"] for event in events] == expected


def test_broker_frame_matches_python_encoder() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        events = run_core_replay(
            Path(tmpdir),
            flat_keymap([{"0,0": "KC_A"}]),
            b"P00\n",
        )
    expected = encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000040000000000")).hex()
    assert events[0]["frame"] == expected


def test_split_keyboard_routes_us_default_keys_to_sub_keyboard() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        events = run_core_replay(
            Path(tmpdir),
            flat_keymap([{"0,0": "KC_A"}]),
            b"P00\nR00\n",
            split_keyboard=True,
        )
    assert [(event["kind"], event["kind_name"], event["report"]) for event in events] == [
        (KIND_US_SUB_KEYBOARD, "us_sub_keyboard", "0000040000000000"),
        (KIND_US_SUB_KEYBOARD, "us_sub_keyboard", "0000000000000000"),
    ]
    assert events[0]["frame"] == encode_hid_report_request(
        KIND_US_SUB_KEYBOARD,
        bytes.fromhex("0000040000000000"),
    ).hex()


def test_held_key_keeps_hid_slot_when_lead_key_releases() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        events = run_core_replay(
            Path(tmpdir),
            flat_keymap([{"0,0": "KC_K", "0,1": "KC_O"}]),
            b"P00\nP01\nR00\nR01\n",
            split_keyboard=True,
        )
    assert [(event["kind"], event["kind_name"], event["report"]) for event in events] == [
        (KIND_US_SUB_KEYBOARD, "us_sub_keyboard", "00000e0000000000"),
        (KIND_US_SUB_KEYBOARD, "us_sub_keyboard", "00000e1200000000"),
        (KIND_US_SUB_KEYBOARD, "us_sub_keyboard", "0000001200000000"),
        (KIND_US_SUB_KEYBOARD, "us_sub_keyboard", "0000000000000000"),
    ]


def test_split_keyboard_routes_jis_special_keys_to_main_keyboard() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        events = run_core_replay(
            Path(tmpdir),
            flat_keymap([{"0,0": "KC_LSHIFT", "0,1": "KC_RO"}]),
            b"P00\nP01\nR01\nR00\n",
            split_keyboard=True,
        )
    assert [(event["kind"], event["report"]) for event in events] == [
        (KIND_KEYBOARD, "0200000000000000"),
        (KIND_US_SUB_KEYBOARD, "0200000000000000"),
        (KIND_KEYBOARD, "0200870000000000"),
        (KIND_KEYBOARD, "0200000000000000"),
        (KIND_US_SUB_KEYBOARD, "0200000000000000"),
        (KIND_KEYBOARD, "0000000000000000"),
        (KIND_US_SUB_KEYBOARD, "0000000000000000"),
    ]


def test_split_keyboard_routes_modifier_only_to_both_keyboards() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        events = run_core_replay(
            Path(tmpdir),
            flat_keymap([{"0,0": "KC_LSHIFT"}]),
            b"P00\nR00\n",
            split_keyboard=True,
        )
    assert [(event["kind"], event["report"]) for event in events] == [
        (KIND_KEYBOARD, "0200000000000000"),
        (KIND_US_SUB_KEYBOARD, "0200000000000000"),
        (KIND_KEYBOARD, "0000000000000000"),
        (KIND_US_SUB_KEYBOARD, "0000000000000000"),
    ]


def test_split_keyboard_routes_henkan_aliases_to_main_keyboard() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        events = run_core_replay(
            Path(tmpdir),
            flat_keymap([{"0,0": "KC_HENK", "0,1": "KC_MHEN"}]),
            b"P00\nR00\nP01\nR01\n",
            split_keyboard=True,
        )
    assert [(event["kind"], event["report"]) for event in events] == [
        (KIND_KEYBOARD, "00008a0000000000"),
        (KIND_KEYBOARD, "0000000000000000"),
        (KIND_KEYBOARD, "00008b0000000000"),
        (KIND_KEYBOARD, "0000000000000000"),
    ]


def test_qmk_layer_tap_actions_delegate_to_companion() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        events = run_core_replay(
            Path(tmpdir),
            flat_keymap([{"0,0": "LT(1,KC_MUHENKAN)", "0,1": "LT(2,KC_HENKAN)"}]),
            b"P00\nR00\nP01\nR01\n",
            split_keyboard=True,
        )
    assert [(event["t"], event["packet"]) for event in events] == [
        ("delegated_matrix_event", "5030300a"),
        ("delegated_matrix_event", "5230300a"),
        ("delegated_matrix_event", "5030310a"),
        ("delegated_matrix_event", "5230310a"),
    ]


def test_output_control_actions_delegate_to_companion() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        events = run_core_replay(
            Path(tmpdir),
            flat_keymap([{"0,0": "KC_USB", "0,1": "KC_BT", "0,2": "KC_CONNAUTO", "0,3": "KC_CONSOLE"}]),
            b"P00\nR00\nP01\nR01\nP02\nR02\nP03\nR03\n",
        )
    assert [(event["t"], event["packet"]) for event in events] == [
        ("delegated_matrix_event", "5030300a"),
        ("delegated_matrix_event", "5230300a"),
        ("delegated_matrix_event", "5030310a"),
        ("delegated_matrix_event", "5230310a"),
        ("delegated_matrix_event", "5030320a"),
        ("delegated_matrix_event", "5230320a"),
        ("delegated_matrix_event", "5030330a"),
        ("delegated_matrix_event", "5230330a"),
    ]


def test_delegate_context_routes_following_key_to_companion() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        events = run_core_replay(
            Path(tmpdir),
            flat_keymap([{"0,0": "LT(1,KC_MUHENKAN)", "0,1": "KC_A"}]),
            b"P00\nP01\nR01\nR00\n",
            split_keyboard=True,
        )
    assert [(event["t"], event["packet"]) for event in events] == [
        ("delegated_matrix_event", "5030300a"),
        ("delegated_matrix_event", "5030310a"),
        ("delegated_matrix_event", "5230310a"),
        ("delegated_matrix_event", "5230300a"),
    ]


def test_split_keyboard_routes_zkhk_to_main_and_grave_to_sub_keyboard() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        grave_events = run_core_replay(
            Path(tmpdir),
            flat_keymap([{"0,0": "KC_GRV"}]),
            b"P00\nR00\n",
            split_keyboard=True,
        )
        zkhk_events = run_core_replay(
            Path(tmpdir),
            flat_keymap([{"0,0": "KC_ZKHK"}]),
            b"P00\nR00\n",
            split_keyboard=True,
        )
    assert [(event["kind"], event["report"]) for event in grave_events] == [
        (KIND_US_SUB_KEYBOARD, "0000350000000000"),
        (KIND_US_SUB_KEYBOARD, "0000000000000000"),
    ]
    assert [(event["kind"], event["report"]) for event in zkhk_events] == [
        (KIND_KEYBOARD, "0000350000000000"),
        (KIND_KEYBOARD, "0000000000000000"),
    ]


def test_shadow_serve_updates_status_without_broker_output() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        matrix_socket = tmp / "matrix_events_shadow.sock"
        ctrl_socket = tmp / "logicd_core_ctrl.sock"
        status_path = tmp / "logicd-core-status.json"
        env = core_env(tmp, flat_keymap([{"0,0": "KC_A"}]))
        env.update(
            {
                "LOGICD_CORE_MATRIX_SOCKET": str(matrix_socket),
                "LOGICD_CORE_CTRL_SOCKET": str(ctrl_socket),
                "LOGICD_CORE_STATUS_PATH": str(status_path),
                "LOGICD_CORE_HID_REPORT_SOCKET": str(tmp / "missing-broker.sock"),
                "LOGICD_CORE_OUTPUT_ENABLED": "0",
            }
        )
        proc = subprocess.Popen(
            [str(BIN), "--serve", "--packets", "2"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            wait_for_socket(matrix_socket)
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                client.connect(str(matrix_socket))
                client.sendall(b"P00\nR00\n")
            finally:
                client.close()
            stdout, stderr = proc.communicate(timeout=3.0)
        finally:
            if proc.poll() is None:
                proc.terminate()
                stdout, stderr = proc.communicate(timeout=1.0)
        assert proc.returncode == 0
        assert stdout == ""
        assert stderr == ""
        assert status_path.exists()
        payload = json.loads(status_path.read_text(encoding="utf-8"))
        assert payload["schema"] == "logicd-core.status.v1"
        assert payload["output_enabled"] is False
        assert payload["broker_socket"]["available"] is False
        assert payload["counters"]["matrix_events"] == 2
        assert payload["counters"]["report_previews"] == 2
        assert payload["counters"]["broker_frames_sent"] == 0
        assert payload["state"]["pressed_matrix"] == 0


def test_core_emits_matrix_tap_for_core_handled_keys() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        matrix_socket = tmp / "matrix_events_shadow.sock"
        ctrl_socket = tmp / "logicd_core_ctrl.sock"
        tap_socket = tmp / "matrix_tap_events.sock"
        status_path = tmp / "logicd-core-status.json"
        env = core_env(tmp, flat_keymap([{"0,0": "KC_A", "0,1": "LT(1,KC_A)"}]))
        env.update(
            {
                "LOGICD_CORE_MATRIX_SOCKET": str(matrix_socket),
                "LOGICD_CORE_CTRL_SOCKET": str(ctrl_socket),
                "LOGICD_CORE_DELEGATE_SOCKET": "none",
                "LOGICD_CORE_MATRIX_TAP_SOCKET": str(tap_socket),
                "LOGICD_CORE_STATUS_PATH": str(status_path),
                "LOGICD_CORE_HID_REPORT_SOCKET": str(tmp / "missing-broker.sock"),
                "LOGICD_CORE_OUTPUT_ENABLED": "0",
            }
        )
        tap = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        tap.settimeout(2.0)
        tap.bind(str(tap_socket))
        tap.listen(4)
        proc = subprocess.Popen(
            [str(BIN), "--serve", "--packets", "3"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            wait_for_socket(matrix_socket)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as matrix:
                matrix.settimeout(2.0)
                matrix.connect(str(matrix_socket))
                matrix.sendall(b"P00\nR00\nP01\n")
            packets = []
            for _ in range(2):
                conn, _addr = tap.accept()
                with conn:
                    conn.settimeout(2.0)
                    packets.append(conn.recv(4))
            stdout, stderr = proc.communicate(timeout=3.0)
        finally:
            if proc.poll() is None:
                proc.terminate()
                stdout, stderr = proc.communicate(timeout=1.0)
            tap.close()
        assert proc.returncode == 0
        assert stdout == ""
        assert stderr == ""
        assert packets == [b"P00\n", b"R00\n"]
        payload = json.loads(status_path.read_text(encoding="utf-8"))
        assert payload["matrix_tap_socket"]["enabled"] is True
        assert payload["counters"]["matrix_tap_events"] == 2
        assert payload["counters"]["matrix_tap_errors"] == 0


def test_ctrl_status_release_all_and_set_output() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        matrix_socket = tmp / "matrix_events_shadow.sock"
        ctrl_socket = tmp / "logicd_core_ctrl.sock"
        status_path = tmp / "logicd-core-status.json"
        env = core_env(tmp, flat_keymap([{"0,0": "KC_A"}]))
        env.update(
            {
                "LOGICD_CORE_MATRIX_SOCKET": str(matrix_socket),
                "LOGICD_CORE_CTRL_SOCKET": str(ctrl_socket),
                "LOGICD_CORE_STATUS_PATH": str(status_path),
                "LOGICD_CORE_HID_REPORT_SOCKET": str(tmp / "missing-broker.sock"),
                "LOGICD_CORE_OUTPUT_ENABLED": "0",
            }
        )
        proc = subprocess.Popen(
            [str(BIN), "--serve"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            wait_for_socket(matrix_socket)
            wait_for_socket(ctrl_socket)
            status = ctrl_request(ctrl_socket, {"t": "status"})
            assert status["schema"] == "logicd-core.status.v1"
            assert status["output_enabled"] is False
            assert status["state"]["pressed_matrix"] == 0
            assert ctrl_request(ctrl_socket, {"t": "set_output", "enabled": False}) == {
                "result": "ok",
                "output_enabled": False,
            }
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as matrix:
                matrix.settimeout(2.0)
                matrix.connect(str(matrix_socket))
                matrix.sendall(b"P00\n")
                deadline = time.monotonic() + ASYNC_IO_TIMEOUT_SECONDS
                while time.monotonic() < deadline:
                    status = ctrl_request(ctrl_socket, {"t": "status"})
                    if status["state"]["pressed_matrix"] == 1:
                        break
                    time.sleep(0.02)
                assert status["state"]["pressed_matrix"] == 1
                assert status["state"]["pressed_keys"] == 1
                released = ctrl_request(ctrl_socket, {"t": "release_all"})
                assert released == {"result": "ok", "released": True}
                status = ctrl_request(ctrl_socket, {"t": "status"})
                assert status["state"]["pressed_matrix"] == 0
                assert status["state"]["pressed_keys"] == 0
                assert status["counters"]["report_previews"] == 2
        finally:
            proc.terminate()
            stdout, stderr = proc.communicate(timeout=3.0)
        assert stdout == ""
        assert proc.returncode in (0, -15)


def test_ctrl_status_burst_survives_backpressure() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        matrix_socket = tmp / "matrix_events_shadow.sock"
        ctrl_socket = tmp / "logicd_core_ctrl.sock"
        status_path = tmp / "logicd-core-status.json"
        env = core_env(tmp, flat_keymap([{"0,0": "KC_A"}]))
        env.update(
            {
                "LOGICD_CORE_MATRIX_SOCKET": str(matrix_socket),
                "LOGICD_CORE_CTRL_SOCKET": str(ctrl_socket),
                "LOGICD_CORE_STATUS_PATH": str(status_path),
                "LOGICD_CORE_HID_REPORT_SOCKET": str(tmp / "missing-broker.sock"),
                "LOGICD_CORE_OUTPUT_ENABLED": "0",
            }
        )
        proc = subprocess.Popen(
            [str(BIN), "--serve"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            wait_for_socket(ctrl_socket)
            request_count = 256
            request = (json.dumps({"t": "status"}) + "\n").encode()
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(ASYNC_IO_TIMEOUT_SECONDS)
                client.connect(str(ctrl_socket))
                client.sendall(request * request_count)
                time.sleep(0.05)
                deadline = time.monotonic() + ASYNC_IO_TIMEOUT_SECONDS
                data = bytearray()
                response_count = 0
                while response_count < request_count:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise AssertionError(
                            "logicd-core ctrl burst response deadline expired "
                            f"responses={response_count}/{request_count} bytes={len(data)}"
                        )
                    client.settimeout(remaining)
                    chunk = client.recv(65536)
                    if not chunk:
                        break
                    data.extend(chunk)
                    response_count += chunk.count(b"\n")
            responses = [json.loads(line) for line in data.splitlines() if line]
            assert len(responses) == request_count
            assert all(response["schema"] == "logicd-core.status.v1" for response in responses)
        finally:
            proc.terminate()
            stdout, stderr = proc.communicate(timeout=ASYNC_IO_TIMEOUT_SECONDS)
        assert stdout == ""
        assert stderr == ""
        assert proc.returncode in (0, -15)


def test_ctrl_matrix_delegate_all_routes_keys_to_companion() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        matrix_socket = tmp / "matrix_events_shadow.sock"
        ctrl_socket = tmp / "logicd_core_ctrl.sock"
        broker_socket = tmp / "broker.sock"
        delegate_socket = tmp / "logicd_delegate_events.sock"
        status_path = tmp / "logicd-core-status.json"
        env = core_env(tmp, flat_keymap([{"0,0": "KC_A"}]))
        env.update(
            {
                "LOGICD_CORE_MATRIX_SOCKET": str(matrix_socket),
                "LOGICD_CORE_CTRL_SOCKET": str(ctrl_socket),
                "LOGICD_CORE_DELEGATE_SOCKET": str(delegate_socket),
                "LOGICD_CORE_STATUS_PATH": str(status_path),
                "LOGICD_CORE_HID_REPORT_SOCKET": str(broker_socket),
                "LOGICD_CORE_OUTPUT_ENABLED": "1",
            }
        )
        broker = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        broker.settimeout(0.2)
        broker.bind(str(broker_socket))
        delegate = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        delegate.settimeout(2.0)
        delegate.bind(str(delegate_socket))
        delegate.listen(1)
        proc = subprocess.Popen(
            [str(BIN), "--serve"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            wait_for_socket(matrix_socket)
            wait_for_socket(ctrl_socket)
            assert ctrl_request(ctrl_socket, {"t": "set_matrix_delegate_all", "enabled": True}) == {
                "result": "ok",
                "matrix_delegate_all": True,
                "released": False,
            }
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as matrix:
                matrix.settimeout(2.0)
                matrix.connect(str(matrix_socket))
                matrix.sendall(b"P00\n")
            conn, _addr = delegate.accept()
            with conn:
                conn.settimeout(2.0)
                assert conn.recv(4) == b"P00\n"
            try:
                broker.recv(128)
            except (TimeoutError, socket.timeout):
                pass
            else:
                raise AssertionError("delegate-all matrix event emitted a broker frame")
            status = ctrl_request(ctrl_socket, {"t": "status"})
            assert status["routing"]["matrix_delegate_all"] is True
            assert status["state"]["force_delegate_all"] is True
            assert status["state"]["pressed_keys"] == 0
            assert ctrl_request(ctrl_socket, {"t": "set_matrix_delegate_all", "enabled": False}) == {
                "result": "ok",
                "matrix_delegate_all": False,
                "released": False,
            }
        finally:
            proc.terminate()
            stdout, stderr = proc.communicate(timeout=3.0)
            broker.close()
            delegate.close()
        assert stdout == ""
        assert proc.returncode in (0, -15)


def test_ctrl_key_event_merges_with_matrix_held_key() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        matrix_socket = tmp / "matrix_events_shadow.sock"
        ctrl_socket = tmp / "logicd_core_ctrl.sock"
        broker_socket = tmp / "broker.sock"
        status_path = tmp / "logicd-core-status.json"
        env = core_env(tmp, flat_keymap([{"0,0": "KC_A"}]))
        env.update(
            {
                "LOGICD_CORE_MATRIX_SOCKET": str(matrix_socket),
                "LOGICD_CORE_CTRL_SOCKET": str(ctrl_socket),
                "LOGICD_CORE_STATUS_PATH": str(status_path),
                "LOGICD_CORE_HID_REPORT_SOCKET": str(broker_socket),
                "LOGICD_CORE_OUTPUT_ENABLED": "1",
            }
        )
        broker = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        broker.settimeout(2.0)
        broker.bind(str(broker_socket))
        proc = subprocess.Popen(
            [str(BIN), "--serve"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            wait_for_socket(matrix_socket)
            wait_for_socket(ctrl_socket)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as matrix:
                matrix.settimeout(2.0)
                matrix.connect(str(matrix_socket))
                matrix.sendall(b"P00\n")
            assert broker.recv(128).hex() == encode_hid_report_request(
                KIND_KEYBOARD,
                bytes.fromhex("0000040000000000"),
            ).hex()
            assert ctrl_request(
                ctrl_socket,
                {"t": "key_event", "id": "helper:0,1:KC_B", "action": "KC_B", "is_press": True},
            ) == {"result": "ok", "emitted": 1}
            assert broker.recv(128).hex() == encode_hid_report_request(
                KIND_KEYBOARD,
                bytes.fromhex("0000040500000000"),
            ).hex()
            assert ctrl_request(
                ctrl_socket,
                {"t": "key_event", "id": "helper:0,1:KC_B", "action": "KC_B", "is_press": False},
            ) == {"result": "ok", "emitted": 1}
            assert broker.recv(128).hex() == encode_hid_report_request(
                KIND_KEYBOARD,
                bytes.fromhex("0000040000000000"),
            ).hex()
            status = ctrl_request(ctrl_socket, {"t": "status"})
            assert status["state"]["pressed_matrix"] == 1
            assert status["state"]["injected_keys"] == 0
            assert status["counters"]["injected_key_events"] == 2
        finally:
            proc.terminate()
            stdout, stderr = proc.communicate(timeout=3.0)
            broker.close()
        assert stdout == ""
        assert proc.returncode in (0, -15)


def test_ctrl_key_event_release_all_clears_injected_state() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        matrix_socket = tmp / "matrix_events_shadow.sock"
        ctrl_socket = tmp / "logicd_core_ctrl.sock"
        broker_socket = tmp / "broker.sock"
        status_path = tmp / "logicd-core-status.json"
        env = core_env(tmp, flat_keymap([{"0,0": "KC_A"}]))
        env.update(
            {
                "LOGICD_CORE_MATRIX_SOCKET": str(matrix_socket),
                "LOGICD_CORE_CTRL_SOCKET": str(ctrl_socket),
                "LOGICD_CORE_STATUS_PATH": str(status_path),
                "LOGICD_CORE_HID_REPORT_SOCKET": str(broker_socket),
                "LOGICD_CORE_OUTPUT_ENABLED": "1",
            }
        )
        broker = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        broker.settimeout(2.0)
        broker.bind(str(broker_socket))
        proc = subprocess.Popen(
            [str(BIN), "--serve"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            wait_for_socket(ctrl_socket)
            assert ctrl_request(
                ctrl_socket,
                {"t": "key_event", "id": "helper:0,1:KC_B", "action": "KC_B", "is_press": True},
            ) == {"result": "ok", "emitted": 1}
            assert broker.recv(128).hex() == encode_hid_report_request(
                KIND_KEYBOARD,
                bytes.fromhex("0000050000000000"),
            ).hex()
            status = ctrl_request(ctrl_socket, {"t": "status"})
            assert status["state"]["injected_keys"] == 1
            assert ctrl_request(ctrl_socket, {"t": "release_all"}) == {"result": "ok", "released": True}
            assert broker.recv(128).hex() == encode_hid_report_request(
                KIND_KEYBOARD,
                bytes.fromhex("0000000000000000"),
            ).hex()
            status = ctrl_request(ctrl_socket, {"t": "status"})
            assert status["state"]["injected_keys"] == 0
            assert status["state"]["pressed_keys"] == 0
        finally:
            proc.terminate()
            stdout, stderr = proc.communicate(timeout=3.0)
            broker.close()
        assert stdout == ""
        assert proc.returncode in (0, -15)


def test_ctrl_key_event_duplicate_edges_are_idempotent() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        ctrl_socket = tmp / "logicd_core_ctrl.sock"
        broker_socket = tmp / "broker.sock"
        status_path = tmp / "logicd-core-status.json"
        env = core_env(tmp, flat_keymap([{}]))
        env.update(
            {
                "LOGICD_CORE_MATRIX_SOCKET": str(tmp / "matrix_events_shadow.sock"),
                "LOGICD_CORE_CTRL_SOCKET": str(ctrl_socket),
                "LOGICD_CORE_STATUS_PATH": str(status_path),
                "LOGICD_CORE_HID_REPORT_SOCKET": str(broker_socket),
                "LOGICD_CORE_OUTPUT_ENABLED": "1",
            }
        )
        broker = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        broker.settimeout(0.2)
        broker.bind(str(broker_socket))
        proc = subprocess.Popen(
            [str(BIN), "--serve"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            wait_for_socket(ctrl_socket)
            payload = {"t": "key_event", "id": "helper:0,1:KC_B", "action": "KC_B", "is_press": True}
            assert ctrl_request(ctrl_socket, payload) == {"result": "ok", "emitted": 1}
            assert ctrl_request(ctrl_socket, payload) == {"result": "ok", "emitted": 0}
            assert broker.recv(128).hex() == encode_hid_report_request(
                KIND_KEYBOARD,
                bytes.fromhex("0000050000000000"),
            ).hex()
            payload["is_press"] = False
            assert ctrl_request(ctrl_socket, payload) == {"result": "ok", "emitted": 1}
            assert ctrl_request(ctrl_socket, payload) == {"result": "ok", "emitted": 0}
            assert broker.recv(128).hex() == encode_hid_report_request(
                KIND_KEYBOARD,
                bytes.fromhex("0000000000000000"),
            ).hex()
            try:
                broker.recv(128)
            except TimeoutError:
                pass
            except socket.timeout:
                pass
            else:
                raise AssertionError("duplicate injected edges emitted an extra broker frame")
            status = ctrl_request(ctrl_socket, {"t": "status"})
            assert status["counters"]["injected_duplicates"] == 2
        finally:
            proc.terminate()
            stdout, stderr = proc.communicate(timeout=3.0)
            broker.close()
        assert stdout == ""
        assert proc.returncode in (0, -15)


def test_ctrl_key_event_release_falls_back_to_unique_matching_action() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        ctrl_socket = tmp / "logicd_core_ctrl.sock"
        broker_socket = tmp / "broker.sock"
        status_path = tmp / "logicd-core-status.json"
        env = core_env(tmp, flat_keymap([{}]))
        env.update(
            {
                "LOGICD_CORE_MATRIX_SOCKET": str(tmp / "matrix_events_shadow.sock"),
                "LOGICD_CORE_CTRL_SOCKET": str(ctrl_socket),
                "LOGICD_CORE_STATUS_PATH": str(status_path),
                "LOGICD_CORE_HID_REPORT_SOCKET": str(broker_socket),
                "LOGICD_CORE_OUTPUT_ENABLED": "1",
            }
        )
        broker = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        broker.settimeout(2.0)
        broker.bind(str(broker_socket))
        proc = subprocess.Popen(
            [str(BIN), "--serve"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            wait_for_socket(ctrl_socket)
            assert ctrl_request(
                ctrl_socket,
                {"t": "key_event", "id": "matrix:0,1:KC_B", "action": "KC_B", "is_press": True},
            ) == {"result": "ok", "emitted": 1}
            assert broker.recv(128).hex() == encode_hid_report_request(
                KIND_KEYBOARD,
                bytes.fromhex("0000050000000000"),
            ).hex()
            assert ctrl_request(
                ctrl_socket,
                {"t": "key_event", "id": "key_override:0,1:KC_B", "action": "KC_B", "is_press": False},
            ) == {"result": "ok", "emitted": 1}
            assert broker.recv(128).hex() == encode_hid_report_request(
                KIND_KEYBOARD,
                bytes.fromhex("0000000000000000"),
            ).hex()
            status = ctrl_request(ctrl_socket, {"t": "status"})
            assert status["state"]["injected_keys"] == 0
            assert status["state"]["pressed_keys"] == 0
            assert status["counters"]["injected_duplicates"] == 0
        finally:
            proc.terminate()
            stdout, stderr = proc.communicate(timeout=3.0)
            broker.close()
        assert stdout == ""
        assert proc.returncode in (0, -15)


def test_ctrl_release_all_cli_matches_exec_stop_path() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        matrix_socket = tmp / "matrix_events_shadow.sock"
        ctrl_socket = tmp / "logicd_core_ctrl.sock"
        status_path = tmp / "logicd-core-status.json"
        env = core_env(tmp, flat_keymap([{"0,0": "KC_A"}]))
        env.update(
            {
                "LOGICD_CORE_MATRIX_SOCKET": str(matrix_socket),
                "LOGICD_CORE_CTRL_SOCKET": str(ctrl_socket),
                "LOGICD_CORE_STATUS_PATH": str(status_path),
                "LOGICD_CORE_HID_REPORT_SOCKET": str(tmp / "missing-broker.sock"),
                "LOGICD_CORE_OUTPUT_ENABLED": "0",
            }
        )
        proc = subprocess.Popen(
            [str(BIN), "--serve"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            wait_for_socket(matrix_socket)
            wait_for_socket(ctrl_socket)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as matrix:
                matrix.settimeout(2.0)
                matrix.connect(str(matrix_socket))
                matrix.sendall(b"P00\n")
            deadline = time.monotonic() + ASYNC_IO_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                status = ctrl_request(ctrl_socket, {"t": "status"})
                if status["state"]["pressed_matrix"] == 1:
                    break
                time.sleep(0.02)
            assert status["state"]["pressed_matrix"] == 1
            result = subprocess.run(
                [str(BIN), "--ctrl-release-all"],
                check=True,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=ASYNC_IO_TIMEOUT_SECONDS,
            )
            assert json.loads(result.stdout) == {"result": "ok", "released": True}
            assert result.stderr == ""
            status = ctrl_request(ctrl_socket, {"t": "status"})
            assert status["state"]["pressed_matrix"] == 0
            assert status["state"]["pressed_keys"] == 0
            assert status["counters"]["report_previews"] == 2
        finally:
            proc.terminate()
            stdout, stderr = proc.communicate(timeout=3.0)
        assert stdout == ""
        assert proc.returncode in (0, -15)


def test_mark_stopped_cli_clears_stale_service_state() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        matrix_socket = tmp / "matrix_events_shadow.sock"
        ctrl_socket = tmp / "logicd_core_ctrl.sock"
        status_path = tmp / "logicd-core-status.json"
        env = core_env(tmp, flat_keymap([{"0,0": "KC_A"}]))
        env.update(
            {
                "LOGICD_CORE_MATRIX_SOCKET": str(matrix_socket),
                "LOGICD_CORE_CTRL_SOCKET": str(ctrl_socket),
                "LOGICD_CORE_STATUS_PATH": str(status_path),
                "LOGICD_CORE_HID_REPORT_SOCKET": str(tmp / "missing-broker.sock"),
                "LOGICD_CORE_OUTPUT_ENABLED": "0",
            }
        )
        proc = subprocess.Popen(
            [str(BIN), "--serve"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            wait_for_socket(matrix_socket)
            wait_for_socket(ctrl_socket)
            assert matrix_socket.exists()
            assert ctrl_socket.exists()
            status = ctrl_request(ctrl_socket, {"t": "status"})
            assert status["process"] is True
            assert status["matrix_socket"]["listening"] is True
            assert status["ctrl_socket"]["listening"] is True
        finally:
            proc.terminate()
            stdout, stderr = proc.communicate(timeout=3.0)
        assert stdout == ""
        assert proc.returncode in (0, -15)
        assert matrix_socket.exists()
        assert ctrl_socket.exists()

        result = subprocess.run(
            [str(BIN), "--mark-stopped"],
            check=True,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=2.0,
        )
        assert json.loads(result.stdout) == {"result": "ok", "marked_stopped": True}
        assert result.stderr == ""
        assert not matrix_socket.exists()
        assert not ctrl_socket.exists()
        status = json.loads(status_path.read_text(encoding="utf-8"))
        assert status["schema"] == "logicd-core.status.v1"
        assert status["process"] is False
        assert status["matrix_socket"]["listening"] is False
        assert status["ctrl_socket"]["listening"] is False


def test_shadow_replay_helper_writes_preview_log() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        matrix_socket = tmp / "matrix_events_shadow.sock"
        ctrl_socket = tmp / "logicd_core_ctrl.sock"
        status_path = tmp / "logicd-core-status.json"
        preview_log = tmp / "logicd-core-preview.ndjson"
        replay_path = tmp / "matrix.bin"
        replay_path.write_bytes(b"P00\0R00\0")
        env = core_env(tmp, flat_keymap([{"0,0": "KC_A"}]))
        env.update(
            {
                "LOGICD_CORE_MATRIX_SOCKET": str(matrix_socket),
                "LOGICD_CORE_CTRL_SOCKET": str(ctrl_socket),
                "LOGICD_CORE_STATUS_PATH": str(status_path),
                "LOGICD_CORE_PREVIEW_LOG_PATH": str(preview_log),
                "LOGICD_CORE_HID_REPORT_SOCKET": str(tmp / "missing-broker.sock"),
                "LOGICD_CORE_OUTPUT_ENABLED": "0",
            }
        )
        proc = subprocess.Popen(
            [str(BIN), "--serve", "--packets", "2"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            wait_for_socket(matrix_socket)
            helper = subprocess.run(
                [
                    sys.executable,
                    str(SHADOW_REPLAY),
                    str(replay_path),
                    "--socket",
                    str(matrix_socket),
                    "--status",
                    str(status_path),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = proc.communicate(timeout=3.0)
        finally:
            if proc.poll() is None:
                proc.terminate()
                stdout, stderr = proc.communicate(timeout=1.0)
        assert proc.returncode == 0
        assert stdout == ""
        assert stderr == ""
        summary = json.loads(helper.stdout)
        assert summary["packets"] == 2
        assert summary["status"]["counters"]["matrix_events"] == 2
        events = [
            json.loads(line)
            for line in preview_log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert [event["t"] for event in events] == ["shadow_report", "shadow_report"]
        assert [event["report"] for event in events] == [
            "0000040000000000",
            "0000000000000000",
        ]
        assert events[0]["event"] == {"kind": "P", "row": 0, "col": 0}
        assert events[1]["event"] == {"kind": "R", "row": 0, "col": 0}


def test_parity_compare_matches_core_preview_to_broker_capture() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        core_preview = tmp / "core-preview.ndjson"
        broker_frames = tmp / "broker-frames.ndjson"
        core_preview.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "t": "shadow_report",
                            "seq": 1,
                            "report": "0000040000000000",
                            "frame": encode_hid_report_request(
                                KIND_KEYBOARD,
                                bytes.fromhex("0000040000000000"),
                            ).hex(),
                        }
                    ),
                    json.dumps(
                        {
                            "t": "shadow_report",
                            "seq": 2,
                            "report": "0000000000000000",
                            "frame": encode_hid_report_request(KIND_KEYBOARD, bytes(8)).hex(),
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        broker_frames.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "t": "broker_frame",
                            "seq": 1,
                            "kind": KIND_KEYBOARD,
                            "payload": "0000040000000000",
                        }
                    ),
                    json.dumps(
                        {
                            "t": "broker_frame",
                            "seq": 2,
                            "kind": KIND_KEYBOARD,
                            "payload": "0000000000000000",
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable,
                str(PARITY_COMPARE),
                "--core-preview",
                str(core_preview),
                "--broker-frames",
                str(broker_frames),
            ],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        summary = json.loads(result.stdout)
        assert summary["result"] == "ok"
        assert summary["core_reports"] == 2
        assert summary["broker_reports"] == 2


def test_parity_compare_includes_us_sub_keyboard_kind() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        core_preview = tmp / "core-preview.ndjson"
        broker_frames = tmp / "broker-frames.ndjson"
        core_preview.write_text(
            json.dumps(
                {
                    "t": "shadow_report",
                    "seq": 1,
                    "kind": KIND_US_SUB_KEYBOARD,
                    "report": "0000040000000000",
                    "frame": encode_hid_report_request(
                        KIND_US_SUB_KEYBOARD,
                        bytes.fromhex("0000040000000000"),
                    ).hex(),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        broker_frames.write_text(
            json.dumps(
                {
                    "t": "broker_frame",
                    "seq": 1,
                    "kind": KIND_US_SUB_KEYBOARD,
                    "payload": "0000040000000000",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable,
                str(PARITY_COMPARE),
                "--core-preview",
                str(core_preview),
                "--broker-frames",
                str(broker_frames),
            ],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert json.loads(result.stdout)["result"] == "ok"


def test_broker_capture_records_datagrams_as_ndjson() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        socket_path = tmp / "usbd_hid_reports.sock"
        output_path = tmp / "broker-frames.ndjson"
        proc = subprocess.Popen(
            [
                sys.executable,
                str(BROKER_CAPTURE),
                "--socket",
                str(socket_path),
                "--count",
                "2",
                "--output",
                str(output_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            wait_for_path(socket_path)
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sender:
                sender.sendto(
                    encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000040000000000")),
                    str(socket_path),
                )
                sender.sendto(
                    encode_hid_report_request(KIND_KEYBOARD, bytes(8)),
                    str(socket_path),
                )
            stdout, stderr = proc.communicate(timeout=3.0)
        finally:
            if proc.poll() is None:
                proc.terminate()
                stdout, stderr = proc.communicate(timeout=1.0)
        assert proc.returncode == 0
        assert stderr == ""
        assert json.loads(stdout)["frames"] == 2
        frames = [
            json.loads(line)
            for line in output_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert [frame["payload"] for frame in frames] == [
            "0000040000000000",
            "0000000000000000",
        ]


def test_python_matrix_replay_matches_core_for_default_keymap() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        replay_path = tmp / "matrix.bin"
        core_preview = tmp / "core-preview.ndjson"
        python_frames = tmp / "python-frames.ndjson"
        replay_path.write_bytes(b"P70\nR70\n")
        events = run_core_replay(
            tmp,
            json.loads((ROOT / "config/default/keymap.json").read_text(encoding="utf-8")),
            replay_path.read_bytes(),
        )
        core_preview.write_text(
            "".join(
                json.dumps({"t": "shadow_report", "report": event["report"]}) + "\n"
                for event in events
            ),
            encoding="utf-8",
        )
        subprocess.run(
            [
                sys.executable,
                str(PYTHON_REPLAY),
                str(replay_path),
                "--output",
                str(python_frames),
            ],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        result = subprocess.run(
            [
                sys.executable,
                str(PARITY_COMPARE),
                "--core-preview",
                str(core_preview),
                "--broker-frames",
                str(python_frames),
            ],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        summary = json.loads(result.stdout)
        assert summary["result"] == "ok"
        assert summary["core_reports"] == 2
        assert summary["broker_reports"] == 2


def test_keymap_parity_suite_matches_m0_supported_sequences() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "parity-suite.json"
        result = subprocess.run(
            [
                sys.executable,
                str(PARITY_SUITE),
                "--max-basic",
                "80",
                "--output",
                str(output_path),
            ],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        summary = json.loads(result.stdout)
        assert summary["result"] == "ok"
        assert summary["sequences"] >= 60
        assert summary["matched"] == summary["sequences"]
        assert summary["unsupported_actions"] > 0
        written = json.loads(output_path.read_text(encoding="utf-8"))
        assert written["result"] == "ok"


def test_idle_poll_interval_is_configurable_and_short_by_default() -> None:
    source = (TOOL_DIR / "src" / "main.rs").read_text(encoding="utf-8")
    assert "LOGICD_CORE_IDLE_POLL_MS" in source
    assert '"idle_poll_ms": config.idle_poll_interval.as_millis()' in source
    assert "Duration::from_millis(5)" not in source


def main() -> None:
    build_tool()
    test_basic_press_release_matches_python_hid_state()
    test_modifier_chord_matches_python_hid_state()
    test_momentary_layer_actions_are_native()
    test_toggle_to_default_and_oneshot_layer_actions_are_native()
    test_broker_frame_matches_python_encoder()
    test_split_keyboard_routes_us_default_keys_to_sub_keyboard()
    test_held_key_keeps_hid_slot_when_lead_key_releases()
    test_split_keyboard_routes_jis_special_keys_to_main_keyboard()
    test_split_keyboard_routes_modifier_only_to_both_keyboards()
    test_split_keyboard_routes_henkan_aliases_to_main_keyboard()
    test_qmk_layer_tap_actions_delegate_to_companion()
    test_output_control_actions_delegate_to_companion()
    test_delegate_context_routes_following_key_to_companion()
    test_split_keyboard_routes_zkhk_to_main_and_grave_to_sub_keyboard()
    test_shadow_serve_updates_status_without_broker_output()
    test_ctrl_status_release_all_and_set_output()
    test_ctrl_status_burst_survives_backpressure()
    test_ctrl_matrix_delegate_all_routes_keys_to_companion()
    test_ctrl_key_event_merges_with_matrix_held_key()
    test_ctrl_key_event_release_all_clears_injected_state()
    test_ctrl_key_event_duplicate_edges_are_idempotent()
    test_ctrl_key_event_release_falls_back_to_unique_matching_action()
    test_ctrl_release_all_cli_matches_exec_stop_path()
    test_mark_stopped_cli_clears_stale_service_state()
    test_shadow_replay_helper_writes_preview_log()
    test_parity_compare_matches_core_preview_to_broker_capture()
    test_parity_compare_includes_us_sub_keyboard_kind()
    test_broker_capture_records_datagrams_as_ndjson()
    test_python_matrix_replay_matches_core_for_default_keymap()
    test_keymap_parity_suite_matches_m0_supported_sequences()
    test_idle_poll_interval_is_configurable_and_short_by_default()
    print("ok: hidloom-logicd-core fixture parity")


if __name__ == "__main__":
    main()
