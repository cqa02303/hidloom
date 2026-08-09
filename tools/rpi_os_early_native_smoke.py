#!/usr/bin/env python3
"""Run the E3 ARM64 daemon chain under qemu-aarch64 without USB hardware.

GPIO scanning is deliberately disabled in a temporary matrixd configuration.
The smoke still starts the production order (hidd, outputd, logicd-core,
matrixd), proves that matrixd connects to the core, exercises modifier plus
two-key overlap through the matrix socket, checks JIS-main / US-sub routing,
and requires every pressed and split-route state to finish released.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
from typing import Any, Callable

import rpi_os_early_initramfs as early


STARTUP_MAIN_RELEASE = bytes.fromhex("010000000000000000")
STARTUP_US_SUB_RELEASE = bytes(8)


def wait_for_json(
    path: Path,
    predicate: Callable[[dict[str, Any]], bool],
    label: str,
    *,
    timeout: float = 6.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: object = "missing"
    while time.monotonic() < deadline:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            last = value
        except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            last = str(exc)
            time.sleep(0.01)
            continue
        if isinstance(value, dict) and predicate(value):
            return value
        time.sleep(0.01)
    raise RuntimeError(f"{label} did not become ready ({path}): {last}")


def ctrl_request(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(3.0)
        client.connect(str(path))
        client.sendall((json.dumps(payload, separators=(",", ":")) + "\n").encode())
        response = bytearray()
        while not response.endswith(b"\n"):
            chunk = client.recv(4096)
            if not chunk:
                break
            response += chunk
    value = json.loads(response)
    if not isinstance(value, dict):
        raise RuntimeError(f"control response is not an object: {value!r}")
    return value


def send_matrix_packets(path: Path, packets: list[bytes]) -> None:
    if any(len(packet) != 4 or packet[3:] != b"\n" for packet in packets):
        raise ValueError("matrix packets must use the exact four-byte P00\\n/R00\\n form")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(3.0)
        client.connect(str(path))
        client.sendall(b"".join(packets))


def wait_for_ctrl_status(
    path: Path,
    predicate: Callable[[dict[str, Any]], bool],
    label: str,
    *,
    timeout: float = 6.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: object = "no response"
    while time.monotonic() < deadline:
        try:
            last = ctrl_request(path, {"t": "status"})
        except (ConnectionError, FileNotFoundError, TimeoutError, json.JSONDecodeError) as exc:
            last = str(exc)
            time.sleep(0.01)
            continue
        if predicate(last):
            return last
        time.sleep(0.01)
    raise RuntimeError(f"{label} did not converge through {path}: {last}")


def terminate(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2.0)


def process_command(qemu: str, binary: Path, *arguments: str) -> list[str]:
    return [qemu, str(binary), *arguments]


def start(
    command: list[str], environment: dict[str, str]
) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        command,
        cwd="/tmp",
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def require_inputs(args: argparse.Namespace) -> dict[str, Path]:
    paths = {
        name: getattr(args, name).resolve()
        for name in (
            "hidd",
            "outputd",
            "logicd_core",
            "matrixd",
            "keymap",
            "keycodes",
            "logicd_config",
            "matrixd_config",
        )
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise SystemExit("missing E3 smoke input(s): " + ", ".join(missing))
    for name in ("hidd", "outputd", "logicd_core", "matrixd"):
        early.verify_arm64_static_elf(paths[name].read_bytes(), name.replace("_", "-"))
    for name in ("keymap", "keycodes", "logicd_config", "matrixd_config"):
        try:
            value = json.loads(paths[name].read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SystemExit(f"invalid JSON input {paths[name]}: {exc}") from exc
        if not isinstance(value, dict):
            raise SystemExit(f"JSON input must be an object: {paths[name]}")
    return paths


def smoke(qemu: str, paths: dict[str, Path], temporary: Path) -> dict[str, Any]:
    hidd_socket = temporary / "hidd-reports.sock"
    output_socket = temporary / "output-reports.sock"
    output_ctrl = temporary / "output-ctrl.sock"
    matrix_socket = temporary / "matrix-events.sock"
    core_ctrl = temporary / "logicd-core-ctrl.sock"
    hidg0 = temporary / "hidg0"
    hidg2 = temporary / "hidg2"
    hidd_status = temporary / "hidd-status.json"
    output_status = temporary / "outputd-status.json"
    core_status = temporary / "logicd-core-status.json"
    matrix_status = temporary / "matrixd-status.json"
    hidd_frames = temporary / "hidd-frames.ndjson"
    core_preview = temporary / "logicd-core-preview.ndjson"
    matrix_config_path = temporary / "matrixd-host-smoke.json"

    hidg0.write_bytes(b"")
    hidg2.write_bytes(b"")
    matrix_config = json.loads(paths["matrixd_config"].read_text(encoding="utf-8"))
    matrix = matrix_config.setdefault("matrix", {})
    ipc = matrix_config.setdefault("ipc", {})
    if not isinstance(matrix, dict) or not isinstance(ipc, dict):
        raise RuntimeError("matrixd config matrix/ipc values must be objects")
    matrix["gpio_enabled"] = False
    ipc["socket_path"] = str(matrix_socket)
    ipc["tap_socket_path"] = "none"
    matrix_config_path.write_text(
        json.dumps(matrix_config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    common = os.environ.copy()
    processes: list[subprocess.Popen[bytes]] = []
    hidd = outputd = core = matrixd = None
    try:
        hidd_env = {
            **common,
            "USBD_HID_REPORT_SOCKET": str(hidd_socket),
            "USBD_HID_REPORT_PATH": str(hidg0),
            "USBD_US_SUB_HID_REPORT_PATH": str(hidg2),
            "HIDD_STATUS_PATH": str(hidd_status),
            "HIDD_RAW_HID_BRIDGE_ENABLED": "0",
            "HIDD_FRAME_LOG_PATH": str(hidd_frames),
            "USBD_KEYBOARD_STARTUP_RELEASE": "1",
            "USBD_KEYBOARD_REPORT_DEDUP": "0",
            "USBD_HID_WRITE_RETRY_TIMEOUT_SEC": "0.02",
            "USBD_HID_WRITE_RETRY_INTERVAL_SEC": "0.001",
            "USBD_KEYBOARD_RELEASE_MERGE_WINDOW_SEC": "0.001",
        }
        hidd = start(process_command(qemu, paths["hidd"]), hidd_env)
        processes.append(hidd)
        wait_for_json(
            hidd_status,
            lambda value: value.get("counters", {}).get("startup_release_reports") == 2,
            "hidd startup release",
        )
        if hidg0.read_bytes() != STARTUP_MAIN_RELEASE:
            raise RuntimeError("hidd main startup release is not Report-ID 0x01 + 8 zero bytes")
        if hidg2.read_bytes() != STARTUP_US_SUB_RELEASE:
            raise RuntimeError("hidd US-sub startup release is not 8 zero bytes")

        output_env = {
            **common,
            "OUTPUTD_REPORT_SOCKET": str(output_socket),
            "OUTPUTD_CTRL_SOCKET": str(output_ctrl),
            "OUTPUTD_USB_SOCKET": str(hidd_socket),
            "OUTPUTD_UIDD_SOCKET": str(temporary / "disabled-uidd.sock"),
            "OUTPUTD_BT_SOCKET": str(temporary / "disabled-btd.sock"),
            "OUTPUTD_STATUS_PATH": str(output_status),
            "OUTPUTD_TARGET": "usb",
        }
        outputd = start(process_command(qemu, paths["outputd"]), output_env)
        processes.append(outputd)
        wait_for_json(
            output_status,
            lambda value: value.get("target") == "usb",
            "outputd USB target",
        )

        core_env = {
            **common,
            "HIDLOOM_REPO_ROOT": str(temporary),
            "LOGICD_CORE_KEYMAP_PATH": str(paths["keymap"]),
            "LOGICD_CORE_DEFAULT_KEYMAP_PATH": str(paths["keymap"]),
            "LOGICD_CORE_KEYCODES_PATH": str(paths["keycodes"]),
            "LOGICD_CORE_DEFAULT_KEYCODES_PATH": str(paths["keycodes"]),
            "LOGICD_CORE_CONFIG_PATH": str(paths["logicd_config"]),
            "LOGICD_CORE_DEFAULT_CONFIG_PATH": str(paths["logicd_config"]),
            "LOGICD_CORE_MATRIX_SOCKET": str(matrix_socket),
            "LOGICD_CORE_CTRL_SOCKET": str(core_ctrl),
            "LOGICD_CORE_DELEGATE_SOCKET": "none",
            "LOGICD_CORE_MATRIX_TAP_SOCKET": "none",
            "LOGICD_CORE_HID_REPORT_SOCKET": str(output_socket),
            "LOGICD_CORE_STATUS_PATH": str(core_status),
            "LOGICD_CORE_PREVIEW_LOG_PATH": str(core_preview),
            "LOGICD_CORE_OUTPUT_ENABLED": "1",
        }
        core = start(process_command(qemu, paths["logicd_core"], "--serve"), core_env)
        processes.append(core)
        wait_for_json(
            core_status,
            lambda value: value.get("output_enabled") is True
            and value.get("matrix_socket", {}).get("listening") is True,
            "logicd-core socket",
        )

        matrix_env = {**common, "MATRIXD_STATUS_PATH": str(matrix_status)}
        matrixd = start(
            process_command(qemu, paths["matrixd"], str(matrix_config_path)), matrix_env
        )
        processes.append(matrixd)
        wait_for_json(
            matrix_status,
            lambda value: value.get("process") is True
            and value.get("logic_socket", {}).get("connected") is True,
            "matrixd-to-core connection",
        )

        # Exercise the same four-byte matrix protocol used by matrixd.  On the
        # keyboard-ver1 profile these are LSFT, A and F, deliberately released
        # in an overlapping order before the modifier is released last.
        matrix_packets = [b"P30\n", b"P21\n", b"P25\n", b"R21\n", b"R25\n", b"R30\n"]
        send_matrix_packets(matrix_socket, matrix_packets)
        matrix_core = wait_for_ctrl_status(
            core_ctrl,
            lambda value: value.get("counters", {}).get("matrix_events", 0) >= 6
            and value.get("state", {}).get("pressed_matrix") == 0
            and value.get("state", {}).get("pressed_keys") == 0
            and value.get("state", {}).get("modifier") == 0
            and not any(value.get("routing", {}).get("state", {}).values()),
            "matrix modifier/two-key overlap release",
        )
        matrix_events = [
            json.loads(line)
            for line in core_preview.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        preview_packets = [
            f"{event['event']['kind']}{event['event']['row']}{event['event']['col']}\n".encode()
            for event in matrix_events
        ]
        actual_packets = [
            packet
            for index, packet in enumerate(preview_packets)
            if index == 0 or packet != preview_packets[index - 1]
        ]
        if actual_packets != matrix_packets:
            raise RuntimeError(
                f"logicd-core matrix packet order differs: {actual_packets!r}"
            )

        # The E3 profile is JIS-main / US-sub split.  KC_RO must use the main
        # keyboard endpoint while an ordinary KC_A must use the US-sub endpoint.
        control_edges = [
            ("jis:KC_RO", "KC_RO", True),
            ("jis:KC_RO", "KC_RO", False),
            ("us:KC_A", "KC_A", True),
            ("us:KC_A", "KC_A", False),
        ]
        control_responses = [
            ctrl_request(
                core_ctrl,
                {
                    "t": "key_event",
                    "id": identity,
                    "action": action,
                    "is_press": is_press,
                },
            )
            for identity, action, is_press in control_edges
        ]
        if any(
            response.get("result") != "ok" or response.get("emitted", 0) < 1
            for response in control_responses
        ):
            raise RuntimeError(f"logicd-core split-route controls failed: {control_responses}")

        final_core = wait_for_ctrl_status(
            core_ctrl,
            lambda value: value.get("state", {}).get("pressed_matrix") == 0
            and value.get("state", {}).get("pressed_keys") == 0
            and value.get("state", {}).get("modifier") == 0
            and value.get("state", {}).get("injected_keys") == 0
            and not any(value.get("routing", {}).get("state", {}).values()),
            "final core release",
        )
        expected_frames = final_core.get("counters", {}).get("broker_frames_sent", 0)
        if expected_frames < 10:
            raise RuntimeError(f"full chain emitted too few frames: {final_core}")
        final_output = wait_for_json(
            output_status,
            lambda value: value.get("counters", {}).get("frames_received")
            == expected_frames,
            "outputd frame drain",
        )
        final_hidd = wait_for_json(
            hidd_status,
            lambda value: value.get("counters", {}).get("frames_received")
            == expected_frames,
            "hidd frame drain",
        )
        final_matrix = json.loads(matrix_status.read_text(encoding="utf-8"))
        if final_core.get("state", {}).get("pressed_matrix") != 0:
            raise RuntimeError(f"logicd-core ended with pressed matrix keys: {final_core}")
        if final_core.get("state", {}).get("pressed_keys") != 0:
            raise RuntimeError(f"logicd-core ended with pressed keys: {final_core}")
        if final_core.get("state", {}).get("modifier") != 0:
            raise RuntimeError(f"logicd-core ended with a pressed modifier: {final_core}")
        if final_core.get("state", {}).get("injected_keys") != 0:
            raise RuntimeError(f"logicd-core ended with injected keys: {final_core}")
        if any(final_core.get("routing", {}).get("state", {}).values()):
            raise RuntimeError(f"logicd-core ended with an active split route: {final_core}")
        if final_output.get("counters", {}).get("frames_received") != expected_frames:
            raise RuntimeError(f"outputd frame count differs: {final_output}")
        if final_output.get("counters", {}).get("forward_errors") != 0:
            raise RuntimeError(f"outputd reported a forwarding error: {final_output}")
        if final_hidd.get("counters", {}).get("frames_received") != expected_frames:
            raise RuntimeError(f"hidd frame count differs: {final_hidd}")
        if final_hidd.get("counters", {}).get("write_errors") != 0:
            raise RuntimeError(f"hidd reported a write error: {final_hidd}")
        if not hidg0.read_bytes().endswith(STARTUP_MAIN_RELEASE):
            raise RuntimeError("main keyboard endpoint did not end in a release report")
        frame_events = [
            json.loads(line)
            for line in hidd_frames.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        received = [
            event for event in frame_events if event.get("t") == "hidd_frame_received"
        ]
        if len(received) != expected_frames:
            raise RuntimeError(f"hidd frame evidence count differs: {len(received)}")
        if not any(
            event.get("kind") == 1
            and event.get("endpoint") == "hidg0"
            and event.get("payload") == "0000870000000000"
            for event in received
        ):
            raise RuntimeError("KC_RO did not reach the JIS main/hidg0 endpoint")
        if not any(
            event.get("kind") == 4
            and event.get("endpoint") == "hidg2"
            and event.get("payload") == "0000040000000000"
            for event in received
        ):
            raise RuntimeError("KC_A did not reach the US-sub/hidg2 endpoint")
        if not any(
            event.get("kind") == 4
            and event.get("payload", "").startswith("02")
            and "04" in event.get("payload", "")[4:]
            and "09" in event.get("payload", "")[4:]
            for event in received
        ):
            raise RuntimeError("matrix LSFT+A+F overlap did not reach the HID chain")
        if not final_matrix.get("logic_socket", {}).get("connected"):
            raise RuntimeError(f"matrixd lost its logicd-core connection: {final_matrix}")
        return {
            "status": "pass",
            "schema": "hidloom.rpi-os-early-native-smoke.e3.v1",
            "start_order": ["hidd", "outputd", "logicd_core", "matrixd"],
            "gpio_mode": "disabled-host-fixture",
            "startup_release": {"main_size": 9, "us_sub_size": 8},
            "final": {
                "pressed_keys": final_core["state"]["pressed_keys"],
                "pressed_matrix": final_core["state"]["pressed_matrix"],
                "modifier": final_core["state"]["modifier"],
                "core_broker_frames": final_core["counters"]["broker_frames_sent"],
                "output_frames": final_output["counters"]["frames_received"],
                "hidd_frames": final_hidd["counters"]["frames_received"],
                "matrix_connected": final_matrix["logic_socket"]["connected"],
                "matrix_events": matrix_core["counters"]["matrix_events"],
                "split_routes_clear": not any(
                    final_core["routing"]["state"].values()
                ),
            },
        }
    finally:
        for process in reversed(processes):
            terminate(process)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hidd", type=Path, required=True)
    parser.add_argument("--outputd", type=Path, required=True)
    parser.add_argument("--logicd-core", dest="logicd_core", type=Path, required=True)
    parser.add_argument("--matrixd", type=Path, required=True)
    parser.add_argument("--keymap", type=Path, required=True)
    parser.add_argument("--keycodes", type=Path, required=True)
    parser.add_argument("--logicd-config", dest="logicd_config", type=Path, required=True)
    parser.add_argument("--matrixd-config", dest="matrixd_config", type=Path, required=True)
    parser.add_argument("--qemu", default="qemu-aarch64")
    args = parser.parse_args()
    qemu = shutil.which(args.qemu)
    if qemu is None:
        raise SystemExit(f"ARM64 emulator not found: {args.qemu}")
    paths = require_inputs(args)
    with tempfile.TemporaryDirectory(prefix="hidloom-e3-qemu-smoke-") as directory:
        result = smoke(qemu, paths, Path(directory))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
