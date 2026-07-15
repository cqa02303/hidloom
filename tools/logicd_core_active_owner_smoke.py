#!/usr/bin/env python3
"""Temporary active-owner smoke for hidloom-logicd-core on a real device."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import logicd_core_owner_recovery as recovery  # noqa: E402

CORE_UNIT = recovery.CORE_UNIT
HIDD_UNIT = recovery.HIDD_UNIT
LOGICD_UNIT = recovery.LOGICD_UNIT
MATRIXD_UNIT = recovery.MATRIXD_UNIT
RUN_SYSTEMD = Path("/run/systemd/system")
CORE_DROPIN = RUN_SYSTEMD / f"{CORE_UNIT}.d/active-owner-smoke.conf"
MATRIXD_DROPIN = RUN_SYSTEMD / f"{MATRIXD_UNIT}.d/logicd-core-owner-smoke.conf"
LOGICD_RUNTIME_MASK = RUN_SYSTEMD / LOGICD_UNIT
CORE_STATUS = Path("/run/hidloom/logicd-core-status.json")
HIDD_STATUS = Path("/run/hidloom/hidd-status.json")
MATRIX_SOCKET = Path("/tmp/matrix_events.sock")

PREFERRED_ACTIONS = (
    "KC_LSFT",
    "KC_RSFT",
    "KC_LCTL",
    "KC_RCTL",
    "KC_LALT",
    "KC_RALT",
    "KC_A",
)


def sudo_prefix(enabled: bool) -> list[str]:
    return ["sudo"] if enabled and os.geteuid() != 0 else []


def run(command: list[str], *, timeout: float, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"command failed rc={proc.returncode}: {' '.join(command)}\n{proc.stderr.strip()}")
    return proc


def write_runtime_dropins(*, sudo: bool, timeout: float) -> None:
    prefix = sudo_prefix(sudo)
    core = """[Unit]
After=
After=hidloom-hidd.service
Wants=
Wants=hidloom-hidd.service
Before=

[Service]
Environment=LOGICD_CORE_MATRIX_SOCKET=/tmp/matrix_events.sock
Environment=LOGICD_CORE_MATRIX_SOCKET_MODE=0o666
Environment=LOGICD_CORE_CTRL_SOCKET=/tmp/logicd_core_ctrl.sock
Environment=LOGICD_CORE_CTRL_SOCKET_MODE=0o666
Environment=LOGICD_CORE_HID_REPORT_SOCKET=/tmp/usbd_hid_reports.sock
Environment=LOGICD_CORE_OUTPUT_ENABLED=1
Environment=LOGICD_CORE_PREVIEW_LOG_PATH=
"""
    matrixd = """[Unit]
Requires=
After=
After=hidloom-logicd-core.service
"""
    for path, content in ((CORE_DROPIN, core), (MATRIXD_DROPIN, matrixd)):
        run([*prefix, "mkdir", "-p", str(path.parent)], timeout=timeout)
        proc = subprocess.run(
            [*prefix, "tee", str(path)],
            input=content,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"failed to write {path}: {proc.stderr.strip()}")
    run([*prefix, "systemctl", "daemon-reload"], timeout=timeout)


def remove_runtime_dropins(*, sudo: bool, timeout: float) -> None:
    prefix = sudo_prefix(sudo)
    run([*prefix, "rm", "-f", str(CORE_DROPIN), str(MATRIXD_DROPIN)], timeout=timeout, check=False)
    run([*prefix, "systemctl", "daemon-reload"], timeout=timeout, check=False)


def mask_logicd_runtime(*, sudo: bool, timeout: float) -> None:
    prefix = sudo_prefix(sudo)
    run([*prefix, "systemctl", "mask", "--runtime", LOGICD_UNIT], timeout=timeout)


def unmask_logicd(*, sudo: bool, timeout: float) -> None:
    prefix = sudo_prefix(sudo)
    run([*prefix, "systemctl", "unmask", LOGICD_UNIT], timeout=timeout, check=False)
    run([*prefix, "rm", "-f", str(LOGICD_RUNTIME_MASK)], timeout=timeout, check=False)
    run([*prefix, "systemctl", "daemon-reload"], timeout=timeout, check=False)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_json_with_fallback(runtime: Path, default: Path, *, prefer_runtime: bool = True) -> dict[str, Any]:
    if prefer_runtime:
        try:
            return load_json(runtime)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
    return load_json(default)


def flatten_keymap(keymap: dict[str, Any]) -> list[dict[str, str]]:
    layers = keymap.get("layers")
    if not isinstance(layers, list):
        return [{}]
    if "_layout_def" not in keymap:
        return [
            {str(k): str(v) for k, v in layer.items() if not str(k).startswith("_")}
            for layer in layers
            if isinstance(layer, dict)
        ] or [{}]
    layout_def = keymap.get("_layout_def", {})
    groups: dict[str, list[tuple[int, int]]] = {}
    if isinstance(layout_def, dict):
        for group, entries in layout_def.items():
            if str(group).startswith("_") or not isinstance(entries, list):
                continue
            coords: list[tuple[int, int]] = []
            for entry in entries:
                if isinstance(entry, list) and len(entry) >= 2:
                    coords.append((int(entry[0]), int(entry[1])))
            groups[str(group)] = coords
    result: list[dict[str, str]] = []
    for layer in layers:
        flat: dict[str, str] = {}
        if not isinstance(layer, dict):
            continue
        for group, coords in groups.items():
            actions = layer.get(group, [])
            if not isinstance(actions, list):
                continue
            for (row, col), action in zip(coords, actions):
                if action:
                    flat[f"{row},{col}"] = str(action)
        result.append(flat)
    return result or [{}]


def load_keycodes(repo_root: Path, *, prefer_runtime: bool = True) -> dict[str, int]:
    raw = load_json_with_fallback(
        Path("/mnt/p3/keycodes.json"),
        repo_root / "config/default/keycodes.json",
        prefer_runtime=prefer_runtime,
    )
    result: dict[str, int] = {}
    for name, value in raw.items():
        if str(name).startswith("_"):
            continue
        if isinstance(value, int):
            result[str(name)] = value
        elif isinstance(value, dict) and isinstance(value.get("hid"), int) and value.get("page") != "consumer":
            result[str(name)] = int(value["hid"])
    return result


def choose_smoke_key(repo_root: Path, *, prefer_runtime: bool = True) -> tuple[int, int, str]:
    keymap = load_json_with_fallback(
        Path("/mnt/p3/keymap.json"),
        repo_root / "config/default/keymap.json",
        prefer_runtime=prefer_runtime,
    )
    keycodes = load_keycodes(repo_root, prefer_runtime=prefer_runtime)
    base = flatten_keymap(keymap)[0]
    by_action = {action: coord for coord, action in base.items()}
    for action in PREFERRED_ACTIONS:
        coord = by_action.get(action)
        code = keycodes.get(action)
        if coord and code is not None and 0 < code < 0xE8:
            row, col = (int(part) for part in coord.split(",", 1))
            return row, col, action
    for coord, action in sorted(base.items()):
        code = keycodes.get(action)
        if code is not None and 0 < code < 0xE8:
            row, col = (int(part) for part in coord.split(",", 1))
            return row, col, action
    raise RuntimeError("no basic smoke key found in layer 0")


def packet(kind: str, row: int, col: int) -> bytes:
    return bytes([ord(kind), ord(f"{row:X}"), ord(f"{col:X}"), 0x00])


def send_matrix_tap(row: int, col: int, *, hold_sec: float) -> None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(3.0)
        sock.connect(str(MATRIX_SOCKET))
        sock.sendall(packet("P", row, col))
        time.sleep(hold_sec)
        sock.sendall(packet("R", row, col))
        time.sleep(max(hold_sec, 0.05))


def wait_status(path: Path, predicate: Any, *, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            last = load_json(path)
            if predicate(last):
                return last
        except Exception:
            pass
        time.sleep(0.05)
    raise RuntimeError(f"status did not reach expected state: {path}: {last}")


def wait_unit_inactive(unit: str, *, sudo: bool, timeout: float) -> None:
    prefix = sudo_prefix(sudo)
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        proc = run([*prefix, "systemctl", "is-active", unit], timeout=timeout, check=False)
        last = proc.stdout.strip() or proc.stderr.strip()
        if proc.returncode != 0:
            return
        time.sleep(0.1)
    raise RuntimeError(f"{unit} did not become inactive: {last}")


def counters(payload: dict[str, Any]) -> dict[str, int]:
    raw = payload.get("counters", {})
    return {str(k): int(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def run_smoke(*, sudo: bool, timeout: float, hold_sec: float, restore: bool, repo_root: Path) -> dict[str, Any]:
    prefix = sudo_prefix(sudo)
    summary: dict[str, Any] = {"schema": "logicd-core.active-owner-smoke.v1", "steps": []}
    try:
        write_runtime_dropins(sudo=sudo, timeout=timeout)
        summary["steps"].append("runtime drop-ins installed")
        run([*prefix, "systemctl", "stop", MATRIXD_UNIT, LOGICD_UNIT], timeout=timeout, check=False)
        mask_logicd_runtime(sudo=sudo, timeout=timeout)
        run([*prefix, "systemctl", "stop", LOGICD_UNIT], timeout=timeout, check=False)
        wait_unit_inactive(LOGICD_UNIT, sudo=sudo, timeout=timeout)
        run([*prefix, "systemctl", "reset-failed", CORE_UNIT], timeout=timeout, check=False)
        run([*prefix, "systemctl", "start", HIDD_UNIT], timeout=timeout)
        run([*prefix, "systemctl", "start", CORE_UNIT], timeout=timeout)
        summary["steps"].append("core owner service started")

        core_status = wait_status(
            CORE_STATUS,
            lambda p: p.get("process") is True
            and p.get("output_enabled") is True
            and p.get("matrix_socket", {}).get("path") == str(MATRIX_SOCKET)
            and MATRIX_SOCKET.exists()
            and os.access(MATRIX_SOCKET, os.W_OK),
            timeout=timeout,
        )
        hidd_before = load_json(HIDD_STATUS)
        row, col, action = choose_smoke_key(repo_root)
        send_matrix_tap(row, col, hold_sec=hold_sec)
        core_after = wait_status(
            CORE_STATUS,
            lambda p: counters(p).get("matrix_events", 0) >= counters(core_status).get("matrix_events", 0) + 2,
            timeout=timeout,
        )
        hidd_after = wait_status(
            HIDD_STATUS,
            lambda p: counters(p).get("frames_received", 0) >= counters(hidd_before).get("frames_received", 0) + 2,
            timeout=timeout,
        )
        summary.update(
            {
                "ok": True,
                "smoke_key": {"row": row, "col": col, "action": action},
                "core_before": counters(core_status),
                "core_after": counters(core_after),
                "hidd_before": counters(hidd_before),
                "hidd_after": counters(hidd_after),
                "core_status": {
                    "process": core_after.get("process"),
                    "output_enabled": core_after.get("output_enabled"),
                    "matrix_socket": core_after.get("matrix_socket"),
                    "broker_socket": core_after.get("broker_socket"),
                },
            }
        )
        return summary
    finally:
        if restore:
            recovery_error: Exception | None = None
            remove_error: Exception | None = None
            try:
                remove_runtime_dropins(sudo=sudo, timeout=timeout)
            except Exception as exc:
                remove_error = exc
            unmask_logicd(sudo=sudo, timeout=timeout)
            try:
                recovery.run_recovery(apply=True, sudo=sudo, timeout=timeout, repo_root=repo_root)
            except Exception as exc:
                recovery_error = exc
            if remove_error is not None:
                raise remove_error
            if recovery_error is not None:
                raise recovery_error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="run the active-owner A/B smoke")
    parser.add_argument("--sudo", action="store_true", help="prefix systemctl/drop-in commands with sudo")
    parser.add_argument("--json", action="store_true", help="print JSON summary")
    parser.add_argument("--timeout-sec", type=float, default=12.0)
    parser.add_argument("--hold-sec", type=float, default=0.03)
    parser.add_argument("--no-restore", action="store_true", help="leave temporary active-owner state running")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.apply:
        payload = {
            "schema": "logicd-core.active-owner-smoke.v1",
            "mode": "dry-run",
            "dropins": [str(CORE_DROPIN), str(MATRIXD_DROPIN)],
            "services": [HIDD_UNIT, CORE_UNIT],
            "restore_default": not args.no_restore,
        }
    else:
        payload = run_smoke(
            sudo=args.sudo,
            timeout=args.timeout_sec,
            hold_sec=args.hold_sec,
            restore=not args.no_restore,
            repo_root=ROOT,
        )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    if args.apply and not payload.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
