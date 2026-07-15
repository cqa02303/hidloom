#!/usr/bin/env python3
"""Collect repeatable remote boot baseline artifacts over SSH."""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import shlex
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
BOOT_HELPER = ROOT / "tools" / "boot_marker_baseline.py"
DEFAULT_OUTPUT_ROOT = ROOT / "build" / "artifacts"


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    elapsed_sec: float


def run_with_input(command: list[str], stdin: str, *, timeout: float) -> CommandResult:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            input=stdin,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return CommandResult(command, proc.returncode, proc.stdout, proc.stderr, time.monotonic() - started)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return CommandResult(
            command,
            124,
            stdout,
            stderr + f"\nTIMEOUT after {timeout:.1f}s",
            time.monotonic() - started,
        )


def safe_name(value: str) -> str:
    chars = [ch if ch.isalnum() or ch in (".", "-", "_") else "_" for ch in value]
    safe = "".join(chars).strip("._-")
    return safe or "remote"


def run(command: list[str], *, timeout: float) -> CommandResult:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return CommandResult(command, proc.returncode, proc.stdout, proc.stderr, time.monotonic() - started)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return CommandResult(
            command,
            124,
            stdout,
            stderr + f"\nTIMEOUT after {timeout:.1f}s",
            time.monotonic() - started,
        )


def require_ok(result: CommandResult) -> None:
    if result.returncode == 0:
        return
    command_text = " ".join(shlex.quote(part) for part in result.command)
    raise SystemExit(
        f"command failed ({result.returncode}): {command_text}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def require_ssh_transport(target: str, *, connect_timeout: int) -> None:
    result = run(ssh_command(target, "true", connect_timeout=connect_timeout), timeout=connect_timeout + 2.0)
    if result.returncode == 0:
        return
    command_text = " ".join(shlex.quote(part) for part in result.command)
    raise SystemExit(
        "SSH transport preflight failed before collecting remote boot markers.\n"
        f"python: {sys.executable}\n"
        f"command: {command_text}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}\n"
        "If plain PowerShell ssh works but this fails, run the collector from a Python environment "
        "whose subprocess ssh uses the same Windows OpenSSH context, or copy "
        "tools/boot_marker_baseline.py to the device and run it directly there."
    )


def ssh_command(target: str, remote_script: str, *, connect_timeout: int) -> list[str]:
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={connect_timeout}",
        target,
        remote_script,
    ]


def scp_command(source: str, target: str, *, connect_timeout: int) -> list[str]:
    return [
        "scp",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={connect_timeout}",
        source,
        target,
    ]


def local_scp_source(path: Path) -> str:
    raw = str(path)
    match = re.match(r"^/([a-zA-Z])/(.*)$", raw)
    if match:
        drive = match.group(1).upper()
        rest = match.group(2).replace("/", "\\")
        return f"{drive}:\\{rest}"
    return raw


def upload_text_file(target: str, remote_path: str, text: str, *, connect_timeout: int) -> CommandResult:
    remote_script = f"umask 077; cat > {shlex.quote(remote_path)}"
    return run_with_input(ssh_command(target, remote_script, connect_timeout=connect_timeout), text, timeout=30.0)


def upload_helper(target: str, remote_helper: str, helper_text: str, *, connect_timeout: int) -> None:
    uploaded = upload_text_file(
        target,
        remote_helper,
        helper_text,
        connect_timeout=connect_timeout,
    )
    if uploaded.returncode == 0:
        return
    require_ok(
        run(
            scp_command(local_scp_source(BOOT_HELPER), f"{target}:{remote_helper}", connect_timeout=connect_timeout),
            timeout=30.0,
        )
    )


def remote_collect_script(remote_helper: str, remote_dir: str, prefix: str, *, no_http_status: bool, sudo: bool = False) -> str:
    helper = shlex.quote(remote_helper)
    out_dir = shlex.quote(remote_dir)
    file_prefix = shlex.quote(prefix)
    http_arg = " --no-http-status" if no_http_status else ""
    sudo_prefix = "sudo -n " if sudo else ""
    return f"""
set -eu
mkdir -p {out_dir}
{sudo_prefix}python3 {helper} --output {out_dir}/{file_prefix}-boot-baseline.md{http_arg}
systemd-analyze --no-pager > {out_dir}/{file_prefix}-systemd-analyze.txt 2>&1 || true
systemd-analyze blame --no-pager > {out_dir}/{file_prefix}-systemd-blame.txt 2>&1 || true
systemd-analyze critical-chain --no-pager > {out_dir}/{file_prefix}-critical-chain.txt 2>&1 || true
{{
  echo '## identity'
  hostname
  uname -a
  echo '## os-release'
  sed -n '1,12p' /etc/os-release 2>/dev/null || true
  echo '## model'
  tr -d '\\000' </proc/device-tree/model 2>/dev/null || true
  echo
  echo '## uptime'
  cat /proc/uptime
  echo '## cmdline'
  cat /proc/cmdline
  echo '## memory'
  free -h || true
  echo '## block'
  lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINTS || true
  echo '## modules'
  lsmod | egrep 'dwc2|libcomposite|configfs|usb_f_hid|g_hid' || true
  echo '## module availability'
  find /lib/modules/$(uname -r) -type f \\( \\
    -name 'dwc2*.ko*' -o \\
    -name 'libcomposite*.ko*' -o \\
    -name 'usb_f_hid*.ko*' -o \\
    -name 'g_hid*.ko*' -o \\
    -name 'configfs*.ko*' \\
  \\) -print | sort || true
  grep -E 'dwc2|libcomposite|usb_f_hid|g_hid|configfs' /lib/modules/$(uname -r)/modules.builtin 2>/dev/null | sed -n '1,80p' || true
  grep -E 'dwc2|libcomposite|usb_f_hid|g_hid|configfs' /lib/modules/$(uname -r)/modules.dep 2>/dev/null | sed -n '1,80p' || true
  echo '## configfs'
  mount | grep configfs || true
  ls -ld /sys/kernel/config /sys/kernel/config/usb_gadget 2>/dev/null || true
  echo '## hidg'
  ls -l /dev/hidg* 2>/dev/null || true
}} > {out_dir}/{file_prefix}-snapshot.txt
"""


def remote_reboot_script(reboot_command: str) -> str:
    reboot = shlex.quote(f"sleep 1; {reboot_command}")
    return f"nohup sh -c {reboot} >/tmp/hidloom-remote-boot-reboot.log 2>&1 &"


def wait_for_ssh(
    target: str,
    *,
    connect_timeout: int,
    boot_wait_timeout_sec: float,
    poll_sec: float,
    settle_sec: float,
) -> None:
    deadline = time.monotonic() + boot_wait_timeout_sec
    last_result: CommandResult | None = None
    while time.monotonic() < deadline:
        result = run(ssh_command(target, "true", connect_timeout=connect_timeout), timeout=connect_timeout + 2.0)
        last_result = result
        if result.returncode == 0:
            if settle_sec > 0:
                time.sleep(settle_sec)
            return
        time.sleep(poll_sec)
    detail = ""
    if last_result is not None:
        detail = f"\nlast stdout:\n{last_result.stdout}\nlast stderr:\n{last_result.stderr}"
    raise SystemExit(f"timed out waiting for SSH after reboot: {target}{detail}")


def copy_remote_dir(target: str, remote_dir: str, output_dir: Path, *, connect_timeout: int) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    ssh_parts = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={connect_timeout}",
        target,
        f"tar -C {shlex.quote(remote_dir)} -cf - .",
    ]
    command = " ".join(shlex.quote(part) for part in ssh_parts)
    command += f" | tar -C {shlex.quote(str(output_dir))} -xf -"
    require_ok(run(["bash", "-lc", command], timeout=60.0))


def read_first_line(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip():
                return line.strip()
    except OSError:
        return ""
    return ""


def section_text(text: str, heading: str) -> str:
    lines = text.splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        if line.strip() == heading:
            start = index + 1
            break
    if start is None:
        return ""
    end = len(lines)
    for index in range(start, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return "\n".join(lines[start:end])


def parse_boot_timeline(report_text: str) -> dict[str, str]:
    section = section_text(report_text, "## Readiness Timeline")
    markers: dict[str, str] = {}
    priorities: dict[str, int] = {}
    for line in section.splitlines():
        if not line.startswith("| "):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 7 or cells[0] in ("time_sec", "---:"):
            continue
        time_sec, _delta, kind, label, _source, confidence, _message = cells[:7]
        if not time_sec or time_sec.startswith("("):
            continue
        key = ""
        priority = 10
        if kind == "usb-gadget" and label == "usb gadget configured":
            key = "usb"
            priority = 90
        elif kind == "hid-broker" and label == "hidd broker active":
            key = "hidd"
            priority = 90
        elif kind == "input-core" and label == "logicd-core active":
            key = "core"
            priority = 90
        elif kind == "input-ready" and label == "matrixd connected to logic owner":
            key = "input"
            priority = 100
        elif kind == "socket-ready" and label == "logicd sockets listening":
            key = "sockets"
            priority = 90
        elif kind == "network-access" and label == "ssh listening":
            key = "ssh"
            priority = 90
        elif kind == "network-ready" and confidence == "known":
            key = "network"
            priority = 100
        elif kind == "unit-active":
            if label == "hidloom-usb-gadget.service active":
                key = "usb"
                priority = 50
            elif label == "hidloom-hidd.service active":
                key = "hidd"
                priority = 50
            elif label == "hidloom-logicd-core.service active":
                key = "core"
                priority = 50
            elif label == "matrixd.service active":
                key = "input"
                priority = 20
            elif label == "ssh.service active":
                key = "ssh"
                priority = 50
            elif label == "NetworkManager.service active":
                key = "network"
                priority = 20
        if key and priority > priorities.get(key, -1):
            markers[key] = time_sec
            priorities[key] = priority
    return markers


def _timeline_float(timeline: dict[str, str], key: str) -> float | None:
    value = timeline.get(key, "")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def timeline_delta(timeline: dict[str, str], start_key: str, end_key: str) -> str:
    start = _timeline_float(timeline, start_key)
    end = _timeline_float(timeline, end_key)
    if start is None or end is None:
        return ""
    return f"{end - start:.3f}"


def keyboard_ready_at(timeline: dict[str, str]) -> str:
    return timeline.get("input") or timeline.get("core") or timeline.get("hidd") or timeline.get("usb") or ""


def render_summary(target: str, output_dir: Path) -> str:
    lines = [
        "# Remote Boot Baseline Summary",
        "",
        f"- target: `{target}`",
        f"- collected_at: `{datetime.now(timezone.utc).isoformat(timespec='seconds')}`",
        f"- artifact_dir: `{output_dir}`",
        "",
        "## Samples",
        "",
        "| sample | systemd-analyze | keyboard_ready | usb->input | hidd->input | input->ssh | input->network | usb | hidd | core | input | sockets | ssh | network | top blame | hidg | modules |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for systemd_path in sorted(output_dir.glob("*-systemd-analyze.txt")):
        prefix = systemd_path.name[: -len("-systemd-analyze.txt")]
        blame_path = output_dir / f"{prefix}-systemd-blame.txt"
        snapshot_path = output_dir / f"{prefix}-snapshot.txt"
        boot_report_path = output_dir / f"{prefix}-boot-baseline.md"
        analyze = read_first_line(systemd_path)
        blame = read_first_line(blame_path)
        snapshot = snapshot_path.read_text(encoding="utf-8", errors="replace") if snapshot_path.exists() else ""
        timeline = (
            parse_boot_timeline(boot_report_path.read_text(encoding="utf-8", errors="replace"))
            if boot_report_path.exists()
            else {}
        )
        hidg = "present" if "/dev/hidg" in snapshot else "none"
        loaded_modules = section_text(snapshot, "## modules")
        modules = "loaded" if any(name in loaded_modules for name in ("dwc2", "libcomposite", "usb_f_hid", "g_hid")) else "not loaded"
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{prefix}`",
                    analyze or "(no output)",
                    keyboard_ready_at(timeline),
                    timeline_delta(timeline, "usb", "input"),
                    timeline_delta(timeline, "hidd", "input"),
                    timeline_delta(timeline, "input", "ssh"),
                    timeline_delta(timeline, "input", "network"),
                    timeline.get("usb", ""),
                    timeline.get("hidd", ""),
                    timeline.get("core", ""),
                    timeline.get("input", ""),
                    timeline.get("sockets", ""),
                    timeline.get("ssh", ""),
                    timeline.get("network", ""),
                    blame or "(no output)",
                    hidg,
                    modules,
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="SSH target, e.g. pi@<keyboard-ip>")
    parser.add_argument("--label", help="artifact label; defaults to a safe target name")
    parser.add_argument("--output-dir", type=Path, help="local artifact directory")
    parser.add_argument("--samples", type=int, default=1, help="number of samples to collect")
    parser.add_argument("--interval-sec", type=float, default=5.0, help="sleep between samples")
    parser.add_argument("--remote-dir", default="/tmp/hidloom-remote-boot-baseline", help="remote artifact directory")
    parser.add_argument("--remote-helper", default="/tmp/hidloom-boot_marker_baseline.py", help="remote helper path")
    parser.add_argument("--connect-timeout", type=int, default=5, help="SSH connect timeout")
    parser.add_argument("--sample-timeout-sec", type=float, default=180.0, help="timeout for each remote sample")
    parser.add_argument("--no-http-status", action="store_true", help="skip remote HTTPS status probe")
    parser.add_argument("--sudo", action="store_true", help="run the remote boot marker helper with sudo -n")
    parser.add_argument(
        "--reboot-before-sample",
        action="store_true",
        help="request a remote reboot before each sample and wait for SSH to return",
    )
    parser.add_argument(
        "--reboot-command",
        default="sudo -n systemctl reboot",
        help="remote command used by --reboot-before-sample",
    )
    parser.add_argument("--boot-wait-timeout-sec", type=float, default=120.0, help="max wait for SSH after reboot")
    parser.add_argument("--boot-poll-sec", type=float, default=3.0, help="SSH polling interval after reboot")
    parser.add_argument("--post-reboot-request-delay-sec", type=float, default=5.0, help="delay after requesting reboot before polling SSH")
    parser.add_argument("--post-ssh-settle-sec", type=float, default=5.0, help="settle delay after SSH returns")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.samples < 1:
        raise SystemExit("--samples must be >= 1")
    if args.interval_sec < 0:
        raise SystemExit("--interval-sec must be >= 0")
    if args.sample_timeout_sec < 1:
        raise SystemExit("--sample-timeout-sec must be >= 1")
    if args.boot_wait_timeout_sec < 1:
        raise SystemExit("--boot-wait-timeout-sec must be >= 1")
    if args.boot_poll_sec <= 0:
        raise SystemExit("--boot-poll-sec must be > 0")
    if args.post_reboot_request_delay_sec < 0:
        raise SystemExit("--post-reboot-request-delay-sec must be >= 0")
    if args.post_ssh_settle_sec < 0:
        raise SystemExit("--post-ssh-settle-sec must be >= 0")
    if not BOOT_HELPER.exists():
        raise SystemExit(f"missing helper: {BOOT_HELPER}")

    label = safe_name(args.label or args.target)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / f"{label}-remote-boot-baseline-{stamp}")
    remote_dir = f"{args.remote_dir}-{label}-{stamp}"

    output_dir.mkdir(parents=True, exist_ok=True)
    require_ssh_transport(args.target, connect_timeout=args.connect_timeout)
    helper_text = BOOT_HELPER.read_text(encoding="utf-8")
    upload_helper(args.target, args.remote_helper, helper_text, connect_timeout=args.connect_timeout)

    for sample in range(1, args.samples + 1):
        prefix = f"{label}-sample-{sample:02d}"
        if args.reboot_before_sample:
            reboot = run(
                ssh_command(
                    args.target,
                    remote_reboot_script(args.reboot_command),
                    connect_timeout=args.connect_timeout,
                ),
                timeout=10.0,
            )
            require_ok(reboot)
            if args.post_reboot_request_delay_sec > 0:
                time.sleep(args.post_reboot_request_delay_sec)
            wait_for_ssh(
                args.target,
                connect_timeout=args.connect_timeout,
                boot_wait_timeout_sec=args.boot_wait_timeout_sec,
                poll_sec=args.boot_poll_sec,
                settle_sec=args.post_ssh_settle_sec,
            )
            upload_helper(args.target, args.remote_helper, helper_text, connect_timeout=args.connect_timeout)
        script = remote_collect_script(args.remote_helper, remote_dir, prefix, no_http_status=args.no_http_status, sudo=args.sudo)
        require_ok(run(ssh_command(args.target, script, connect_timeout=args.connect_timeout), timeout=args.sample_timeout_sec))
        if sample != args.samples:
            time.sleep(args.interval_sec)

    copy_remote_dir(args.target, remote_dir, output_dir, connect_timeout=args.connect_timeout)
    (output_dir / "summary.md").write_text(render_summary(args.target, output_dir), encoding="utf-8")
    print(output_dir)


if __name__ == "__main__":
    main()
