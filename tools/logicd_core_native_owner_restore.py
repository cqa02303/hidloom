#!/usr/bin/env python3
"""Restore native logicd-core as the matrix owner after rollback testing."""
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
PYTHON_OWNER_DROPIN = Path("/run/systemd/system/matrixd.service.d/10-python-owner-recovery.conf")
PYTHON_OWNER_RUNTIME_UNIT = Path("/run/systemd/system/matrixd.service")
MATRIXD_SYSTEM_UNIT = Path("/etc/systemd/system/matrixd.service")
MATRIXD_NATIVE_BACKUP = Path("/run/hidloom/matrixd.service.native-owner-backup")
DEFAULT_EXPECT_ACTIVE = (HIDD_UNIT, CORE_UNIT, MATRIXD_UNIT, COMPANION_UNIT)
DEFAULT_EXPECT_INACTIVE = (LOGICD_UNIT,)
NON_FATAL_STEPS = {
    "stop legacy logicd",
    "disable legacy logicd",
    "remove python-owner runtime unit",
    "remove python-owner drop-in",
    "reset failed legacy logicd",
    "unmask logicd-core",
}


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


def restore_commands(*, sudo: bool, repo_root: Path = ROOT) -> list[tuple[str, list[str]]]:
    prefix = sudo_prefix(sudo)
    restore_matrixd_unit_command = (
        f"if test -f {shlex.quote(str(MATRIXD_NATIVE_BACKUP))}; then\n"
        f"  cp {shlex.quote(str(MATRIXD_NATIVE_BACKUP))} {shlex.quote(str(MATRIXD_SYSTEM_UNIT))}\n"
        "else\n"
        f"  sed 's|@HIDLOOM_REPO_ROOT@|{repo_root}|g' {shlex.quote(str(repo_root / 'system/systemd/matrixd.service'))} > {shlex.quote(str(MATRIXD_SYSTEM_UNIT))}\n"
        "fi\n"
    )
    return [
        ("stop matrixd", [*prefix, "systemctl", "stop", MATRIXD_UNIT]),
        ("stop legacy logicd", [*prefix, "systemctl", "stop", LOGICD_UNIT]),
        ("disable legacy logicd", [*prefix, "systemctl", "disable", LOGICD_UNIT]),
        ("unmask logicd-core", [*prefix, "systemctl", "unmask", CORE_UNIT]),
        ("restore native matrixd system unit", [*prefix, "sh", "-c", restore_matrixd_unit_command]),
        ("remove python-owner runtime unit", [*prefix, "rm", "-f", str(PYTHON_OWNER_RUNTIME_UNIT)]),
        ("remove python-owner drop-in", [*prefix, "rm", "-f", str(PYTHON_OWNER_DROPIN)]),
        ("daemon reload", [*prefix, "systemctl", "daemon-reload"]),
        ("enable native owner units", [*prefix, "systemctl", "enable", HIDD_UNIT, CORE_UNIT, MATRIXD_UNIT, COMPANION_UNIT]),
        ("start hidloom-hidd", [*prefix, "systemctl", "start", HIDD_UNIT]),
        ("restart logicd-core", [*prefix, "systemctl", "restart", CORE_UNIT]),
        ("restart matrixd", [*prefix, "systemctl", "restart", MATRIXD_UNIT]),
        ("restart logicd-companion", [*prefix, "systemctl", "restart", COMPANION_UNIT]),
        ("reset failed legacy logicd", [*prefix, "systemctl", "reset-failed", LOGICD_UNIT]),
    ]


def status_command(unit: str, *, sudo: bool) -> list[str]:
    return [*sudo_prefix(sudo), "systemctl", "is-active", unit]


def enabled_command(unit: str, *, sudo: bool) -> list[str]:
    return [*sudo_prefix(sudo), "systemctl", "is-enabled", unit]


def collect_statuses(
    units: tuple[str, ...],
    *,
    sudo: bool,
    apply: bool,
    timeout: float,
) -> dict[str, dict[str, object]]:
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


def evaluate(statuses: dict[str, dict[str, object]], *, dropin_exists: bool) -> tuple[bool, list[str]]:
    issues: list[str] = []
    if dropin_exists:
        issues.append(f"{PYTHON_OWNER_DROPIN} still exists")
    for unit in DEFAULT_EXPECT_ACTIVE:
        if statuses.get(unit, {}).get("active") != "active":
            issues.append(f"{unit} is not active")
        if statuses.get(unit, {}).get("enabled") != "enabled":
            issues.append(f"{unit} is not enabled")
    for unit in DEFAULT_EXPECT_INACTIVE:
        if statuses.get(unit, {}).get("active") == "active":
            issues.append(f"{unit} is still active")
        if statuses.get(unit, {}).get("enabled") == "enabled":
            issues.append(f"{unit} is still enabled")
    return not issues, issues


def run_restore(*, apply: bool, sudo: bool, timeout: float) -> dict[str, object]:
    steps: list[StepResult] = []
    for name, command in restore_commands(sudo=sudo):
        result = run_step(name, command, apply=apply, timeout=timeout)
        steps.append(result)
        if result.returncode != 0 and apply and name not in NON_FATAL_STEPS:
            break
    units = (HIDD_UNIT, CORE_UNIT, MATRIXD_UNIT, COMPANION_UNIT, LOGICD_UNIT)
    statuses = collect_statuses(units, sudo=sudo, apply=apply, timeout=timeout)
    dropin_exists = PYTHON_OWNER_DROPIN.exists() if apply else False
    ok, issues = evaluate(statuses, dropin_exists=dropin_exists) if apply else (True, [])
    return {
        "schema": "logicd-core.native-owner-restore.v1",
        "mode": "apply" if apply else "dry-run",
        "ok": ok,
        "issues": issues,
        "python_owner_dropin": {"path": str(PYTHON_OWNER_DROPIN), "exists": dropin_exists},
        "steps": [step.to_dict() for step in steps],
        "statuses": statuses,
    }


def render_text(payload: dict[str, object]) -> str:
    lines = [f"mode: {payload['mode']}", f"ok: {payload['ok']}"]
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
    mode.add_argument("--apply", action="store_true", help="execute restore commands")
    mode.add_argument("--dry-run", action="store_true", help="print commands only; default")
    parser.add_argument("--sudo", action="store_true", help="prefix system commands with sudo when not root")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--timeout-sec", type=float, default=12.0, help="timeout for each command")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.timeout_sec <= 0:
        raise SystemExit("--timeout-sec must be > 0")
    payload = run_restore(apply=args.apply, sudo=args.sudo, timeout=args.timeout_sec)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(render_text(payload))
    if args.apply and not payload["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
