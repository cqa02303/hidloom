#!/usr/bin/env python3
"""Collect a post-incident matrixd/input diagnostics snapshot."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import shlex
import socket
import subprocess
import threading
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_SERVICES = ("matrixd", "logicd", "ledd", "httpd", "viald", "hidloom-hidd", "btd", "i2cd")
PROCESS_NAMES = ("matrixd", "logicd", "ledd", "httpd", "viald", "hidloom-hidd", "btd", "i2cd")
DEFAULT_KEY_SOCKET = "/tmp/key_events.sock"
DEFAULT_LEDD_SOCKET = "/tmp/ledd_events.sock"
DEFAULT_CTRL_SOCKET = "/tmp/ctrl_events.sock"
PRESS = 0x50
RELEASE = 0x52
RESTART_HINT_PATTERN = (
    "SW90|KC_SHUTDOWN|KC_SH10|logicd\\.macro|shutdown|poweroff|power off|halt|reboot|"
    "system will power off|system is powering down|sudo.*shutdown|sudo.*reboot|"
    "systemctl.*(restart|stop|reboot|poweroff|halt)|watchdog|oom|Out of memory|kernel panic|panic|"
    "Failed with result|Main process exited|code=killed|signal|timeout"
)
HANG_HINT_PATTERN = (
    "blocked for more than|hung task|soft lockup|hard lockup|rcu_sched|stall|deadlock|"
    "timeout|timed out|queue|backlog|latency|slow|Traceback|Exception|BrokenPipe|"
    "No buffer space|Resource temporarily unavailable|Input/output error|I/O error|"
    "under-voltage|undervoltage|voltage|throttled|reset|disconnect|disconnected"
)


@dataclass(frozen=True)
class CommandResult:
    title: str
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    elapsed_sec: float


@dataclass
class KeyMonitorResult:
    packets: int = 0
    valid_packets: int = 0
    invalid_packets: int = 0
    samples: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class LineMonitorResult:
    messages: int = 0
    key_messages: int = 0
    invalid_lines: int = 0
    samples: list[str] = field(default_factory=list)
    error: str = ""


def run_command(title: str, command: list[str], *, timeout: float = 10.0) -> CommandResult:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return CommandResult(title, command, proc.returncode, proc.stdout, proc.stderr, time.monotonic() - started)
    except FileNotFoundError as exc:
        return CommandResult(title, command, 127, "", str(exc), time.monotonic() - started)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return CommandResult(
            title,
            command,
            124,
            stdout,
            stderr + f"\nTIMEOUT after {timeout:.1f}s",
            time.monotonic() - started,
        )


def ps_command() -> list[str]:
    command = ["ps", "-o", "pid,ni,pri,rtprio,pcpu,pmem,rss,comm,args"]
    for name in PROCESS_NAMES:
        command.extend(["-C", name])
    return command


def journal_hint_command(*, boot: str | None = None, since: str | None = None) -> list[str]:
    return journal_filter_command(RESTART_HINT_PATTERN, boot=boot, since=since)


def journal_filter_command(pattern: str, *, boot: str | None = None, since: str | None = None) -> list[str]:
    command = ["journalctl", "--no-pager", "-l", "--output=short-iso"]
    if boot is not None:
        command.extend(["-b", boot])
    if since:
        command.extend(["--since", since])
    journal = " ".join(shlex.quote(part) for part in command)
    grep_pattern = shlex.quote(pattern)
    return ["sh", "-c", f"{journal} | grep -i -E {grep_pattern} || true"]


def process_filter_command(base_command: str, pattern: str) -> list[str]:
    return ["sh", "-c", f"{base_command} | grep -E {shlex.quote(pattern)} || true"]


def daemon_proc_command(path: str) -> list[str]:
    names = " ".join(shlex.quote(name) for name in PROCESS_NAMES)
    return [
        "sh",
        "-c",
        (
            f"for name in {names}; do "
            "for pid in $(pidof \"$name\" 2>/dev/null || true); do "
            "echo \"### $name pid=$pid\"; "
            f"if [ -r /proc/$pid/{path} ]; then cat /proc/$pid/{path}; else echo \"not readable: /proc/$pid/{path}\"; fi; "
            "echo; "
            "done; "
            "done"
        ),
    ]


def daemon_status_command() -> list[str]:
    wanted = "Name|State|Pid|PPid|Threads|FDSize|VmRSS|VmHWM|voluntary_ctxt_switches|nonvoluntary_ctxt_switches|Sig|Cpus_allowed_list"
    names = " ".join(shlex.quote(name) for name in PROCESS_NAMES)
    return [
        "sh",
        "-c",
        (
            f"for name in {names}; do "
            "for pid in $(pidof \"$name\" 2>/dev/null || true); do "
            "echo \"### $name pid=$pid\"; "
            f"grep -E {shlex.quote(wanted)} /proc/$pid/status 2>/dev/null || true; "
            "echo; "
            "done; "
            "done"
        ),
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
                    if len(result.samples) < 20:
                        result.samples.append(packet.hex())
            if buffer:
                result.invalid_packets += 1
                if len(result.samples) < 20:
                    result.samples.append(buffer.hex())
    except OSError as exc:
        result.error = str(exc)


def monitor_line_socket(sock_path: str, stop_event: threading.Event, result: LineMonitorResult) -> None:
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
                    if len(result.samples) < 20:
                        result.samples.append(text[:240])
    except OSError as exc:
        result.error = str(exc)


def json_request(sock_path: str, msg: dict[str, Any], *, timeout: float = 3.0) -> dict[str, Any]:
    try:
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
    except OSError as exc:
        return {"result": "error", "msg": str(exc)}
    try:
        return json.loads(data.decode("utf-8")) if data else {}
    except json.JSONDecodeError as exc:
        return {"result": "error", "msg": f"invalid json: {exc}", "raw": data.decode("utf-8", errors="replace")}


def fenced(text: str) -> str:
    return text.rstrip() if text.strip() else "(no output)"


def file_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False}
    try:
        data = path.read_bytes()
    except OSError as exc:
        return {"path": str(path), "exists": True, "error": str(exc)}
    text = data.decode("utf-8", errors="replace") if path.is_file() and len(data) <= 20000 else ""
    return {
        "path": str(path),
        "exists": True,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "text": text,
    }


def default_output_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    persistent_dir = Path("/mnt/p3/matrixd-diagnostics")
    if persistent_dir.exists() and persistent_dir.is_dir():
        return persistent_dir / f"matrixd-diagnostics-{stamp}.md"
    return Path("/tmp/hidloom-smoke") / f"matrixd-diagnostics-{stamp}.md"


def collect_commands(args: argparse.Namespace) -> list[CommandResult]:
    hint_since = args.since or "30 minutes ago"
    commands: list[tuple[str, list[str], float]] = [
        ("hostname", ["hostname"], 5.0),
        ("date", ["date", "-Is"], 5.0),
        ("uptime", ["uptime"], 5.0),
        ("system boots", ["journalctl", "--list-boots", "--no-pager"], 10.0),
        ("service active state", ["systemctl", "is-active", *DEFAULT_SERVICES], 10.0),
        (
            "service restart state",
            [
                "systemctl",
                "show",
                "logicd.service",
                "matrixd.service",
                "httpd.service",
                "-p",
                "Id",
                "-p",
                "ActiveState",
                "-p",
                "SubState",
                "-p",
                "Result",
                "-p",
                "NRestarts",
                "-p",
                "ExecMainCode",
                "-p",
                "ExecMainStatus",
                "-p",
                "ActiveEnterTimestamp",
                "-p",
                "InactiveEnterTimestamp",
            ],
            10.0,
        ),
        ("failed services", ["systemctl", "--failed", "--no-pager"], 10.0),
        (
            "matrixd priority",
            ["systemctl", "show", "matrixd", "-p", "Nice", "-p", "CPUSchedulingPolicy", "-p", "CPUSchedulingPriority"],
            10.0,
        ),
        ("matrixd unit", ["systemctl", "cat", "matrixd", "--no-pager"], 10.0),
        ("hid gadgets", ["ls", "-l", "/dev/hidg0", "/dev/hidg1"], 10.0),
        ("matrixd binary", ["file", str(ROOT / "daemon" / "matrixd" / "matrixd")], 10.0),
        ("process snapshot", ps_command(), 10.0),
        (
            "thread wait snapshot",
            process_filter_command(
                "ps -eLo pid,tid,ni,pri,rtprio,stat,pcpu,pmem,wchan:32,comm,args",
                "|".join(PROCESS_NAMES),
            ),
            10.0,
        ),
        ("daemon proc status", daemon_status_command(), 10.0),
        ("daemon kernel stacks", daemon_proc_command("stack"), 10.0),
        ("daemon open files", daemon_proc_command("fd"), 10.0),
        (
            "unix socket snapshot",
            process_filter_command(
                "ss -xap",
                "/tmp/(matrix|ctrl|ledd|key|i2c|spi)_events|matrixd|logicd|ledd|httpd|viald|hidloom-hidd|btd|i2cd",
            ),
            10.0,
        ),
        (
            "pressure and memory",
            [
                "sh",
                "-c",
                "cat /proc/pressure/cpu /proc/pressure/io /proc/pressure/memory 2>/dev/null; echo; free -h; echo; vmstat 1 3",
            ],
            10.0,
        ),
        ("kernel ring buffer tail", ["sh", "-c", "dmesg -T 2>/dev/null | tail -200 || true"], 10.0),
        ("previous boot shutdown/restart hints", journal_hint_command(boot="-1"), 30.0),
        ("recent shutdown/restart hints", journal_hint_command(since=hint_since), 30.0),
        ("recent hang/input hints", journal_filter_command(HANG_HINT_PATTERN, since=hint_since), 30.0),
    ]
    journal_command = ["journalctl"]
    for service in DEFAULT_SERVICES:
        journal_command.extend(["-u", service])
    if args.since:
        journal_command.extend(["--since", args.since])
    else:
        journal_command.extend(["-n", str(args.journal_lines)])
    journal_command.extend(["--no-pager"])
    commands.append(("recent daemon logs", journal_command, 30.0))
    return [run_command(title, command, timeout=timeout) for title, command, timeout in commands]


def monitor_events(args: argparse.Namespace) -> tuple[KeyMonitorResult, LineMonitorResult]:
    key_result = KeyMonitorResult()
    ledd_result = LineMonitorResult()
    stop_event = threading.Event()
    threads = [
        threading.Thread(target=monitor_key_events, args=(args.key_socket, stop_event, key_result), daemon=True),
        threading.Thread(target=monitor_line_socket, args=(args.ledd_socket, stop_event, ledd_result), daemon=True),
    ]
    for thread in threads:
        thread.start()
    time.sleep(args.duration)
    stop_event.set()
    for thread in threads:
        thread.join(timeout=2.0)
    return key_result, ledd_result


def render_report(
    *,
    args: argparse.Namespace,
    commands: list[CommandResult],
    key_result: KeyMonitorResult,
    ledd_result: LineMonitorResult,
    ctrl_snapshots: dict[str, dict[str, Any]],
    files: list[dict[str, Any]],
) -> str:
    lines = [
        "# matrixd Diagnostics Snapshot",
        "",
        f"- collected_at: `{datetime.now(timezone.utc).isoformat(timespec='seconds')}`",
        f"- host: `{socket.gethostname()}`",
        f"- platform: `{platform.platform()}`",
        f"- duration_sec: `{args.duration}`",
        f"- key_socket: `{args.key_socket}`",
        f"- ledd_socket: `{args.ledd_socket}`",
        "",
        "## Summary",
        "",
        f"- key_event_count: `{key_result.packets}`",
        f"- key_event_valid_count: `{key_result.valid_packets}`",
        f"- key_event_invalid_count: `{key_result.invalid_packets}`",
        f"- key_monitor_error: `{key_result.error or 'none'}`",
        f"- ledd_message_count: `{ledd_result.messages}`",
        f"- ledd_key_message_count: `{ledd_result.key_messages}`",
        f"- ledd_invalid_line_count: `{ledd_result.invalid_lines}`",
        f"- ledd_monitor_error: `{ledd_result.error or 'none'}`",
        "",
        "## Control Socket Snapshots",
        "",
        "```json",
        json.dumps(ctrl_snapshots, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Event Samples",
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
        "## File Snapshots",
        "",
    ]
    for info in files:
        lines.extend(
            [
                f"### {info['path']}",
                "",
                f"- exists: `{info['exists']}`",
            ]
        )
        if info.get("exists"):
            if info.get("error"):
                lines.append(f"- error: `{info['error']}`")
                lines.append("")
                continue
            lines.extend([f"- size: `{info['size']}`", f"- sha256: `{info['sha256']}`"])
            if info.get("text"):
                lines.extend(["", "```text", fenced(info["text"]), "```"])
        lines.append("")
    for result in commands:
        command_text = " ".join(shlex.quote(part) for part in result.command)
        lines.extend(
            [
                f"## {result.title}",
                "",
                f"- command: `{command_text}`",
                f"- exit: `{result.returncode}`",
                f"- elapsed_sec: `{result.elapsed_sec:.3f}`",
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
    parser.add_argument("--duration", type=float, default=10.0, help="seconds to watch key/ledd event sockets")
    parser.add_argument("--output", type=Path, default=None, help="write Markdown report to this path")
    parser.add_argument("--journal-lines", type=int, default=300, help="journal lines to collect when --since is omitted")
    parser.add_argument("--since", help="journalctl --since value, e.g. '10 minutes ago'")
    parser.add_argument("--key-socket", default=DEFAULT_KEY_SOCKET)
    parser.add_argument("--ledd-socket", default=DEFAULT_LEDD_SOCKET)
    parser.add_argument("--ctrl", default=DEFAULT_CTRL_SOCKET)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.duration < 0:
        raise SystemExit("--duration must be >= 0")
    output = args.output or default_output_path()
    files = [
        file_snapshot(ROOT / "config" / "default" / "matrixd.json"),
        file_snapshot(Path("/etc/systemd/system/matrixd.service")),
        file_snapshot(Path("/etc/systemd/system/logicd.service")),
        file_snapshot(Path("/etc/systemd/system/httpd.service")),
        file_snapshot(Path("/mnt/p3/script/KC_SH8.sh")),
        file_snapshot(Path("/mnt/p3/keymap.json")),
        file_snapshot(Path("/mnt/p3/led_state.json")),
    ]
    ctrl_snapshots = {
        "led_state": json_request(args.ctrl, {"t": "LED", "op": "vialrgb_get"}),
        "active_layers": json_request(args.ctrl, {"t": "ACTIVE"}),
        "pressed_matrix": json_request(args.ctrl, {"t": "K"}),
    }
    key_result, ledd_result = monitor_events(args)
    commands = collect_commands(args)
    report = render_report(
        args=args,
        commands=commands,
        key_result=key_result,
        ledd_result=ledd_result,
        ctrl_snapshots=ctrl_snapshots,
        files=files,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
