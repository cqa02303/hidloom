#!/usr/bin/env python3
"""Open a temporary BLE HID pairing window for real-device host checks."""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path


DEFAULT_SOCKET = "/tmp/test_btd_bluez.sock"
DEFAULT_LOG = "/tmp/btd-bluez-pairing-window.log"
DEFAULT_PASSKEY_FILE = "/tmp/btd_pairing_passkey.txt"
A_PRESS = bytes.fromhex("0000040000000000")
A_RELEASE = bytes(8)
NOTIFY_STARTED_MARKER = "BlueZ GATT notify started"
ENTER_TAP = bytes([0x00, 0x00, 0x28, 0x00, 0x00, 0x00, 0x00, 0x00])
DIGIT_USAGE = {
    "1": 0x1E,
    "2": 0x1F,
    "3": 0x20,
    "4": 0x21,
    "5": 0x22,
    "6": 0x23,
    "7": 0x24,
    "8": 0x25,
    "9": 0x26,
    "0": 0x27,
}


def run_text(command: list[str], *, timeout: float = 5.0) -> str:
    try:
        proc = subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)
    except Exception as exc:
        return f"{command[0]} failed: {exc}"
    output = (proc.stdout + proc.stderr).strip()
    if output:
        return output
    if proc.returncode == 0:
        return ""
    return f"{command[0]} exited {proc.returncode} with no output"


def print_bluez_snapshot(label: str) -> None:
    print(f"\n== {label} ==")
    show = run_text(["bluetoothctl", "show"])
    for line in show.splitlines():
        if any(
            token in line
            for token in (
                "Controller ",
                "Name:",
                "Alias:",
                "Powered:",
                "Discoverable:",
                "Pairable:",
                "UUID: Human Interface Device",
                "ActiveInstances:",
            )
        ):
            print(line)
    connected = run_text(["bluetoothctl", "devices", "Connected"])
    paired = run_text(["bluetoothctl", "devices", "Paired"])
    print("Connected devices:")
    print(connected or "(none)")
    print("Paired devices:")
    print(paired or "(none)")
    print_device_infos(device_addresses(connected) | device_addresses(paired))


def device_addresses(devices_output: str) -> set[str]:
    addresses: set[str] = set()
    for line in devices_output.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "Device":
            addresses.add(parts[1])
    return addresses


def device_info(address: str) -> dict[str, str]:
    info = run_text(["bluetoothctl", "info", address], timeout=5.0)
    fields: dict[str, str] = {"Address": address}
    for line in info.splitlines():
        text = line.strip()
        if ":" not in text:
            continue
        key, value = text.split(":", 1)
        if key in {"Name", "Alias", "Paired", "Bonded", "Trusted", "Connected", "ServicesResolved"}:
            fields[key] = value.strip()
    return fields


def format_device_info(fields: dict[str, str]) -> str:
    ordered = ["Address", "Name", "Alias", "Paired", "Bonded", "Trusted", "Connected", "ServicesResolved"]
    return " ".join(f"{key}={fields[key]}" for key in ordered if key in fields)


def print_device_infos(addresses: set[str]) -> None:
    if not addresses:
        return
    print("Device details:")
    for address in sorted(addresses):
        print(format_device_info(device_info(address)))


def wait_for_socket(path: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if Path(path).exists():
            return True
        time.sleep(0.2)
    return False


def send_report(socket_path: str, payload: bytes) -> None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(2.0)
        sock.connect(socket_path)
        sock.sendall(payload)


def send_a_tap(socket_path: str) -> None:
    send_report(socket_path, A_PRESS)
    time.sleep(0.1)
    send_report(socket_path, A_RELEASE)


def digit_report(digit: str) -> bytes:
    if digit not in DIGIT_USAGE:
        raise ValueError(f"unsupported passkey digit: {digit!r}")
    return bytes([0x00, 0x00, DIGIT_USAGE[digit], 0x00, 0x00, 0x00, 0x00, 0x00])


def send_tap(socket_path: str, report: bytes) -> None:
    send_report(socket_path, report)
    time.sleep(0.08)
    send_report(socket_path, A_RELEASE)
    time.sleep(0.04)


def send_passkey(socket_path: str, passkey: str) -> None:
    if not passkey.isdigit():
        raise ValueError("passkey must contain only digits")
    for digit in passkey:
        send_tap(socket_path, digit_report(digit))
    send_tap(socket_path, ENTER_TAP)


def write_passkey_file(path: str, passkey: str) -> None:
    if not passkey.isdigit():
        raise ValueError("passkey must contain only digits")
    passkey_path = Path(path)
    passkey_path.parent.mkdir(parents=True, exist_ok=True)
    passkey_path.write_text(passkey)


def tail_log(path: str, lines: int = 80) -> str:
    log_path = Path(path)
    if not log_path.exists():
        return f"log file does not exist: {path}"
    text = log_path.read_text(errors="replace")
    return "\n".join(text.splitlines()[-lines:])


def log_contains(path: str, marker: str) -> bool:
    log_path = Path(path)
    if not log_path.exists():
        return False
    return marker in log_path.read_text(errors="replace")


def build_btd_env(socket_path: str, passkey_file: str = DEFAULT_PASSKEY_FILE) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "BTD_EVENTS_SOCK": socket_path,
            "BTD_BACKEND": "bluez",
            "BTD_BLUEZ_ENABLE": "1",
            "BTD_GATT_ADAPTER": "bluez-dbus",
            "BTD_GATT_SECURITY": os.environ.get("BTD_GATT_SECURITY", "none"),
            "BTD_ADVERTISING_ADAPTER": "bluez-dbus",
            "BTD_ADVERTISING_MODE": "pairing",
            "BTD_PAIRING_MODE": "1",
            "BTD_PAIRING_ADAPTER": "bluetoothctl",
            "BTD_PAIRING_AGENT": os.environ.get("BTD_PAIRING_AGENT", "KeyboardOnly"),
            "BTD_PAIRING_PASSKEY_FILE": passkey_file,
            "BTD_STATUS_INTERVAL": "5",
            "PYTHONUNBUFFERED": "1",
        }
    )
    return env


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Open a temporary BLE HID pairing window.")
    parser.add_argument(
        "--send-passkey",
        help="submit numeric pairing passkey to an already-running bluetoothctl agent, then exit",
    )
    parser.add_argument("--duration", type=float, default=120.0, help="seconds to keep the pairing window open")
    parser.add_argument("--socket", default=DEFAULT_SOCKET)
    parser.add_argument("--log", default=DEFAULT_LOG)
    parser.add_argument("--passkey-file", default=DEFAULT_PASSKEY_FILE)
    parser.add_argument("--repo", default=str(repo_root))
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="seconds between connected-device / notify checks",
    )
    parser.add_argument(
        "--pairing-agent",
        choices=("DisplayOnly", "DisplayYesNo", "KeyboardOnly", "KeyboardDisplay", "NoInputNoOutput"),
        default="KeyboardOnly",
        help="bluetoothctl agent capability to use during the pairing window",
    )
    parser.add_argument(
        "--gatt-security",
        choices=("none", "encrypt", "authenticated"),
        default="none",
        help="GATT characteristic security mode to request from BlueZ",
    )
    parser.add_argument("--send-test-report", action="store_true", help="send A press/release once after startup")
    parser.add_argument(
        "--type-passkey",
        help="type the numeric pairing passkey followed by Enter as keyboard HID reports",
    )
    parser.add_argument(
        "--send-on-connect",
        action="store_true",
        help="send one A press/release when bluetoothctl first reports a connected host",
    )
    parser.add_argument(
        "--send-on-notify",
        action="store_true",
        help="send one A press/release after the host starts HID Input Report notifications",
    )
    parser.add_argument(
        "--disconnect-on-exit",
        action="store_true",
        help="disconnect devices that newly connected during this pairing window",
    )
    args = parser.parse_args()

    socket_path = Path(args.socket)
    if args.send_passkey:
        write_passkey_file(args.passkey_file, args.send_passkey)
        print(f"Submitted pairing passkey via {args.passkey_file}: {'*' * len(args.send_passkey)}")
        if socket_path.exists():
            try:
                send_passkey(str(socket_path), args.send_passkey)
                print(f"Also typed pairing passkey to {socket_path}: {'*' * len(args.send_passkey)} + Enter")
            except OSError as exc:
                print(f"Could not type passkey to {socket_path}: {exc}")
        return

    log_path = Path(args.log)
    try:
        socket_path.unlink()
    except FileNotFoundError:
        pass
    try:
        Path(args.passkey_file).unlink()
    except FileNotFoundError:
        pass
    log_path.write_text("")

    cmd = [sys.executable, "-m", "btd.btd", "--log-level", "DEBUG"]
    print("Starting temporary BLE HID btd instance")
    print(f"Socket: {socket_path}")
    print(f"Log: {log_path}")
    print(f"Passkey file: {args.passkey_file}")
    print(f"Pairing window: {args.duration:.0f}s")
    os.environ["BTD_PAIRING_AGENT"] = args.pairing_agent
    os.environ["BTD_GATT_SECURITY"] = args.gatt_security
    print(f"Pairing agent: {args.pairing_agent}")
    print(f"GATT security: {args.gatt_security}")
    print("Host-side action: open Bluetooth settings and pair with <keyboard-host>")
    initially_connected = device_addresses(run_text(["bluetoothctl", "devices", "Connected"]))

    with log_path.open("ab") as log_file:
        proc = subprocess.Popen(
            cmd,
            cwd=args.repo,
            env=build_btd_env(str(socket_path), args.passkey_file),
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        try:
            if not wait_for_socket(str(socket_path), timeout=12.0):
                raise SystemExit(f"btd socket did not appear: {socket_path}\n{tail_log(str(log_path), 40)}")

            print_bluez_snapshot("pairing window open")
            if args.send_test_report:
                send_a_tap(str(socket_path))
                print("Sent test A press/release report")
            if args.type_passkey:
                send_passkey(str(socket_path), args.type_passkey)
                print("Typed pairing passkey followed by Enter")

            deadline = time.monotonic() + max(0.0, args.duration)
            sent_on_connect = False
            sent_on_notify = False
            connected_hint_printed = False
            while time.monotonic() < deadline:
                remaining = max(0, int(deadline - time.monotonic()))
                print(f"\n-- waiting for host pairing/connect: {remaining}s remaining --")
                devices = run_text(["bluetoothctl", "devices", "Connected"], timeout=4.0)
                print(devices or "(none)")
                connected_addresses = device_addresses(devices)
                print_device_infos(connected_addresses)
                if args.send_on_notify and not sent_on_notify and log_contains(str(log_path), NOTIFY_STARTED_MARKER):
                    send_a_tap(str(socket_path))
                    sent_on_notify = True
                    print("HID Input Report notify detected; sent one A press/release report")
                if connected_addresses:
                    if args.send_on_connect and not sent_on_connect:
                        send_a_tap(str(socket_path))
                        sent_on_connect = True
                        print("Connected host detected; sent one A press/release report")
                    elif not connected_hint_printed:
                        connected_hint_printed = True
                        print("BLE link detected by BlueZ. Check Paired/Bonded/ServicesResolved above before treating it as a usable keyboard connection.")
                        print("If ServicesResolved is yes or notify starts, you can send a test report:")
                        print(f"python3 script/send_btd_report.py --socket {socket_path} 0000040000000000")
                time.sleep(min(max(0.2, args.poll_interval), max(0.2, remaining)))
        except KeyboardInterrupt:
            print("\nInterrupted; closing pairing window")
        finally:
            if args.disconnect_on_exit:
                connected_now = device_addresses(run_text(["bluetoothctl", "devices", "Connected"]))
                for address in sorted(connected_now - initially_connected):
                    print(f"Disconnecting newly connected host: {address}")
                    print(run_text(["bluetoothctl", "disconnect", address], timeout=8.0) or "disconnect command completed")
            proc.terminate()
            try:
                proc.wait(timeout=8.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3.0)

    print_bluez_snapshot("after cleanup")
    print("\n== btd log tail ==")
    print(tail_log(str(log_path)))


if __name__ == "__main__":
    main()
