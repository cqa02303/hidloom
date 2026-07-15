#!/usr/bin/env python3
"""Rollback helper for restoring Python logicd as the matrix owner."""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]

CORE_UNIT = "hidloom-logicd-core.service"
HIDD_UNIT = "hidloom-hidd.service"
LOGICD_UNIT = "logicd.service"
COMPANION_UNIT = "logicd-companion.service"
MATRIXD_UNIT = "matrixd.service"
MATRIXD_SYSTEM_UNIT = Path("/etc/systemd/system/matrixd.service")
MATRIXD_NATIVE_BACKUP = Path("/run/hidloom/matrixd.service.native-owner-backup")
DEFAULT_EXPECT_ACTIVE = (HIDD_UNIT, LOGICD_UNIT, MATRIXD_UNIT)
DEFAULT_EXPECT_INACTIVE = (CORE_UNIT, COMPANION_UNIT)
NON_FATAL_STEPS = {
    "stop matrixd",
    "stop logicd-companion",
    "disable logicd-companion",
    "mask logicd-core runtime",
    "reset failed logicd-core",
    "mark logicd-core stopped",
    "final stop logicd-core",
}


def matrixd_python_owner_unit(repo_root: Path) -> str:
    return f"""[Unit]
Description=Keyboard Matrix Scanner Daemon (matrixd, Python owner rollback)
Documentation=file://{repo_root}/daemon/matrixd/README.md
Requires=logicd.service
After=logicd.service

[Service]
Type=simple
ExecStart={repo_root}/daemon/matrixd/matrixd {repo_root}/config/default/matrixd.json
WorkingDirectory={repo_root}
User=root
Group=root

Nice=-20
CPUSchedulingPolicy=fifo
CPUSchedulingPriority=99
IOSchedulingClass=realtime
IOSchedulingPriority=0
LimitRTPRIO=99
LimitNICE=-20

Restart=on-failure
RestartSec=2s

TimeoutStopSec=5

StandardOutput=journal
StandardError=journal
SyslogIdentifier=matrixd

[Install]
WantedBy=multi-user.target
"""


@dataclass(frozen=True)
class StepResult:
    name: str
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    elapsed_sec: float
    skipped: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "command": self.command,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "elapsed_sec": round(self.elapsed_sec, 3),
            "skipped": self.skipped,
        }


def command_text(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def sudo_prefix(enabled: bool) -> list[str]:
    return ["sudo"] if enabled and os.geteuid() != 0 else []


def run_step(name: str, command: list[str], *, apply: bool, timeout: float) -> StepResult:
    if not apply:
        return StepResult(name, command, 0, "", "", 0.0, skipped=True)
    started = time.monotonic()
    proc = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    return StepResult(
        name=name,
        command=command,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        elapsed_sec=time.monotonic() - started,
    )


def recovery_commands(*, sudo: bool, repo_root: Path = ROOT) -> list[tuple[str, list[str]]]:
    prefix = sudo_prefix(sudo)
    core_bin = repo_root / "bin" / "hidloom-logicd-core"
    matrixd_unit_command = (
        "mkdir -p /run/hidloom && "
        f"test -f {shlex.quote(str(MATRIXD_NATIVE_BACKUP))} || cp {shlex.quote(str(MATRIXD_SYSTEM_UNIT))} {shlex.quote(str(MATRIXD_NATIVE_BACKUP))}\n"
        f"cat > {shlex.quote(str(MATRIXD_SYSTEM_UNIT))} <<'EOF'\n"
        f"{matrixd_python_owner_unit(repo_root)}"
        "EOF\n"
    )
    commands: list[tuple[str, list[str]]] = [
        ("stop matrixd", [*prefix, "systemctl", "stop", MATRIXD_UNIT]),
        ("stop logicd-companion", [*prefix, "systemctl", "stop", COMPANION_UNIT]),
        ("disable logicd-companion", [*prefix, "systemctl", "disable", COMPANION_UNIT]),
        ("stop logicd-core", [*prefix, "systemctl", "stop", CORE_UNIT]),
        ("disable logicd-core", [*prefix, "systemctl", "disable", CORE_UNIT]),
        ("mask logicd-core runtime", [*prefix, "systemctl", "mask", "--runtime", CORE_UNIT]),
        ("reset failed logicd-core", [*prefix, "systemctl", "reset-failed", CORE_UNIT]),
        ("install matrixd python-owner system unit", [*prefix, "sh", "-c", matrixd_unit_command]),
        ("daemon reload", [*prefix, "systemctl", "daemon-reload"]),
    ]
    if core_bin.exists():
        commands.append(("mark logicd-core stopped", [*prefix, str(core_bin), "--mark-stopped"]))
    commands.extend(
        [
            ("start hidloom-hidd", [*prefix, "systemctl", "start", HIDD_UNIT]),
            ("start logicd", [*prefix, "systemctl", "start", LOGICD_UNIT]),
            ("start matrixd", [*prefix, "systemctl", "start", MATRIXD_UNIT]),
            ("final stop logicd-core", [*prefix, "systemctl", "stop", CORE_UNIT]),
        ]
    )
    return commands


def status_command(unit: str, *, sudo: bool) -> list[str]:
    return [*sudo_prefix(sudo), "systemctl", "is-active", unit]


def enabled_command(unit: str, *, sudo: bool) -> list[str]:
    return [*sudo_prefix(sudo), "systemctl", "is-enabled", unit]


def collect_statuses(units: tuple[str, ...], *, sudo: bool, apply: bool, timeout: float) -> dict[str, dict[str, object]]:
    statuses: dict[str, dict[str, object]] = {}
    for unit in units:
        active = run_step(f"is-active {unit}", status_command(unit, sudo=sudo), apply=apply, timeout=timeout)
        enabled = run_step(f"is-enabled {unit}", enabled_command(unit, sudo=sudo), apply=apply, timeout=timeout)
        statuses[unit] = {
            "active": active.stdout.strip() if apply else "unknown",
            "enabled": enabled.stdout.strip() if apply else "unknown",
            "active_rc": active.returncode,
            "enabled_rc": enabled.returncode,
        }
    return statuses


def evaluate(statuses: dict[str, dict[str, object]]) -> tuple[bool, list[str]]:
    issues: list[str] = []
    for unit in DEFAULT_EXPECT_ACTIVE:
        if statuses.get(unit, {}).get("active") != "active":
            issues.append(f"{unit} is not active")
    for unit in DEFAULT_EXPECT_INACTIVE:
        if statuses.get(unit, {}).get("active") == "active":
            issues.append(f"{unit} is still active")
        if statuses.get(unit, {}).get("enabled") == "enabled":
            issues.append(f"{unit} is still enabled")
    return not issues, issues


def run_recovery(*, apply: bool, sudo: bool, timeout: float, repo_root: Path = ROOT) -> dict[str, object]:
    steps: list[StepResult] = []
    for name, command in recovery_commands(sudo=sudo, repo_root=repo_root):
        result = run_step(name, command, apply=apply, timeout=timeout)
        steps.append(result)
        if result.returncode != 0 and apply and name not in NON_FATAL_STEPS:
            break
    units = (CORE_UNIT, COMPANION_UNIT, HIDD_UNIT, LOGICD_UNIT, MATRIXD_UNIT)
    statuses = collect_statuses(units, sudo=sudo, apply=apply, timeout=timeout)
    ok, issues = evaluate(statuses) if apply else (True, [])
    return {
        "schema": "logicd-core.owner-recovery.v1",
        "mode": "apply" if apply else "dry-run",
        "ok": ok,
        "issues": issues,
        "steps": [step.to_dict() for step in steps],
        "statuses": statuses,
    }


def render_text(payload: dict[str, object]) -> str:
    lines = [
        f"mode: {payload['mode']}",
        f"ok: {payload['ok']}",
    ]
    issues = payload.get("issues") or []
    if issues:
        lines.append("issues:")
        lines.extend(f"- {issue}" for issue in issues)
    lines.append("steps:")
    for step in payload["steps"]:  # type: ignore[index]
        assert isinstance(step, dict)
        marker = "skip" if step.get("skipped") else f"rc={step.get('returncode')}"
        lines.append(f"- {marker}: {command_text(step['command'])}")  # type: ignore[arg-type]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="execute rollback commands")
    mode.add_argument("--dry-run", action="store_true", help="print commands only; default")
    parser.add_argument("--sudo", action="store_true", help="prefix system commands with sudo when not root")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--timeout-sec", type=float, default=12.0, help="timeout for each command")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.timeout_sec <= 0:
        raise SystemExit("--timeout-sec must be > 0")
    payload = run_recovery(apply=args.apply, sudo=args.sudo, timeout=args.timeout_sec)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(render_text(payload))
    if args.apply and not payload["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
