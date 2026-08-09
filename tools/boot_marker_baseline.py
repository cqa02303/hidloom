#!/usr/bin/env python3
"""Collect boot-readiness markers for Raspberry Pi OS / Buildroot comparison."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
from dataclasses import dataclass, replace
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

DEFAULT_EARLY_RUNTIME_ROOT = Path("/run/hidloom-early")
DEFAULT_ACCEPTED_MANIFEST_PATH = Path(
    "/var/lib/hidloom/early-boot/early-image.accepted.json"
)
DEFAULT_INSTALL_RECEIPT_PATH = Path(
    "/var/lib/hidloom/early-boot/tryboot-install.json"
)
DEFAULT_CONFIGFS_GADGET_ROOT = Path("/sys/kernel/config/usb_gadget")
DEFAULT_SYS_CLASS_UDC_ROOT = Path("/sys/class/udc")
DEFAULT_GADGET_NAME = "cqa02303v5"
MAX_EARLY_TREE_ENTRIES = 64
MAX_EARLY_TREE_DEPTH = 2
MAX_EARLY_FILE_BYTES = 256 * 1024
MAX_EARLY_TOTAL_BYTES = 1024 * 1024
MAX_INSTALLED_EVIDENCE_BYTES = 2 * 1024 * 1024
MAX_EVIDENCE_PREVIEW_BYTES = 4096
MAX_PSEUDO_FILE_BYTES = 4096
EARLY_MARKER_SCHEMA = "hidloom.early-gadget-bound.v1"
ACCEPTED_EARLY_MANIFEST_SCHEMA = "hidloom.rpi-os-early-initramfs.e1.v1"


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


@dataclass(frozen=True)
class EvidenceSnapshot:
    label: str
    path: str
    exists: bool
    kind: str
    mode: str
    uid: int | None
    gid: int | None
    size: int | None
    sha256: str
    valid_json: bool | None
    schema: str
    summary: str
    details: dict[str, str]
    preview: str
    error: str


@dataclass(frozen=True)
class UdcSnapshot:
    gadget: str
    udc_path: str
    name: str
    state_path: str
    state: str
    bound: bool
    error: str


@dataclass(frozen=True)
class EarlyBootEvidence:
    runtime_root: str
    expected_kernel_release: str
    runtime_tree: list[EvidenceSnapshot]
    accepted_manifest: EvidenceSnapshot
    install_receipt: EvidenceSnapshot
    udc: UdcSnapshot


@dataclass(frozen=True)
class QueuedDirectory:
    path: Path
    relative_parts: tuple[str, ...]
    depth: int
    fd: int
    identity: tuple[int, int, int, int, int]


JOURNAL_RULES: tuple[JournalRule, ...] = (
    JournalRule(
        "early gadget adopted",
        "usb-adopt",
        re.compile(r"hidloom.*usb.*gadget|systemd", re.I),
        re.compile(r"Early USB gadget adopted without configfs mutation", re.I),
    ),
    JournalRule(
        "usb gadget configured",
        "usb-gadget",
        re.compile(r"setup_usb_gadget|hidloom.*usb.*gadget|systemd", re.I),
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
    "Early USB gadget adopted without configfs mutation|"
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


def build_timeline(
    unit_markers: list[UnitMarker],
    results: list[CommandResult],
    *,
    extra_markers: list[TimelineMarker] | None = None,
) -> list[TimelineMarker]:
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
    for marker in extra_markers or []:
        append_marker(marker)
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
        except (OSError, UnicodeError) as exc:
            snapshots.append(StatusSnapshot(raw_path, False, False, "", "", "", str(exc)))
            continue
        try:
            value = json.loads(raw)
        except (ValueError, RecursionError) as exc:
            snapshots.append(StatusSnapshot(raw_path, True, False, "", "", raw, str(exc)))
            continue
        schema = value.get("schema", "") if isinstance(value, dict) else ""
        snapshots.append(StatusSnapshot(raw_path, True, True, str(schema), _status_summary(value), raw, ""))
    return snapshots


def _path_kind(mode: int) -> str:
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISFIFO(mode):
        return "fifo"
    if stat.S_ISCHR(mode):
        return "character-device"
    if stat.S_ISBLK(mode):
        return "block-device"
    return "other"


def _empty_evidence(
    label: str,
    path: Path,
    *,
    exists: bool,
    kind: str = "missing",
    details: os.stat_result | None = None,
    error: str = "",
) -> EvidenceSnapshot:
    return EvidenceSnapshot(
        label=label,
        path=str(path),
        exists=exists,
        kind=kind,
        mode="" if details is None else f"{stat.S_IMODE(details.st_mode):04o}",
        uid=None if details is None else details.st_uid,
        gid=None if details is None else details.st_gid,
        size=None if details is None else details.st_size,
        sha256="",
        valid_json=None,
        schema="",
        summary="",
        details={},
        preview="",
        error=error,
    )


def _regular_identity(details: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        details.st_dev,
        details.st_ino,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
    )


def read_bounded_regular(path: Path, *, max_bytes: int) -> tuple[bytes, os.stat_result]:
    """Read a regular file without following its final symlink or trusting races."""
    if max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    before_path = path.lstat()
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise OSError(f"not a regular file: {path}")
        if before.st_size > max_bytes:
            raise OSError(
                f"file exceeds {max_bytes}-byte evidence bound: {before.st_size}"
            )
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(fd, min(64 * 1024, remaining))
            if not chunk:
                raise OSError(f"short read: {path}")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(fd, 1):
            raise OSError(f"file grew while being read: {path}")
        after = os.fstat(fd)
    finally:
        os.close(fd)
    after_path = path.lstat()
    identities = {
        _regular_identity(item) for item in (before_path, before, after, after_path)
    }
    if len(identities) != 1:
        raise OSError(f"file changed while being read: {path}")
    return b"".join(chunks), before


def _detail_text(value: object) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return str(value)
    return ""


def json_evidence_details(value: object) -> tuple[str, dict[str, str]]:
    if not isinstance(value, dict):
        return "", {}
    details: dict[str, str] = {}
    for key in (
        "state",
        "status",
        "source",
        "kernel_release",
        "ready_uptime_seconds",
        "runtime_contract_sha256",
        "placement_sha256",
    ):
        text = _detail_text(value.get(key))
        if text:
            details[key] = text
    profile = value.get("profile")
    if isinstance(profile, dict):
        profile_id = _detail_text(profile.get("id"))
        if profile_id:
            details["profile"] = profile_id
    activation = value.get("activation")
    if isinstance(activation, dict):
        activation_parts: list[str] = []
        for key in (
            "default_boot_modified",
            "one_shot_requested",
            "reboot_requested",
            "tryboot_published_last",
        ):
            if key in activation:
                activation_parts.append(f"{key}={_detail_text(activation.get(key))}")
        if activation_parts:
            details["activation"] = ",".join(activation_parts)
    adopt = value.get("adopt")
    if isinstance(adopt, dict):
        packages = adopt.get("packages")
        if isinstance(packages, dict):
            package_parts: list[str] = []
            for key in sorted(packages):
                record = packages.get(key)
                if not isinstance(record, dict):
                    continue
                name = _detail_text(record.get("name"))
                version = _detail_text(record.get("version"))
                if name or version:
                    package_parts.append(f"{key}:{name}={version}")
            if package_parts:
                details["packages"] = ",".join(package_parts)
    runtime_contract = value.get("runtime_contract")
    if isinstance(runtime_contract, dict):
        contract_sha = _detail_text(runtime_contract.get("sha256"))
        if contract_sha:
            details["accepted_runtime_contract_sha256"] = contract_sha
    schema = _detail_text(value.get("schema"))
    return schema, details | ({"schema": schema} if schema else {})


def snapshot_evidence_file(
    path: Path,
    label: str,
    *,
    max_bytes: int,
    include_preview: bool,
) -> EvidenceSnapshot:
    try:
        path_details = path.lstat()
    except FileNotFoundError:
        return _empty_evidence(label, path, exists=False)
    except OSError as exc:
        return _empty_evidence(label, path, exists=False, error=str(exc))
    kind = _path_kind(path_details.st_mode)
    if kind != "file":
        return _empty_evidence(
            label,
            path,
            exists=True,
            kind=kind,
            details=path_details,
            error="not read; evidence files must be regular files",
        )
    try:
        raw, details = read_bounded_regular(path, max_bytes=max_bytes)
    except (OSError, ValueError) as exc:
        return _empty_evidence(
            label,
            path,
            exists=True,
            kind=kind,
            details=path_details,
            error=str(exc),
        )
    return _snapshot_evidence_bytes(
        path,
        label,
        raw,
        details,
        include_preview=include_preview,
    )


def _snapshot_evidence_bytes(
    path: Path,
    label: str,
    raw: bytes,
    details: os.stat_result,
    *,
    include_preview: bool,
) -> EvidenceSnapshot:
    kind = _path_kind(details.st_mode)
    digest = hashlib.sha256(raw).hexdigest()
    valid_json: bool | None = None
    schema = ""
    summary = ""
    json_details: dict[str, str] = {}
    evidence_error = ""
    if path.suffix.lower() == ".json":
        try:
            value = json.loads(raw)
            valid_json = True
            schema, json_details = json_evidence_details(value)
            summary = ", ".join(
                f"{key}={item}"
                for key, item in json_details.items()
                if key != "schema"
            )
        except (UnicodeError, ValueError, RecursionError) as exc:
            valid_json = False
            summary = f"invalid JSON: {exc}"
            evidence_error = summary
    preview = ""
    if include_preview:
        preview_raw = raw[:MAX_EVIDENCE_PREVIEW_BYTES]
        if b"\x00" in preview_raw:
            preview = "(binary content omitted)"
        else:
            preview = preview_raw.decode("utf-8", errors="replace")
            if len(raw) > len(preview_raw):
                preview += "\n... (preview truncated)"
    return EvidenceSnapshot(
        label=label,
        path=str(path),
        exists=True,
        kind=kind,
        mode=f"{stat.S_IMODE(details.st_mode):04o}",
        uid=details.st_uid,
        gid=details.st_gid,
        size=len(raw),
        sha256=digest,
        valid_json=valid_json,
        schema=schema,
        summary=summary,
        details=json_details,
        preview=preview,
        error=evidence_error,
    )


def read_bounded_regular_at(
    directory_fd: int,
    name: str,
    display_path: Path,
    expected: os.stat_result,
    *,
    max_bytes: int,
) -> tuple[bytes, os.stat_result]:
    if max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    if not name or name in {".", ".."} or "/" in name:
        raise OSError(f"unsafe evidence filename: {name!r}")
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(name, flags, dir_fd=directory_fd)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise OSError(f"not a regular file: {display_path}")
        if before.st_size > max_bytes:
            raise OSError(
                f"file exceeds {max_bytes}-byte evidence bound: {before.st_size}"
            )
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(fd, min(64 * 1024, remaining))
            if not chunk:
                raise OSError(f"short read: {display_path}")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(fd, 1):
            raise OSError(f"file grew while being read: {display_path}")
        after = os.fstat(fd)
    finally:
        os.close(fd)
    after_path = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    identities = {
        _regular_identity(item) for item in (expected, before, after, after_path)
    }
    if len(identities) != 1:
        raise OSError(f"file changed while being read: {display_path}")
    return b"".join(chunks), before


def _directory_identity(
    details: os.stat_result,
) -> tuple[int, int, int, int, int]:
    return (
        details.st_dev,
        details.st_ino,
        stat.S_IFMT(details.st_mode),
        details.st_uid,
        details.st_gid,
    )


def _directory_open_flags() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return flags


def _open_relative_directory(root_fd: int, parts: tuple[str, ...]) -> int:
    current = os.dup(root_fd)
    try:
        for part in parts:
            if not part or part in {".", ".."} or "/" in part:
                raise OSError(f"unsafe runtime directory component: {part!r}")
            next_fd = os.open(
                part,
                _directory_open_flags(),
                dir_fd=current,
            )
            os.close(current)
            current = next_fd
        return current
    except BaseException:
        os.close(current)
        raise


def verify_queued_directory(root_fd: int, queued: QueuedDirectory) -> str:
    try:
        if _directory_identity(os.fstat(queued.fd)) != queued.identity:
            return "queued directory descriptor identity changed"
        current_fd = _open_relative_directory(root_fd, queued.relative_parts)
        try:
            if _directory_identity(os.fstat(current_fd)) != queued.identity:
                return "queued directory path identity changed"
        finally:
            os.close(current_fd)
    except OSError as exc:
        return f"queued directory path is no longer safe: {exc}"
    return ""


def snapshot_early_runtime_tree(
    root: Path = DEFAULT_EARLY_RUNTIME_ROOT,
    *,
    max_entries: int = MAX_EARLY_TREE_ENTRIES,
    max_depth: int = MAX_EARLY_TREE_DEPTH,
    max_file_bytes: int = MAX_EARLY_FILE_BYTES,
    max_total_bytes: int = MAX_EARLY_TOTAL_BYTES,
) -> list[EvidenceSnapshot]:
    """Snapshot a bounded runtime tree through pinned, no-follow descriptors."""
    if max_entries < 1 or max_depth < 0 or max_file_bytes < 0 or max_total_bytes < 0:
        raise ValueError("early runtime tree bounds are invalid")
    try:
        root_details = root.lstat()
    except FileNotFoundError:
        return [_empty_evidence("early runtime root", root, exists=False)]
    except OSError as exc:
        return [
            _empty_evidence("early runtime root", root, exists=False, error=str(exc))
        ]
    root_kind = _path_kind(root_details.st_mode)
    root_snapshot = _empty_evidence(
        "early runtime root",
        root,
        exists=True,
        kind=root_kind,
        details=root_details,
        error="" if root_kind == "directory" else "runtime root is not a directory",
    )
    snapshots = [root_snapshot]
    if root_kind != "directory":
        return snapshots
    try:
        root_fd = os.open(root, _directory_open_flags())
    except OSError as exc:
        snapshots[0] = replace(root_snapshot, error=f"cannot open runtime root: {exc}")
        return snapshots
    root_identity = _directory_identity(root_details)
    if _directory_identity(os.fstat(root_fd)) != root_identity:
        os.close(root_fd)
        snapshots[0] = replace(root_snapshot, error="runtime root identity changed")
        return snapshots
    pending = [
        QueuedDirectory(
            path=root,
            relative_parts=(),
            depth=0,
            fd=os.dup(root_fd),
            identity=root_identity,
        )
    ]
    total_bytes = 0
    enumerated_entries = 0
    try:
        while pending:
            queued = pending.pop(0)
            try:
                queue_error = verify_queued_directory(root_fd, queued)
                if queue_error:
                    snapshots.append(
                        _empty_evidence(
                            f"early runtime {queued.path.relative_to(root)}",
                            queued.path,
                            exists=False,
                            kind="directory",
                            error=queue_error,
                        )
                    )
                    continue
                remaining_entries = max_entries - enumerated_entries
                names: list[str] = []
                with os.scandir(queued.fd) as iterator:
                    for _ in range(remaining_entries + 1):
                        try:
                            entry = next(iterator)
                        except StopIteration:
                            break
                        names.append(entry.name)
                overflow = len(names) > remaining_entries
                for name in sorted(names[:remaining_entries]):
                    enumerated_entries += 1
                    relative_parts = queued.relative_parts + (name,)
                    child = root.joinpath(*relative_parts)
                    label = f"early runtime {child.relative_to(root)}"
                    try:
                        child_details = os.stat(
                            name,
                            dir_fd=queued.fd,
                            follow_symlinks=False,
                        )
                    except OSError as exc:
                        snapshots.append(
                            _empty_evidence(
                                label,
                                child,
                                exists=False,
                                error=str(exc),
                            )
                        )
                        continue
                    child_kind = _path_kind(child_details.st_mode)
                    if child_kind == "file":
                        if total_bytes + child_details.st_size > max_total_bytes:
                            snapshots.append(
                                _empty_evidence(
                                    label,
                                    child,
                                    exists=True,
                                    kind=child_kind,
                                    details=child_details,
                                    error=(
                                        f"tree exceeds {max_total_bytes}-byte evidence bound"
                                    ),
                                )
                            )
                            continue
                        try:
                            raw, opened_details = read_bounded_regular_at(
                                queued.fd,
                                name,
                                child,
                                child_details,
                                max_bytes=max_file_bytes,
                            )
                            snapshot = _snapshot_evidence_bytes(
                                child,
                                label,
                                raw,
                                opened_details,
                                include_preview=True,
                            )
                        except (OSError, ValueError) as exc:
                            snapshot = _empty_evidence(
                                label,
                                child,
                                exists=True,
                                kind=child_kind,
                                details=child_details,
                                error=str(exc),
                            )
                        snapshots.append(snapshot)
                        if snapshot.size is not None and snapshot.sha256:
                            total_bytes += snapshot.size
                    else:
                        child_error = ""
                        if child_kind == "symlink":
                            child_error = "symlink not followed"
                        snapshots.append(
                            _empty_evidence(
                                label,
                                child,
                                exists=True,
                                kind=child_kind,
                                details=child_details,
                                error=child_error,
                            )
                        )
                        if child_kind == "directory" and queued.depth + 1 < max_depth:
                            try:
                                child_fd = os.open(
                                    name,
                                    _directory_open_flags(),
                                    dir_fd=queued.fd,
                                )
                                opened_identity = _directory_identity(os.fstat(child_fd))
                                if opened_identity != _directory_identity(child_details):
                                    os.close(child_fd)
                                    raise OSError("directory changed while being opened")
                                pending.append(
                                    QueuedDirectory(
                                        path=child,
                                        relative_parts=relative_parts,
                                        depth=queued.depth + 1,
                                        fd=child_fd,
                                        identity=opened_identity,
                                    )
                                )
                            except OSError as exc:
                                snapshots[-1] = replace(
                                    snapshots[-1],
                                    error=f"cannot queue directory safely: {exc}",
                                )
                if overflow:
                    snapshots.append(
                        _empty_evidence(
                            "early runtime tree bound",
                            root,
                            exists=True,
                            kind="boundary",
                            error=f"tree exceeds {max_entries}-entry evidence bound",
                        )
                    )
                    return snapshots
            except OSError as exc:
                snapshots.append(
                    _empty_evidence(
                        "early runtime enumeration",
                        queued.path,
                        exists=True,
                        kind="directory",
                        error=str(exc),
                    )
                )
            finally:
                os.close(queued.fd)
        return snapshots
    finally:
        for queued in pending:
            os.close(queued.fd)
        os.close(root_fd)


def read_bounded_pseudo_text(path: Path, *, max_bytes: int) -> str:
    """Read a small procfs/sysfs/configfs attribute twice without following it."""
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    def read_once() -> tuple[bytes, tuple[int, ...]]:
        before_path = path.lstat()
        fd = os.open(path, flags)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                raise OSError(f"not a regular pseudo-file: {path}")
            output = bytearray()
            while True:
                chunk = os.read(fd, min(4096, max_bytes + 1 - len(output)))
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > max_bytes:
                    raise OSError(f"pseudo-file exceeds {max_bytes}-byte bound: {path}")
            after = os.fstat(fd)
        finally:
            os.close(fd)
        after_path = path.lstat()
        path_contracts = {
            (
                item.st_dev,
                stat.S_IFMT(item.st_mode),
                item.st_uid,
                item.st_gid,
                item.st_size,
                item.st_mtime_ns,
                item.st_ctime_ns,
            )
            for item in (before_path, after_path)
        }
        fd_identities = {
            (
                item.st_dev,
                item.st_ino,
                stat.S_IFMT(item.st_mode),
                item.st_uid,
                item.st_gid,
                item.st_size,
                item.st_mtime_ns,
                item.st_ctime_ns,
            )
            for item in (before, after)
        }
        if len(path_contracts) != 1 or len(fd_identities) != 1:
            raise OSError(f"pseudo-file changed while being read: {path}")
        path_contract = path_contracts.pop()
        fd_identity = fd_identities.pop()
        if path_contract != (
            fd_identity[0],
            *fd_identity[2:],
        ):
            raise OSError(f"pseudo-file path/open contract mismatch: {path}")
        return bytes(output), path_contract

    first, first_identity = read_once()
    second, second_identity = read_once()
    if first_identity != second_identity or first != second:
        raise OSError(f"pseudo-file was unstable across reads: {path}")
    if b"\x00" in first:
        raise OSError(f"pseudo-file contains NUL: {path}")
    return first.decode("utf-8").strip()


def snapshot_udc(
    *,
    configfs_root: Path = DEFAULT_CONFIGFS_GADGET_ROOT,
    sys_class_udc_root: Path = DEFAULT_SYS_CLASS_UDC_ROOT,
    gadget_name: str = DEFAULT_GADGET_NAME,
) -> UdcSnapshot:
    if not gadget_name or gadget_name in {".", ".."} or "/" in gadget_name:
        return UdcSnapshot(
            gadget_name,
            "",
            "",
            "",
            "",
            False,
            "invalid gadget name",
        )
    udc_path = configfs_root / gadget_name / "UDC"
    try:
        name = read_bounded_pseudo_text(udc_path, max_bytes=MAX_PSEUDO_FILE_BYTES)
    except FileNotFoundError:
        return UdcSnapshot(
            gadget_name,
            str(udc_path),
            "",
            "",
            "missing",
            False,
            "gadget UDC attribute is missing",
        )
    except (OSError, UnicodeError, ValueError) as exc:
        return UdcSnapshot(
            gadget_name,
            str(udc_path),
            "",
            "",
            "error",
            False,
            str(exc),
        )
    if not name:
        return UdcSnapshot(
            gadget_name,
            str(udc_path),
            "",
            "",
            "unbound",
            False,
            "",
        )
    if name in {".", ".."} or "/" in name:
        return UdcSnapshot(
            gadget_name,
            str(udc_path),
            name,
            "",
            "error",
            True,
            "UDC name is not a safe basename",
        )
    state_path = sys_class_udc_root / name / "state"
    try:
        state = read_bounded_pseudo_text(
            state_path, max_bytes=MAX_PSEUDO_FILE_BYTES
        )
    except (OSError, UnicodeError, ValueError) as exc:
        return UdcSnapshot(
            gadget_name,
            str(udc_path),
            name,
            str(state_path),
            "unknown",
            True,
            str(exc),
        )
    return UdcSnapshot(
        gadget_name,
        str(udc_path),
        name,
        str(state_path),
        state or "unknown",
        True,
        "",
    )


def _validated_early_marker(
    snapshot: EvidenceSnapshot,
    *,
    runtime_root: Path,
    expected_kernel_release: str,
    expected_runtime_contract_sha256: str,
) -> tuple[TimelineMarker | None, str]:
    canonical_path = runtime_root / "gadget-bound.json"
    if Path(snapshot.path) != canonical_path:
        return None, (
            "non-canonical gadget-bound.json ignored; expected "
            f"{canonical_path}"
        )
    if not snapshot.exists or snapshot.kind != "file":
        return None, "canonical early marker is not a regular file"
    if snapshot.valid_json is not True:
        return None, snapshot.error or "canonical early marker is not valid JSON"
    if snapshot.size is None or snapshot.size > MAX_EVIDENCE_PREVIEW_BYTES:
        return None, (
            "canonical early marker cannot be validated within the "
            f"{MAX_EVIDENCE_PREVIEW_BYTES}-byte preview bound"
        )
    try:
        value = json.loads(snapshot.preview)
    except (UnicodeError, ValueError, RecursionError) as exc:
        return None, f"canonical early marker JSON validation failed: {exc}"
    if not isinstance(value, dict):
        return None, "canonical early marker JSON root must be an object"
    if value.get("schema") != EARLY_MARKER_SCHEMA:
        return None, (
            "canonical early marker schema mismatch: "
            f"expected {EARLY_MARKER_SCHEMA}"
        )
    if value.get("state") != "bound":
        return None, "canonical early marker state must be bound"
    raw_uptime = value.get("ready_uptime_seconds")
    if isinstance(raw_uptime, bool) or not isinstance(raw_uptime, (int, float)):
        return None, "canonical early marker ready_uptime_seconds must be numeric"
    try:
        uptime = float(raw_uptime)
    except (TypeError, ValueError, OverflowError) as exc:
        return None, f"canonical early marker uptime is invalid: {exc}"
    if not math.isfinite(uptime) or uptime < 0:
        return None, (
            "canonical early marker ready_uptime_seconds must be finite and "
            "non-negative"
        )
    contract = value.get("runtime_contract_sha256")
    if not isinstance(contract, str) or re.fullmatch(r"[0-9a-fA-F]{64}", contract) is None:
        return None, (
            "canonical early marker runtime_contract_sha256 must be exactly "
            "64 hexadecimal characters"
        )
    if (
        re.fullmatch(r"[0-9a-fA-F]{64}", expected_runtime_contract_sha256)
        is None
    ):
        return None, (
            "accepted manifest does not provide a trusted runtime contract SHA-256"
        )
    if contract.lower() != expected_runtime_contract_sha256.lower():
        return None, (
            "canonical early marker runtime_contract_sha256 mismatch with "
            "accepted manifest"
        )
    kernel = value.get("kernel_release")
    if not isinstance(kernel, str) or kernel != expected_kernel_release:
        return None, (
            "canonical early marker kernel_release mismatch: "
            f"expected {expected_kernel_release}"
        )
    return (
        TimelineMarker(
            uptime,
            "early-usb-ready",
            "early gadget bound",
            snapshot.path,
            "runtime-marker",
            f"state=bound kernel_release={kernel}",
        ),
        "",
    )


def trusted_accepted_runtime_contract(snapshot: EvidenceSnapshot) -> str:
    if (
        not snapshot.exists
        or snapshot.kind != "file"
        or snapshot.valid_json is not True
        or snapshot.schema != ACCEPTED_EARLY_MANIFEST_SCHEMA
        or snapshot.error
    ):
        return ""
    contract = snapshot.details.get("accepted_runtime_contract_sha256", "")
    return contract if re.fullmatch(r"[0-9a-fA-F]{64}", contract) else ""


def validate_early_runtime_tree(
    snapshots: list[EvidenceSnapshot],
    *,
    runtime_root: Path,
    expected_kernel_release: str,
    expected_runtime_contract_sha256: str,
) -> list[EvidenceSnapshot]:
    """Annotate marker-shaped rows that cannot be trusted as boot evidence."""
    validated: list[EvidenceSnapshot] = []
    for snapshot in snapshots:
        if Path(snapshot.path).name != "gadget-bound.json":
            validated.append(snapshot)
            continue
        _, marker_error = _validated_early_marker(
            snapshot,
            runtime_root=runtime_root,
            expected_kernel_release=expected_kernel_release,
            expected_runtime_contract_sha256=expected_runtime_contract_sha256,
        )
        if marker_error:
            combined = (
                f"{snapshot.error}; {marker_error}"
                if snapshot.error and marker_error not in snapshot.error
                else snapshot.error or marker_error
            )
            snapshot = replace(snapshot, error=combined)
        validated.append(snapshot)
    return validated


def early_timeline_markers(evidence: EarlyBootEvidence) -> list[TimelineMarker]:
    canonical_path = Path(evidence.runtime_root) / "gadget-bound.json"
    for snapshot in evidence.runtime_tree:
        if Path(snapshot.path) != canonical_path:
            continue
        marker, _ = _validated_early_marker(
            snapshot,
            runtime_root=Path(evidence.runtime_root),
            expected_kernel_release=evidence.expected_kernel_release,
            expected_runtime_contract_sha256=trusted_accepted_runtime_contract(
                evidence.accepted_manifest
            ),
        )
        return [] if marker is None else [marker]
    return []


def collect_early_boot_evidence(
    *,
    runtime_root: Path = DEFAULT_EARLY_RUNTIME_ROOT,
    accepted_manifest_path: Path = DEFAULT_ACCEPTED_MANIFEST_PATH,
    install_receipt_path: Path = DEFAULT_INSTALL_RECEIPT_PATH,
    configfs_root: Path = DEFAULT_CONFIGFS_GADGET_ROOT,
    sys_class_udc_root: Path = DEFAULT_SYS_CLASS_UDC_ROOT,
    gadget_name: str = DEFAULT_GADGET_NAME,
    expected_kernel_release: str | None = None,
) -> EarlyBootEvidence:
    expected_kernel = expected_kernel_release or platform.release()
    accepted_manifest = snapshot_evidence_file(
        accepted_manifest_path,
        "accepted early image manifest",
        max_bytes=MAX_INSTALLED_EVIDENCE_BYTES,
        include_preview=False,
    )
    runtime_tree = validate_early_runtime_tree(
        snapshot_early_runtime_tree(runtime_root),
        runtime_root=runtime_root,
        expected_kernel_release=expected_kernel,
        expected_runtime_contract_sha256=trusted_accepted_runtime_contract(
            accepted_manifest
        ),
    )
    return EarlyBootEvidence(
        runtime_root=str(runtime_root),
        expected_kernel_release=expected_kernel,
        runtime_tree=runtime_tree,
        accepted_manifest=accepted_manifest,
        install_receipt=snapshot_evidence_file(
            install_receipt_path,
            "tryboot install receipt",
            max_bytes=MAX_INSTALLED_EVIDENCE_BYTES,
            include_preview=False,
        ),
        udc=snapshot_udc(
            configfs_root=configfs_root,
            sys_class_udc_root=sys_class_udc_root,
            gadget_name=gadget_name,
        ),
    )


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
    *,
    journal_lines: int,
    include_http_status: bool,
    early_runtime_root: Path = DEFAULT_EARLY_RUNTIME_ROOT,
    accepted_manifest_path: Path = DEFAULT_ACCEPTED_MANIFEST_PATH,
    install_receipt_path: Path = DEFAULT_INSTALL_RECEIPT_PATH,
    configfs_root: Path = DEFAULT_CONFIGFS_GADGET_ROOT,
    sys_class_udc_root: Path = DEFAULT_SYS_CLASS_UDC_ROOT,
    gadget_name: str = DEFAULT_GADGET_NAME,
    expected_kernel_release: str | None = None,
) -> tuple[
    list[UnitMarker],
    list[SocketSnapshot],
    list[StatusSnapshot],
    list[CommandResult],
    EarlyBootEvidence,
]:
    units = DEFAULT_UNITS
    unit_markers, unit_results = collect_unit_markers(units)
    socket_snapshots = snapshot_sockets()
    status_snapshots = snapshot_status_files()
    early_evidence = collect_early_boot_evidence(
        runtime_root=early_runtime_root,
        accepted_manifest_path=accepted_manifest_path,
        install_receipt_path=install_receipt_path,
        configfs_root=configfs_root,
        sys_class_udc_root=sys_class_udc_root,
        gadget_name=gadget_name,
        expected_kernel_release=expected_kernel_release,
    )
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
    return unit_markers, socket_snapshots, status_snapshots, results, early_evidence


def _format_sec(value: float | None) -> str:
    return "" if value is None else f"{value:.3f}"


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def fenced(text: str) -> str:
    return text.rstrip() if text.strip() else "(no output)"


def _metadata_value(value: str) -> str:
    return value.replace("`", "'").replace("\r", " ").replace("\n", " ")


def early_evidence_metadata(evidence: EarlyBootEvidence) -> dict[str, str]:
    root = evidence.runtime_tree[0] if evidence.runtime_tree else None
    if root is None or not root.exists:
        runtime_state = "absent"
    elif root.error:
        runtime_state = "error"
    else:
        runtime_state = "present"
    ready = early_timeline_markers(evidence)
    ready_uptime = f"{ready[0].time_sec:.6f}" if ready else "(missing)"
    accepted = evidence.accepted_manifest
    receipt = evidence.install_receipt
    accepted_sha = (
        accepted.sha256
        if accepted.sha256
        else ("(error)" if accepted.error else "(missing)")
    )
    receipt_sha = (
        receipt.sha256
        if receipt.sha256
        else ("(error)" if receipt.error else "(missing)")
    )
    return {
        "early_runtime_tree": runtime_state,
        "early_ready_uptime_seconds": ready_uptime,
        "gadget_udc_name": evidence.udc.name or "(unbound)",
        "gadget_udc_state": evidence.udc.state or "(unknown)",
        "accepted_manifest_sha256": accepted_sha,
        "accepted_runtime_contract_sha256": (
            trusted_accepted_runtime_contract(accepted) or "(missing)"
        ),
        "tryboot_receipt_sha256": receipt_sha,
        "tryboot_activation": receipt.details.get("activation", "(missing)"),
    }


def render_evidence_table(snapshots: list[EvidenceSnapshot]) -> list[str]:
    lines = [
        "| label | path | exists | kind | mode | uid | gid | size | sha256 | json | schema | summary | error |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- |",
    ]
    for snapshot in snapshots:
        valid_json = "" if snapshot.valid_json is None else str(snapshot.valid_json).lower()
        lines.append(
            "| "
            + " | ".join(
                [
                    _escape_table(snapshot.label),
                    f"`{_escape_table(snapshot.path)}`",
                    str(snapshot.exists).lower(),
                    snapshot.kind,
                    snapshot.mode,
                    "" if snapshot.uid is None else str(snapshot.uid),
                    "" if snapshot.gid is None else str(snapshot.gid),
                    "" if snapshot.size is None else str(snapshot.size),
                    snapshot.sha256,
                    valid_json,
                    _escape_table(snapshot.schema),
                    _escape_table(snapshot.summary),
                    _escape_table(snapshot.error),
                ]
            )
            + " |"
        )
    return lines


def render_report(
    markers: list[UnitMarker],
    results: list[CommandResult],
    *,
    include_http_status: bool,
    sockets: list[SocketSnapshot] | None = None,
    statuses: list[StatusSnapshot] | None = None,
    early_evidence: EarlyBootEvidence | None = None,
    timeline: list[TimelineMarker] | None = None,
    timeline_max_sec: float | None = 90.0,
) -> str:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if early_evidence is None:
        early_evidence = EarlyBootEvidence(
            runtime_root=str(DEFAULT_EARLY_RUNTIME_ROOT),
            expected_kernel_release=platform.release(),
            runtime_tree=[],
            accepted_manifest=_empty_evidence(
                "accepted early image manifest",
                DEFAULT_ACCEPTED_MANIFEST_PATH,
                exists=False,
            ),
            install_receipt=_empty_evidence(
                "tryboot install receipt",
                DEFAULT_INSTALL_RECEIPT_PATH,
                exists=False,
            ),
            udc=UdcSnapshot(
                DEFAULT_GADGET_NAME,
                str(DEFAULT_CONFIGFS_GADGET_ROOT / DEFAULT_GADGET_NAME / "UDC"),
                "",
                "",
                "missing",
                False,
                "not collected",
            ),
        )
    metadata = early_evidence_metadata(early_evidence)
    timeline = (
        build_timeline(
            markers,
            results,
            extra_markers=early_timeline_markers(early_evidence),
        )
        if timeline is None
        else sorted(timeline, key=lambda item: item.time_sec)
    )
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
        *[
            f"- {key}: `{_metadata_value(value)}`"
            for key, value in metadata.items()
        ],
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
            "## Early Runtime Tree",
            "",
            *render_evidence_table(early_evidence.runtime_tree),
        ]
    )
    for snapshot in early_evidence.runtime_tree:
        if not snapshot.preview:
            continue
        lines.extend(
            [
                "",
                f"### {_escape_table(snapshot.path)}",
                "",
                "```text",
                fenced(snapshot.preview),
                "```",
            ]
        )
    lines.extend(
        [
            "",
            "## USB Device Controller Snapshot",
            "",
            f"- gadget: `{_metadata_value(early_evidence.udc.gadget)}`",
            f"- udc_path: `{_metadata_value(early_evidence.udc.udc_path)}`",
            f"- name: `{_metadata_value(early_evidence.udc.name or '(unbound)')}`",
            f"- state_path: `{_metadata_value(early_evidence.udc.state_path or '(none)')}`",
            f"- state: `{_metadata_value(early_evidence.udc.state)}`",
            f"- bound: `{str(early_evidence.udc.bound).lower()}`",
            f"- error: `{_metadata_value(early_evidence.udc.error or '(none)')}`",
            "",
            "## Installed E2 Evidence",
            "",
            *render_evidence_table(
                [
                    early_evidence.accepted_manifest,
                    early_evidence.install_receipt,
                ]
            ),
        ]
    )
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
    parser.add_argument(
        "--early-runtime-root",
        type=Path,
        default=DEFAULT_EARLY_RUNTIME_ROOT,
        help="ephemeral early-initramfs runtime tree to snapshot read-only",
    )
    parser.add_argument(
        "--accepted-manifest",
        type=Path,
        default=DEFAULT_ACCEPTED_MANIFEST_PATH,
        help="installed accepted E1 manifest to hash and summarize",
    )
    parser.add_argument(
        "--tryboot-install-receipt",
        type=Path,
        default=DEFAULT_INSTALL_RECEIPT_PATH,
        help="installed disabled-placement receipt to hash and summarize",
    )
    parser.add_argument(
        "--configfs-gadget-root",
        type=Path,
        default=DEFAULT_CONFIGFS_GADGET_ROOT,
        help="configfs USB gadget root used for the read-only UDC snapshot",
    )
    parser.add_argument(
        "--sys-class-udc-root",
        type=Path,
        default=DEFAULT_SYS_CLASS_UDC_ROOT,
        help="sysfs UDC class root used for the read-only link-state snapshot",
    )
    parser.add_argument(
        "--gadget-name",
        default=DEFAULT_GADGET_NAME,
        help="configfs gadget name used for the read-only UDC snapshot",
    )
    parser.add_argument(
        "--expected-kernel-release",
        default=platform.release(),
        help="kernel release required in the canonical early runtime marker",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.journal_lines < 1:
        raise SystemExit("--journal-lines must be >= 1")
    timeline_max_sec = None if args.timeline_max_sec == 0 else args.timeline_max_sec
    if timeline_max_sec is not None and timeline_max_sec < 0:
        raise SystemExit("--timeline-max-sec must be >= 0")
    include_http_status = not args.no_http_status
    markers, sockets, statuses, results, early_evidence = collect_results(
        journal_lines=args.journal_lines,
        include_http_status=include_http_status,
        early_runtime_root=args.early_runtime_root,
        accepted_manifest_path=args.accepted_manifest,
        install_receipt_path=args.tryboot_install_receipt,
        configfs_root=args.configfs_gadget_root,
        sys_class_udc_root=args.sys_class_udc_root,
        gadget_name=args.gadget_name,
        expected_kernel_release=args.expected_kernel_release,
    )
    report = render_report(
        markers,
        results,
        include_http_status=include_http_status,
        sockets=sockets,
        statuses=statuses,
        early_evidence=early_evidence,
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
