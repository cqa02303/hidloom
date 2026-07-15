#!/usr/bin/env python3
"""Run no-touch LED stress scenarios while watching for matrix ghost input."""
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
from typing import Any, Iterable

DEFAULT_CTRL_SOCKET = "/tmp/ctrl_events.sock"
DEFAULT_KEY_SOCKET = "/tmp/key_events.sock"
DEFAULT_LEDD_SOCKET = "/tmp/ledd_events.sock"
DEFAULT_SERVICES = ("matrixd", "logicd", "ledd", "httpd", "viald", "hidloom-hidd", "btd", "i2cd")
PROCESS_NAMES = ("matrixd", "logicd", "ledd", "httpd", "viald", "hidloom-hidd", "btd", "i2cd")
PRESS = 0x50
RELEASE = 0x52
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


@dataclass(frozen=True)
class LedEffect:
    label: str
    mode: int
    speed: int
    hue: int
    saturation: int
    value: int
    dummy_rate_hz: float = 0.0


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


@dataclass
class DummySplashResult:
    sent_messages: int = 0
    error: str = ""


@dataclass
class ScenarioResult:
    effect: LedEffect
    started_at: datetime
    elapsed_sec: float
    apply_response: dict[str, Any]
    effective_led: dict[str, Any]
    key_result: KeyMonitorResult
    ledd_result: LeddMonitorResult
    dummy_result: DummySplashResult
    passed: bool


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


def service_status_results(services: tuple[str, ...]) -> list[CommandResult]:
    return [
        run_command("service active state", ["systemctl", "is-active", *services], timeout=10.0),
        run_command("process snapshot", ps_command(), timeout=10.0),
    ]


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
                    if len(result.samples) < 12:
                        result.samples.append(packet.hex())
            if buffer:
                result.invalid_packets += 1
                if len(result.samples) < 12:
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
                    if len(result.samples) < 12:
                        result.samples.append(text[:240])
    except OSError as exc:
        result.error = str(exc)


def send_ctrl_led_key_event(sock: socket.socket, *, row: int, col: int, kind: str) -> dict[str, Any]:
    msg = {"t": "LED", "op": "key_event", "kind": kind, "row": row, "col": col}
    sock.sendall((json.dumps(msg, separators=(",", ":")) + "\n").encode("utf-8"))
    data = b""
    while not data.endswith(b"\n"):
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    return json.loads(data.decode("utf-8")) if data else {}


def dummy_splash_producer(
    ctrl_sock_path: str,
    stop_event: threading.Event,
    result: DummySplashResult,
    *,
    rate_hz: float,
    positions: list[tuple[int, int]],
) -> None:
    if rate_hz <= 0:
        return
    interval = 1.0 / rate_hz
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            sock.connect(ctrl_sock_path)
            index = 0
            next_at = time.monotonic()
            while not stop_event.is_set():
                row, col = positions[index % len(positions)]
                for kind in ("P", "R"):
                    response = send_ctrl_led_key_event(sock, row=row, col=col, kind=kind)
                    if response.get("result") != "ok":
                        raise OSError(f"LED key_event failed: {response}")
                result.sent_messages += 2
                index += 1
                next_at += interval
                delay = next_at - time.monotonic()
                if delay > 0:
                    stop_event.wait(delay)
    except OSError as exc:
        result.error = str(exc)


def apply_led_effect(ctrl_sock: str, effect: LedEffect) -> dict[str, Any]:
    return json_request(
        ctrl_sock,
        {
            "t": "LED",
            "op": "vialrgb",
            "mode": effect.mode,
            "speed": effect.speed,
            "h": effect.hue,
            "s": effect.saturation,
            "v": effect.value,
            "save": False,
        },
    )


def restore_led(ctrl_sock: str, original: dict[str, Any]) -> dict[str, Any]:
    return json_request(
        ctrl_sock,
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


def default_effects() -> list[LedEffect]:
    return [
        LedEffect("led-off", 0, 32, 0, 0, 0),
        LedEffect("solid-low", 2, 32, 175, 77, 64),
        LedEffect("default-multisplash", 40, 32, 175, 77, 160),
        LedEffect("risky-multisplash", 40, 128, 80, 255, 160),
        LedEffect("dummy-splash-10hz", 40, 32, 175, 77, 160, dummy_rate_hz=10.0),
        LedEffect("dummy-splash-30hz", 40, 32, 175, 77, 160, dummy_rate_hz=30.0),
        LedEffect("dummy-splash-60hz", 40, 32, 175, 77, 160, dummy_rate_hz=60.0),
    ]


def parse_effect(text: str) -> LedEffect:
    parts = text.split(":")
    if len(parts) not in {6, 7}:
        raise argparse.ArgumentTypeError("effect must be label:mode:speed:h:s:v[:dummy_rate_hz]")
    label = parts[0].strip()
    if not label:
        raise argparse.ArgumentTypeError("effect label must not be empty")
    try:
        mode, speed, hue, saturation, value = [int(part) for part in parts[1:6]]
        dummy_rate = float(parts[6]) if len(parts) == 7 else 0.0
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return LedEffect(label, mode, speed, hue, saturation, value, dummy_rate)


def parse_position(text: str) -> tuple[int, int]:
    try:
        row_text, col_text = text.split(",", 1)
        return int(row_text), int(col_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("position must be row,col") from exc


def scenario_passed(
    *,
    key_result: KeyMonitorResult,
    ledd_result: LeddMonitorResult,
    dummy_result: DummySplashResult,
    allow_events: bool,
    allow_monitor_errors: bool,
) -> bool:
    if not allow_monitor_errors and (key_result.error or ledd_result.error or dummy_result.error):
        return False
    if allow_events:
        return True
    return key_result.packets == 0


def run_scenario(args: argparse.Namespace, effect: LedEffect) -> ScenarioResult:
    started_at = datetime.now(timezone.utc)
    key_result = KeyMonitorResult()
    ledd_result = LeddMonitorResult()
    dummy_result = DummySplashResult()
    stop_event = threading.Event()
    threads = [
        threading.Thread(target=monitor_key_events, args=(args.key_socket, stop_event, key_result), daemon=True),
        threading.Thread(target=monitor_ledd_events, args=(args.ledd_socket, stop_event, ledd_result), daemon=True),
    ]
    if effect.dummy_rate_hz > 0:
        threads.append(
            threading.Thread(
                target=dummy_splash_producer,
                args=(args.ctrl, stop_event, dummy_result),
                kwargs={"rate_hz": effect.dummy_rate_hz, "positions": args.dummy_position},
                daemon=True,
            )
        )
    for thread in threads:
        thread.start()
    wall_start = time.monotonic()
    apply_response: dict[str, Any] = {}
    effective_led: dict[str, Any] = {}
    try:
        time.sleep(args.settle)
        apply_response = apply_led_effect(args.ctrl, effect)
        if apply_response.get("result") != "ok":
            raise SystemExit(f"failed to apply LED effect {effect.label}: {apply_response}")
        effective_led = json_request(args.ctrl, {"t": "LED", "op": "vialrgb_get"})
        time.sleep(args.duration)
    finally:
        stop_event.set()
        for thread in threads:
            thread.join(timeout=2.0)
    elapsed_sec = time.monotonic() - wall_start
    passed = scenario_passed(
        key_result=key_result,
        ledd_result=ledd_result,
        dummy_result=dummy_result,
        allow_events=args.allow_events,
        allow_monitor_errors=args.allow_monitor_errors,
    )
    return ScenarioResult(effect, started_at, elapsed_sec, apply_response, effective_led, key_result, ledd_result, dummy_result, passed)


def fenced(text: str) -> str:
    return text.rstrip() if text.strip() else "(no output)"


def render_report(
    *,
    args: argparse.Namespace,
    started_at: datetime,
    original_led: dict[str, Any],
    restore_response: dict[str, Any] | None,
    scenarios: list[ScenarioResult],
    command_results: list[CommandResult],
    log_result: CommandResult,
    interesting_logs: list[str],
    passed: bool,
) -> str:
    lines = [
        "# matrixd LED Stress Sweep",
        "",
        f"- collected_at: `{datetime.now(timezone.utc).isoformat(timespec='seconds')}`",
        f"- started_at: `{started_at.isoformat(timespec='seconds')}`",
        f"- host: `{socket.gethostname()}`",
        f"- platform: `{platform.platform()}`",
        f"- scenario_count: `{len(scenarios)}`",
        f"- duration_sec_per_scenario: `{args.duration}`",
        f"- result: `{'pass' if passed else 'fail'}`",
        f"- ctrl_socket: `{args.ctrl}`",
        f"- key_event_socket: `{args.key_socket}`",
        f"- ledd_event_socket: `{args.ledd_socket}`",
        "",
        "## Summary",
        "",
        "| scenario | LED | dummy rate | key events | ledd key messages | dummy sent | result |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for scenario in scenarios:
        effect = scenario.effect
        led = f"mode={effect.mode} speed={effect.speed} h={effect.hue} s={effect.saturation} v={effect.value}"
        lines.append(
            "| "
            + " | ".join(
                [
                    effect.label,
                    led,
                    f"{effect.dummy_rate_hz:g}",
                    str(scenario.key_result.packets),
                    str(scenario.ledd_result.key_messages),
                    str(scenario.dummy_result.sent_messages),
                    "pass" if scenario.passed else "fail",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## LED Restore",
            "",
            "original:",
            "",
            "```json",
            json.dumps(original_led, ensure_ascii=False, indent=2),
            "```",
            "",
            "restore_response:",
            "",
            "```json",
            json.dumps(restore_response or {}, ensure_ascii=False, indent=2),
            "```",
            "",
            "## Scenarios",
            "",
        ]
    )
    for scenario in scenarios:
        lines.extend(render_scenario_section(scenario))
    lines.extend(
        [
            "## Interesting Logs",
            "",
            f"- interesting_log_count: `{len(interesting_logs)}`",
            "",
            "```text",
            fenced("\n".join(interesting_logs)),
            "```",
            "",
        ]
    )
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


def render_scenario_section(scenario: ScenarioResult) -> list[str]:
    effect = scenario.effect
    return [
        f"### {effect.label}",
        "",
        f"- started_at: `{scenario.started_at.isoformat(timespec='seconds')}`",
        f"- elapsed_sec: `{scenario.elapsed_sec:.3f}`",
        f"- LED: `mode={effect.mode} speed={effect.speed} h={effect.hue} s={effect.saturation} v={effect.value}`",
        f"- dummy_rate_hz: `{effect.dummy_rate_hz:g}`",
        f"- result: `{'pass' if scenario.passed else 'fail'}`",
        f"- key_event_count: `{scenario.key_result.packets}`",
        f"- key_event_valid_count: `{scenario.key_result.valid_packets}`",
        f"- key_event_invalid_count: `{scenario.key_result.invalid_packets}`",
        f"- ledd_message_count: `{scenario.ledd_result.messages}`",
        f"- ledd_key_message_count: `{scenario.ledd_result.key_messages}`",
        f"- dummy_ledd_key_messages_sent: `{scenario.dummy_result.sent_messages}`",
        f"- key_monitor_error: `{scenario.key_result.error or 'none'}`",
        f"- ledd_monitor_error: `{scenario.ledd_result.error or 'none'}`",
        f"- dummy_error: `{scenario.dummy_result.error or 'none'}`",
        "",
        "apply_response:",
        "",
        "```json",
        json.dumps(scenario.apply_response, ensure_ascii=False, indent=2),
        "```",
        "",
        "effective_led:",
        "",
        "```json",
        json.dumps(scenario.effective_led, ensure_ascii=False, indent=2),
        "```",
        "",
        "key_events:",
        "",
        "```text",
        fenced("\n".join(scenario.key_result.samples)),
        "```",
        "",
        "ledd_events:",
        "",
        "```text",
        fenced("\n".join(scenario.ledd_result.samples)),
        "```",
        "",
    ]


def selected_effects(args: argparse.Namespace) -> list[LedEffect]:
    effects = args.effect or default_effects()
    if args.quick:
        labels = {"led-off", "default-multisplash", "risky-multisplash", "dummy-splash-30hz"}
        effects = [effect for effect in effects if effect.label in labels]
    return effects


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=60.0, help="seconds to observe each scenario")
    parser.add_argument("--settle", type=float, default=0.2, help="seconds to wait after monitors connect")
    parser.add_argument("--output", type=Path, help="write Markdown report to this path")
    parser.add_argument("--ctrl", default=DEFAULT_CTRL_SOCKET)
    parser.add_argument("--key-socket", default=DEFAULT_KEY_SOCKET)
    parser.add_argument("--ledd-socket", default=DEFAULT_LEDD_SOCKET)
    parser.add_argument(
        "--effect",
        type=parse_effect,
        action="append",
        help="custom scenario as label:mode:speed:h:s:v[:dummy_rate_hz]; can be repeated",
    )
    parser.add_argument("--quick", action="store_true", help="run a shorter representative scenario set")
    parser.add_argument("--dummy-position", type=parse_position, action="append", default=None)
    parser.add_argument("--no-restore", action="store_true", help="leave the last temporary LED effect active")
    parser.add_argument("--allow-events", action="store_true", help="do not fail when key events are observed")
    parser.add_argument("--allow-monitor-errors", action="store_true", help="do not fail on monitor/producer socket errors")
    parser.add_argument("--allow-log-warnings", action="store_true", help="do not fail on interesting daemon logs")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> None:
    args = parse_args(argv)
    if args.duration <= 0:
        raise SystemExit("--duration must be > 0")
    if args.settle < 0:
        raise SystemExit("--settle must be >= 0")
    args.dummy_position = args.dummy_position or [(0, 1), (0, 2), (1, 2), (3, 3), (4, 6), (5, 3)]
    for path in (args.ctrl, args.key_socket, args.ledd_socket):
        if not Path(path).exists():
            raise SystemExit(f"socket not found: {path}")

    started_at = datetime.now(timezone.utc)
    original_led = json_request(args.ctrl, {"t": "LED", "op": "vialrgb_get"})
    if original_led.get("result") != "ok":
        raise SystemExit(f"failed to read original LED state: {original_led}")

    scenarios: list[ScenarioResult] = []
    restore_response: dict[str, Any] | None = None
    try:
        for effect in selected_effects(args):
            print(f"scenario: {effect.label}", flush=True)
            scenarios.append(run_scenario(args, effect))
    finally:
        if not args.no_restore:
            restore_response = restore_led(args.ctrl, original_led)

    command_results = service_status_results(DEFAULT_SERVICES)
    log_result, interesting_logs = collect_interesting_logs(started_at, DEFAULT_SERVICES)
    services_active = command_results[0].returncode == 0
    log_ok = args.allow_log_warnings or not interesting_logs
    passed = services_active and log_ok and all(scenario.passed for scenario in scenarios)

    report = render_report(
        args=args,
        started_at=started_at,
        original_led=original_led,
        restore_response=restore_response,
        scenarios=scenarios,
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
