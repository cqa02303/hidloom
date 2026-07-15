#!/usr/bin/env python3
"""Collect boot-readiness markers for Raspberry Pi OS / Buildroot comparison."""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import platform
import shlex
import socket
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_UNITS = (
    "hidloom-usb-gadget.service",
    "hidloom-network-late.service",
    "hidloom-network-late.timer",
    "viald.service",
    "usbd.service",
    "hidloom-hidd.service",
    "hidloom-uidd.service",
    "hidloom-outputd.service",
    "hidloom-logicd-core.service",
    "logicd.service",
    "logicd-companion.service",
    "matrixd.service",
    "httpd.service",
    "i2cd.service",
    "ledd.service",
    "btd.service",
    "NetworkManager.service",
    "wpa_supplicant.service",
    "ssh.service",
)

DEFAULT_SOCKET_PATHS = (
    "/tmp/usbd_hid_reports.sock",
    "/tmp/uidd_reports.sock",
    "/tmp/hidloom_output_reports.sock",
    "/tmp/hidloom_output_ctrl.sock",
    "/tmp/matrix_events.sock",
    "/tmp/matrix_events_shadow.sock",
    "/tmp/logicd_core_ctrl.sock",
)

DEFAULT_STATUS_PATHS = (
    "/run/hidloom/hidd-status.json",
    "/run/hidloom/uidd-status.json",
    "/run/hidloom/outputd-status.json",
    "/run/hidloom/logicd-core-status.json",
)


@dataclass(frozen=True)
class CommandResult:
    title: str
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    elapsed_sec: float


@dataclass(frozen=True)
class UnitMarker:
    unit: str
    active_state: str
    sub_state: str
    exec_start_sec: float | None
    active_enter_sec: float | None


@dataclass(frozen=True)
class TimelineMarker:
    time_sec: float
    kind: str
    label: str
    source: str
    confidence: str
    message: str


@dataclass(frozen=True)
class JournalRule:
    label: str
    kind: str
    source_pattern: re.Pattern[str]
    message_pattern: re.Pattern[str]


@dataclass(frozen=True)
class SocketSnapshot:
    path: str
    exists: bool
    is_socket: bool
    mode: str
    uid: int | None
    gid: int | None
    error: str


@dataclass(frozen=True)
class StatusSnapshot:
    path: str
    exists: bool
    valid_json: bool
    schema: str
    summary: str
    raw: str
    error: str


JOURNAL_RULES: tuple[JournalRule, ...] = (
    JournalRule(
        "usb gadget configured",
        "usb-gadget",
        re.compile(r"setup_usb_gadget|hidloom-usb-gadget|systemd", re.I),
        re.compile(r"USB HID gadget configured|Finished hidloom-usb-gadget", re.I),
    ),
    JournalRule(
        "hidd broker active",
        "hid-broker",
        re.compile(r"systemd|hidloom-hidd", re.I),
        re.compile(r"Started hidloom-hidd|native HID report broker", re.I),
    ),
    JournalRule(
        "output router active",
        "output-router",
        re.compile(r"systemd|hidloom-outputd", re.I),
        re.compile(r"Started hidloom-outputd|native HID report output router", re.I),
    ),
    JournalRule(
        "uinput sink active",
        "uinput-sink",
        re.compile(r"systemd|hidloom-uidd", re.I),
        re.compile(r"Started hidloom-uidd|native uinput report sink", re.I),
    ),
    JournalRule(
        "logicd-core active",
        "input-core",
        re.compile(r"systemd|hidloom-logicd-core", re.I),
        re.compile(r"Started hidloom-logicd-core|native logicd core", re.I),
    ),
    JournalRule(
        "matrixd active",
        "matrix-scan",
        re.compile(r"systemd|matrixd", re.I),
        re.compile(r"Started matrixd|Keyboard Matrix Scanner", re.I),
    ),
    JournalRule(
        "matrixd configured",
        "matrix-scan",
        re.compile(r"matrixd", re.I),
        re.compile(r"設定読み込み完了|GPIO 初期化完了|debounce|デバウンス", re.I),
    ),
    JournalRule(
        "matrixd connected to logic owner",
        "input-ready",
        re.compile(r"matrixd", re.I),
        re.compile(r"logicd に接続しました|connected.*logicd|logicd.*connected", re.I),
    ),
    JournalRule(
        "matrix tap connected",
        "tap-ready",
        re.compile(r"matrixd", re.I),
        re.compile(r"matrix tap に接続しました|matrix tap.*connected", re.I),
    ),
    JournalRule(
        "logicd output setup",
        "output-ready",
        re.compile(r"logicd|logicd-companion", re.I),
        re.compile(r"output setup duration|Keyboard output targets enabled|output router enabled", re.I),
    ),
    JournalRule(
        "logicd sockets listening",
        "socket-ready",
        re.compile(r"logicd|logicd-companion", re.I),
        re.compile(r"Listening on .*sock|sockets listening", re.I),
    ),
    JournalRule(
        "host led report reader opened",
        "hid-feedback",
        re.compile(r"logicd|logicd-companion", re.I),
        re.compile(r"host LED output report reader|opened .*hidg", re.I),
    ),
    JournalRule(
        "i2cd connected",
        "peripheral-ready",
        re.compile(r"logicd|logicd-companion", re.I),
        re.compile(r"i2cd に接続|i2c events", re.I),
    ),
    JournalRule(
        "ssh listening",
        "network-access",
        re.compile(r"sshd|ssh|systemd", re.I),
        re.compile(r"Server listening .* port 22|Started ssh\.service", re.I),
    ),
    JournalRule(
        "network connected",
        "network-ready",
        re.compile(r"NetworkManager|dhclient|wpa_supplicant", re.I),
        re.compile(r"CONNECTED|DHCP|lease|state is now CONNECTED", re.I),
    ),
)

DISCOVERY_MESSAGE_PATTERN = re.compile(
    r"ready|configured|listening|connected|initialized|loaded|opened|active|dhcp|lease|failed|error|timeout",
    re.I,
)
JOURNAL_GREP_PATTERN = (
    "ready|configured|listening|Listening|connected|接続|initialized|loaded|opened|active|dhcp|lease|"
    "failed|error|timeout|USB HID gadget configured|logicd boot marker|"
    "Started hidloom-hidd|Started hidloom-uidd|Started hidloom-outputd|"
    "Started hidloom-logicd-core|Started matrixd|"
    "設定読み込み完了|GPIO 初期化完了|デバウンス|Keyboard output targets enabled|output router enabled"
)
EMPTY_STATUS_ERROR_PATTERN = re.compile(r"\b[a-z0-9_]*error=\"\"", re.I)
JOURNAL_LINE_RE = re.compile(r"^\[\s*(?P<time>\d+(?:\.\d+)?)\]\s+\S+\s+(?P<source>[^:]+):\s+(?P<message>.*)$")


def run_command(title: str, command: list[str], *, timeout: float) -> CommandResult:
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
        return CommandResult(
            title=title,
            command=command,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            elapsed_sec=time.monotonic() - started,
        )
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


def _monotonic_usec_to_sec(value: str) -> float | None:
    try:
        usec = int(value)
    except ValueError:
        return None
    if usec <= 0:
        return None
    return usec / 1_000_000.0


def parse_systemctl_show(unit: str, text: str) -> UnitMarker:
    props: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        props[key] = value
    return UnitMarker(
        unit=unit,
        active_state=props.get("ActiveState", ""),
        sub_state=props.get("SubState", ""),
        exec_start_sec=_monotonic_usec_to_sec(props.get("ExecMainStartTimestampMonotonic", "")),
        active_enter_sec=_monotonic_usec_to_sec(props.get("ActiveEnterTimestampMonotonic", "")),
    )


def parse_journal_line(line: str) -> tuple[float, str, str] | None:
    match = JOURNAL_LINE_RE.match(line)
    if not match:
        return None
    return (
        float(match.group("time")),
        match.group("source").strip(),
        match.group("message").strip(),
    )


def classify_journal_marker(line: str) -> TimelineMarker | None:
    parsed = parse_journal_line(line)
    if parsed is None:
        return None
    time_sec, source, message = parsed
    for rule in JOURNAL_RULES:
        if rule.source_pattern.search(source) and rule.message_pattern.search(message):
            return TimelineMarker(time_sec, rule.kind, rule.label, source, "known", message)
    if DISCOVERY_MESSAGE_PATTERN.search(message):
        message_for_warning = EMPTY_STATUS_ERROR_PATTERN.sub("", message)
        if "backend status" in message and not re.search(r"failed|error|timeout", message_for_warning, re.I):
            return None
        label = "discovered journal candidate"
        if re.search(r"failed|error|timeout", message_for_warning, re.I):
            label = "discovered warning candidate"
        return TimelineMarker(time_sec, "journal-discovered", label, source, "discovered", message)
    return None


def extract_journal_markers(text: str) -> list[TimelineMarker]:
    markers: list[TimelineMarker] = []
    seen: set[tuple[float, str, str, str]] = set()
    for line in text.splitlines():
        marker = classify_journal_marker(line)
        if marker is None:
            continue
        key = (marker.time_sec, marker.kind, marker.source, marker.message)
        if key in seen:
            continue
        seen.add(key)
        markers.append(marker)
    return sorted(markers, key=lambda marker: marker.time_sec)


def build_timeline(unit_markers: list[UnitMarker], results: list[CommandResult]) -> list[TimelineMarker]:
    timeline: list[TimelineMarker] = []
    seen: set[tuple[float, str, str, str]] = set()

    def append_marker(marker: TimelineMarker) -> None:
        key = (marker.time_sec, marker.kind, marker.source, marker.message)
        if key in seen:
            return
        seen.add(key)
        timeline.append(marker)

    for marker in unit_markers:
        if marker.active_enter_sec is None:
            continue
        append_marker(
            TimelineMarker(
                marker.active_enter_sec,
                "unit-active",
                f"{marker.unit} active",
                marker.unit,
                "systemd",
                f"ActiveState={marker.active_state} SubState={marker.sub_state}",
            )
        )
    for result in results:
        if result.title in ("boot journal markers", "boot journal marker candidates") and result.returncode == 0:
            for marker in extract_journal_markers(result.stdout):
                append_marker(marker)
    return sorted(timeline, key=lambda marker: marker.time_sec)


def collect_unit_markers(units: tuple[str, ...]) -> tuple[list[UnitMarker], list[CommandResult]]:
    markers: list[UnitMarker] = []
    results: list[CommandResult] = []
    for unit in units:
        result = run_command(
            f"systemd marker {unit}",
            [
                "systemctl",
                "show",
                unit,
                "-p",
                "ActiveState",
                "-p",
                "SubState",
                "-p",
                "ExecMainStartTimestampMonotonic",
                "-p",
                "ActiveEnterTimestampMonotonic",
                "--no-pager",
            ],
            timeout=5.0,
        )
        results.append(result)
        if result.returncode == 0:
            markers.append(parse_systemctl_show(unit, result.stdout))
    return markers, results


def snapshot_sockets(paths: tuple[str, ...] = DEFAULT_SOCKET_PATHS) -> list[SocketSnapshot]:
    snapshots: list[SocketSnapshot] = []
    for raw_path in paths:
        try:
            st = os.stat(raw_path)
            snapshots.append(
                SocketSnapshot(
                    path=raw_path,
                    exists=True,
                    is_socket=stat.S_ISSOCK(st.st_mode),
                    mode=f"{st.st_mode & 0o777:o}",
                    uid=st.st_uid,
                    gid=st.st_gid,
                    error="",
                )
            )
        except FileNotFoundError:
            snapshots.append(SocketSnapshot(raw_path, False, False, "", None, None, ""))
        except OSError as exc:
            snapshots.append(SocketSnapshot(raw_path, False, False, "", None, None, str(exc)))
    return snapshots


def _status_summary(value: object) -> str:
    if not isinstance(value, dict):
        return "json_root=non_object"
    parts: list[str] = []
    schema = value.get("schema")
    if isinstance(schema, str):
        parts.append(f"schema={schema}")
    if "process" in value:
        parts.append(f"process={value.get('process')}")
    socket_value = value.get("socket")
    if isinstance(socket_value, dict) and "listening" in socket_value:
        parts.append(f"socket.listening={socket_value.get('listening')}")
    if "output_enabled" in value:
        parts.append(f"output_enabled={value.get('output_enabled')}")
    state = value.get("state")
    if isinstance(state, dict):
        for key in ("pressed_matrix", "pressed_keys"):
            if key in state:
                parts.append(f"state.{key}={state.get(key)}")
    counters = value.get("counters")
    if isinstance(counters, dict):
        for key in ("frames_received", "report_previews", "broker_frames_sent", "write_errors", "dropped_reports"):
            if key in counters:
                parts.append(f"counters.{key}={counters.get(key)}")
    return ", ".join(parts) or "json_root=object"


def snapshot_status_files(paths: tuple[str, ...] = DEFAULT_STATUS_PATHS) -> list[StatusSnapshot]:
    snapshots: list[StatusSnapshot] = []
    for raw_path in paths:
        path = Path(raw_path)
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            snapshots.append(StatusSnapshot(raw_path, False, False, "", "", "", ""))
            continue
        except OSError as exc:
            snapshots.append(StatusSnapshot(raw_path, False, False, "", "", "", str(exc)))
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            snapshots.append(StatusSnapshot(raw_path, True, False, "", "", raw, str(exc)))
            continue
        schema = value.get("schema", "") if isinstance(value, dict) else ""
        snapshots.append(StatusSnapshot(raw_path, True, True, str(schema), _status_summary(value), raw, ""))
    return snapshots


def hidg_snapshot() -> str:
    paths = sorted(Path("/dev").glob("hidg*"))
    if not paths:
        return "(no /dev/hidg* devices)"
    lines: list[str] = []
    for path in paths:
        try:
            stat = path.stat()
            lines.append(f"{path} mode={stat.st_mode & 0o777:o} uid={stat.st_uid} gid={stat.st_gid}")
        except OSError as exc:
            lines.append(f"{path} stat_failed={exc}")
    return "\n".join(lines)


def collect_results(
    *, journal_lines: int, include_http_status: bool
) -> tuple[list[UnitMarker], list[SocketSnapshot], list[StatusSnapshot], list[CommandResult]]:
    units = DEFAULT_UNITS
    unit_markers, unit_results = collect_unit_markers(units)
    socket_snapshots = snapshot_sockets()
    status_snapshots = snapshot_status_files()
    unit_args = [part for unit in units for part in ("-u", unit)]
    results: list[CommandResult] = [
        run_command("kernel uptime", ["cat", "/proc/uptime"], timeout=2.0),
        run_command("system boot id", ["cat", "/proc/sys/kernel/random/boot_id"], timeout=2.0),
        run_command("system failed units", ["systemctl", "--failed", "--no-pager"], timeout=8.0),
        run_command(
            "boot journal marker candidates",
            [
                "journalctl",
                "-b",
                "--no-pager",
                "-o",
                "short-monotonic",
                *unit_args,
                "--grep",
                JOURNAL_GREP_PATTERN,
            ],
            timeout=20.0,
        ),
        run_command(
            "boot journal markers",
            ["journalctl", "-b", "--no-pager", "-o", "short-monotonic", *unit_args, "-n", str(journal_lines)],
            timeout=20.0,
        ),
        CommandResult("hidg devices", ["python", "glob:/dev/hidg*"], 0, hidg_snapshot(), "", 0.0),
    ]
    if include_http_status:
        results.append(
            run_command(
                "http status",
                [
                    "curl",
                    "-sk",
                    "-u",
                    f"admin:{socket.gethostname()}",
                    "https://127.0.0.1/api/status",
                ],
                timeout=8.0,
            )
        )
    results.extend(unit_results)
    return unit_markers, socket_snapshots, status_snapshots, results


def _format_sec(value: float | None) -> str:
    return "" if value is None else f"{value:.3f}"


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def fenced(text: str) -> str:
    return text.rstrip() if text.strip() else "(no output)"


def render_report(
    markers: list[UnitMarker],
    results: list[CommandResult],
    *,
    include_http_status: bool,
    sockets: list[SocketSnapshot] | None = None,
    statuses: list[StatusSnapshot] | None = None,
    timeline: list[TimelineMarker] | None = None,
    timeline_max_sec: float | None = 90.0,
) -> str:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    timeline = build_timeline(markers, results) if timeline is None else sorted(timeline, key=lambda item: item.time_sec)
    if timeline_max_sec is not None:
        timeline = [marker for marker in timeline if marker.time_sec <= timeline_max_sec]
    lines = [
        "# Boot Marker Baseline",
        "",
        f"- collected_at: `{now}`",
        f"- host: `{socket.gethostname()}`",
        f"- platform: `{platform.platform()}`",
        f"- http_status: `{'enabled' if include_http_status else 'skipped'}`",
        f"- timeline_max_sec: `{'all' if timeline_max_sec is None else f'{timeline_max_sec:.3f}'}`",
        "",
        "## Readiness Timeline",
        "",
        "| time_sec | delta_sec | kind | label | source | confidence | message |",
        "| ---: | ---: | --- | --- | --- | --- | --- |",
    ]
    previous_sec: float | None = None
    if timeline:
        for marker in timeline:
            delta = "" if previous_sec is None else f"{marker.time_sec - previous_sec:.3f}"
            previous_sec = marker.time_sec
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"{marker.time_sec:.3f}",
                        delta,
                        _escape_table(marker.kind),
                        _escape_table(marker.label),
                        _escape_table(marker.source),
                        _escape_table(marker.confidence),
                        _escape_table(marker.message),
                    ]
                )
                + " |"
            )
    else:
        lines.append("| (no timeline markers) | | | | | | |")
    lines.extend(
        [
            "",
            "## Systemd Unit Markers",
            "",
            "| unit | active | sub | exec_start_sec | active_enter_sec |",
            "| --- | --- | --- | ---: | ---: |",
        ]
    )
    if markers:
        for marker in markers:
            lines.append(
                "| "
                + " | ".join(
                    [
                        marker.unit,
                        marker.active_state,
                        marker.sub_state,
                        _format_sec(marker.exec_start_sec),
                        _format_sec(marker.active_enter_sec),
                    ]
                )
                + " |"
            )
    else:
        lines.append("| (no systemd markers) | | | | |")
    lines.extend(
        [
            "",
            "## Boot-Critical Socket Snapshots",
            "",
            "| path | exists | socket | mode | uid | gid | error |",
            "| --- | --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for snapshot in sockets or []:
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{snapshot.path}`",
                    str(snapshot.exists).lower(),
                    str(snapshot.is_socket).lower(),
                    snapshot.mode,
                    "" if snapshot.uid is None else str(snapshot.uid),
                    "" if snapshot.gid is None else str(snapshot.gid),
                    snapshot.error,
                ]
            )
            + " |"
        )
    if not sockets:
        lines.append("| (no socket snapshots) | | | | | | |")
    lines.extend(
        [
            "",
            "## Status Snapshots",
            "",
            "| path | exists | valid_json | schema | summary | error |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for snapshot in statuses or []:
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{snapshot.path}`",
                    str(snapshot.exists).lower(),
                    str(snapshot.valid_json).lower(),
                    snapshot.schema,
                    snapshot.summary,
                    snapshot.error,
                ]
            )
            + " |"
        )
    if not statuses:
        lines.append("| (no status snapshots) | | | | | |")
    for snapshot in statuses or []:
        if not snapshot.raw:
            continue
        lines.extend(
            [
                "",
                f"### {snapshot.path}",
                "",
                "```json",
                snapshot.raw.rstrip(),
                "```",
            ]
        )
    lines.extend(
        [
            "",
            "## Raw Command Results",
            "",
        ]
    )
    for result in results:
        command_text = " ".join(shlex.quote(part) for part in result.command)
        lines.extend(
            [
                f"### {result.title}",
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
    parser.add_argument("--output", type=Path, help="write Markdown report to this path")
    parser.add_argument("--journal-lines", type=int, default=240, help="journal lines to include")
    parser.add_argument(
        "--timeline-max-sec",
        type=float,
        default=90.0,
        help="hide timeline markers after this boot time; use 0 for all",
    )
    parser.add_argument("--no-http-status", action="store_true", help="skip HTTPS /api/status query")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.journal_lines < 1:
        raise SystemExit("--journal-lines must be >= 1")
    timeline_max_sec = None if args.timeline_max_sec == 0 else args.timeline_max_sec
    if timeline_max_sec is not None and timeline_max_sec < 0:
        raise SystemExit("--timeline-max-sec must be >= 0")
    include_http_status = not args.no_http_status
    markers, sockets, statuses, results = collect_results(
        journal_lines=args.journal_lines,
        include_http_status=include_http_status,
    )
    report = render_report(
        markers,
        results,
        include_http_status=include_http_status,
        sockets=sockets,
        statuses=statuses,
        timeline_max_sec=timeline_max_sec,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report + "\n", encoding="utf-8")
        print(args.output)
    else:
        print(report)


if __name__ == "__main__":
    main()
