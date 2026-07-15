#!/usr/bin/env python3
"""Run a real-device matrixd stability smoke under a temporary LED effect."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import shlex
import socket
import subprocess
import threading
import time
from typing import Any

DEFAULT_CTRL_SOCKET = "/tmp/ctrl_events.sock"
DEFAULT_KEY_SOCKET = "/tmp/key_events.sock"
DEFAULT_LEDD_SOCKET = "/tmp/ledd_events.sock"
DEFAULT_SERVICES = ("matrixd", "logicd", "ledd", "httpd", "viald", "hidloom-hidd", "btd", "i2cd")
PROCESS_NAMES = ("matrixd", "logicd", "ledd", "httpd", "viald", "hidloom-hidd", "btd", "i2cd")
INTERESTING_LOG_PATTERNS = (
    " failed",
    " failure",
    " warning",
    " warn",
    " error:",
    " error ",
    " overflow",
    " drop",
    " blocked",
    " timeout",
    "失敗",
)
PRESS = 0x50
RELEASE = 0x52


@dataclass
class CommandResult:
    title: str
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


@dataclass
class KeyMonitorResult:
    packets: int = 0
    valid_packets: int = 0
    invalid_packets: int = 0
    samples: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class LeddMonitorResult:
    messages: int = 0
    key_messages: int = 0
    invalid_lines: int = 0
    samples: list[str] = field(default_factory=list)
    error: str = ""


def json_request(sock_path: str, msg: dict[str, Any], *, timeout: float = 3.0) -> dict[str, Any]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(sock_path)
        sock.sendall((json.dumps(msg, separators=(",", ":")) + "\n").encode("utf-8"))
        data = b""
        while not data.endswith(b"\n"):
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
    return json.loads(data.decode("utf-8")) if data else {}


def run_command(title: str, command: list[str], *, timeout: float = 10.0) -> CommandResult:
    try:
        proc = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return CommandResult(title, command, proc.returncode, proc.stdout, proc.stderr)
    except FileNotFoundError as exc:
        return CommandResult(title, command, 127, "", str(exc))
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return CommandResult(title, command, 124, stdout, stderr + f"\nTIMEOUT after {timeout:.1f}s")


def ps_command() -> list[str]:
    command = ["ps", "-o", "pid,comm,rss,pcpu,args"]
    for name in PROCESS_NAMES:
        command.extend(["-C", name])
    return command


def valid_key_packet(packet: bytes) -> bool:
    return len(packet) == 4 and packet[0] in (PRESS, RELEASE)


def monitor_key_events(sock_path: str, stop_event: threading.Event, result: KeyMonitorResult) -> None:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            sock.connect(sock_path)
            buffer = b""
            while not stop_event.is_set():
                try:
                    chunk = sock.recv(4096)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buffer += chunk
                while len(buffer) >= 4:
                    packet, buffer = buffer[:4], buffer[4:]
                    result.packets += 1
                    if valid_key_packet(packet):
                        result.valid_packets += 1
                    else:
                        result.invalid_packets += 1
                    if len(result.samples) < 10:
                        result.samples.append(packet.hex())
            if buffer:
                result.invalid_packets += 1
                if len(result.samples) < 10:
                    result.samples.append(buffer.hex())
    except OSError as exc:
        result.error = str(exc)


def monitor_ledd_events(sock_path: str, stop_event: threading.Event, result: LeddMonitorResult) -> None:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            sock.connect(sock_path)
            buffer = b""
            while not stop_event.is_set():
                try:
                    chunk = sock.recv(4096)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line:
                        continue
                    result.messages += 1
                    text = line.decode("utf-8", errors="replace")
                    try:
                        msg = json.loads(text)
                    except json.JSONDecodeError:
                        result.invalid_lines += 1
                        msg = {}
                    if msg.get("t") == "key":
                        result.key_messages += 1
                    if len(result.samples) < 10:
                        result.samples.append(text[:240])
    except OSError as exc:
        result.error = str(exc)


def collect_interesting_logs(since: datetime, services: tuple[str, ...], *, timeout: float = 20.0) -> tuple[CommandResult, list[str]]:
    command = ["journalctl"]
    for service in services:
        command.extend(["-u", service])
    command.extend(["--since", since.astimezone().strftime("%Y-%m-%d %H:%M:%S"), "--no-pager"])
    result = run_command("recent daemon logs", command, timeout=timeout)
    interesting = [
        line
        for line in result.stdout.splitlines()
        if any(pattern in line.lower() for pattern in INTERESTING_LOG_PATTERNS)
    ]
    return result, interesting


def service_status_results(services: tuple[str, ...]) -> list[CommandResult]:
    results = [
        run_command("service active state", ["systemctl", "is-active", *services], timeout=10.0),
        run_command(
            "matrixd priority",
            [
                "systemctl",
                "show",
                "matrixd",
                "-p",
                "Nice",
                "-p",
                "CPUSchedulingPolicy",
                "-p",
                "CPUSchedulingPriority",
            ],
            timeout=10.0,
        ),
        run_command("process snapshot", ps_command(), timeout=10.0),
    ]
    return results


def apply_led_effect(args: argparse.Namespace) -> dict[str, Any]:
    return json_request(
        args.ctrl,
        {
            "t": "LED",
            "op": "vialrgb",
            "mode": args.mode,
            "speed": args.speed,
            "h": args.hue,
            "s": args.saturation,
            "v": args.value,
            "save": False,
        },
    )


def restore_led(args: argparse.Namespace, original: dict[str, Any]) -> dict[str, Any]:
    return json_request(
        args.ctrl,
        {
            "t": "LED",
            "op": "vialrgb",
            "mode": original["mode"],
            "speed": original["speed"],
            "h": original["h"],
            "s": original["s"],
            "v": original["v"],
            "save": False,
        },
    )


def fenced(text: str) -> str:
    return text.rstrip() if text.strip() else "(no output)"


def render_report(
    *,
    args: argparse.Namespace,
    started_at: datetime,
    elapsed_sec: float,
    original_led: dict[str, Any],
    apply_response: dict[str, Any],
    effective_led: dict[str, Any],
    restore_response: dict[str, Any] | None,
    key_result: KeyMonitorResult,
    ledd_result: LeddMonitorResult,
    command_results: list[CommandResult],
    log_result: CommandResult,
    interesting_logs: list[str],
    passed: bool,
) -> str:
    lines = [
        "# matrixd Stability Smoke",
        "",
        f"- collected_at: `{datetime.now(timezone.utc).isoformat(timespec='seconds')}`",
        f"- started_at: `{started_at.isoformat(timespec='seconds')}`",
        f"- host: `{socket.gethostname()}`",
        f"- platform: `{platform.platform()}`",
        f"- duration_sec: `{args.duration}`",
        f"- elapsed_sec: `{elapsed_sec:.3f}`",
        f"- result: `{'pass' if passed else 'fail'}`",
        f"- ctrl_socket: `{args.ctrl}`",
        f"- key_event_socket: `{args.key_socket}`",
        f"- ledd_event_socket: `{args.ledd_socket}`",
        f"- LED effect: `mode={args.mode} speed={args.speed} h={args.hue} s={args.saturation} v={args.value} save=false`",
        "",
        "## Summary",
        "",
        f"- key_event_count: `{key_result.packets}`",
        f"- key_event_valid_count: `{key_result.valid_packets}`",
        f"- key_event_invalid_count: `{key_result.invalid_packets}`",
        f"- ledd_message_count: `{ledd_result.messages}`",
        f"- ledd_key_message_count: `{ledd_result.key_messages}`",
        f"- ledd_invalid_line_count: `{ledd_result.invalid_lines}`",
        f"- interesting_log_count: `{len(interesting_logs)}`",
        f"- key_monitor_error: `{key_result.error or 'none'}`",
        f"- ledd_monitor_error: `{ledd_result.error or 'none'}`",
        "",
        "## LED",
        "",
        "original:",
        "",
        "```json",
        json.dumps(original_led, ensure_ascii=False, indent=2),
        "```",
        "",
        "apply_response:",
        "",
        "```json",
        json.dumps(apply_response, ensure_ascii=False, indent=2),
        "```",
        "",
        "effective_led:",
        "",
        "```json",
        json.dumps(effective_led, ensure_ascii=False, indent=2),
        "```",
        "",
        "restore_response:",
        "",
        "```json",
        json.dumps(restore_response or {}, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Monitor Samples",
        "",
        "key_events:",
        "",
        "```text",
        fenced("\n".join(key_result.samples)),
        "```",
        "",
        "ledd_events:",
        "",
        "```text",
        fenced("\n".join(ledd_result.samples)),
        "```",
        "",
        "## Interesting Logs",
        "",
        "```text",
        fenced("\n".join(interesting_logs)),
        "```",
        "",
    ]
    for result in [*command_results, log_result]:
        command_text = " ".join(shlex.quote(part) for part in result.command)
        lines.extend(
            [
                f"## {result.title}",
                "",
                f"- command: `{command_text}`",
                f"- exit: `{result.returncode}`",
                "",
                "stdout:",
                "",
                "```text",
                fenced(result.stdout),
                "```",
                "",
                "stderr:",
                "",
                "```text",
                fenced(result.stderr),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=60.0, help="seconds to observe")
    parser.add_argument("--output", type=Path, help="write Markdown report to this path")
    parser.add_argument("--ctrl", default=DEFAULT_CTRL_SOCKET)
    parser.add_argument("--key-socket", default=DEFAULT_KEY_SOCKET)
    parser.add_argument("--ledd-socket", default=DEFAULT_LEDD_SOCKET)
    parser.add_argument("--mode", type=int, default=40, help="VialRGB mode, default Multisplash")
    parser.add_argument("--speed", type=int, default=128)
    parser.add_argument("--hue", type=int, default=80)
    parser.add_argument("--saturation", type=int, default=255)
    parser.add_argument("--value", type=int, default=160, help="brightness/value")
    parser.add_argument("--no-restore", action="store_true", help="leave the temporary LED effect active")
    parser.add_argument("--allow-events", action="store_true", help="do not fail when key events are observed")
    parser.add_argument("--allow-log-warnings", action="store_true", help="do not fail on interesting daemon logs")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.duration <= 0:
        raise SystemExit("--duration must be > 0")
    for path in (args.ctrl, args.key_socket, args.ledd_socket):
        if not Path(path).exists():
            raise SystemExit(f"socket not found: {path}")

    started_at = datetime.now(timezone.utc)
    original_led = json_request(args.ctrl, {"t": "LED", "op": "vialrgb_get"})
    if original_led.get("result") != "ok":
        raise SystemExit(f"failed to read original LED state: {original_led}")

    key_result = KeyMonitorResult()
    ledd_result = LeddMonitorResult()
    stop_event = threading.Event()
    key_thread = threading.Thread(target=monitor_key_events, args=(args.key_socket, stop_event, key_result), daemon=True)
    ledd_thread = threading.Thread(target=monitor_ledd_events, args=(args.ledd_socket, stop_event, ledd_result), daemon=True)
    key_thread.start()
    ledd_thread.start()

    apply_response: dict[str, Any] = {}
    effective_led: dict[str, Any] = {}
    restore_response: dict[str, Any] | None = None
    wall_start = time.monotonic()
    try:
        time.sleep(0.2)
        apply_response = apply_led_effect(args)
        if apply_response.get("result") != "ok":
            raise SystemExit(f"failed to apply LED effect: {apply_response}")
        effective_led = json_request(args.ctrl, {"t": "LED", "op": "vialrgb_get"})
        time.sleep(args.duration)
    finally:
        stop_event.set()
        key_thread.join(timeout=2.0)
        ledd_thread.join(timeout=2.0)
        if not args.no_restore:
            restore_response = restore_led(args, original_led)

    elapsed_sec = time.monotonic() - wall_start
    command_results = service_status_results(DEFAULT_SERVICES)
    log_result, interesting_logs = collect_interesting_logs(started_at, DEFAULT_SERVICES)
    services_active = command_results[0].returncode == 0
    monitor_ok = not key_result.error and not ledd_result.error
    event_ok = args.allow_events or (key_result.packets == 0 and ledd_result.key_messages == 0)
    log_ok = args.allow_log_warnings or not interesting_logs
    passed = services_active and monitor_ok and event_ok and log_ok

    report = render_report(
        args=args,
        started_at=started_at,
        elapsed_sec=elapsed_sec,
        original_led=original_led,
        apply_response=apply_response,
        effective_led=effective_led,
        restore_response=restore_response,
        key_result=key_result,
        ledd_result=ledd_result,
        command_results=command_results,
        log_result=log_result,
        interesting_logs=interesting_logs,
        passed=passed,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report + "\n", encoding="utf-8")
        print(args.output)
    else:
        print(report)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
