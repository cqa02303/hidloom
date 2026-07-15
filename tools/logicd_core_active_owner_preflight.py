#!/usr/bin/env python3
"""Read-only preflight for a logicd-core active-owner measurement run."""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import logicd_core_owner_recovery as recovery  # noqa: E402

CORE_UNIT = recovery.CORE_UNIT
HIDD_UNIT = recovery.HIDD_UNIT
LOGICD_UNIT = recovery.LOGICD_UNIT
MATRIXD_UNIT = recovery.MATRIXD_UNIT
BOOT_MARKER_TOOL = ROOT / "tools" / "boot_marker_baseline.py"


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str

    def to_dict(self) -> dict[str, object]:
        return {
            "command": self.command,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


def sudo_prefix(enabled: bool) -> list[str]:
    return ["sudo"] if enabled and os.geteuid() != 0 else []


def run_command(command: list[str], *, timeout: float) -> CommandResult:
    proc = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    return CommandResult(command, proc.returncode, proc.stdout.strip(), proc.stderr.strip())


def unit_state(unit: str, *, sudo: bool, timeout: float) -> dict[str, object]:
    prefix = sudo_prefix(sudo)
    active = run_command([*prefix, "systemctl", "is-active", unit], timeout=timeout)
    enabled = run_command([*prefix, "systemctl", "is-enabled", unit], timeout=timeout)
    return {
        "active": active.stdout,
        "enabled": enabled.stdout,
        "active_rc": active.returncode,
        "enabled_rc": enabled.returncode,
    }


def load_status(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"path": str(path), "exists": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - status files are external runtime inputs.
        return {"path": str(path), "exists": True, "error": str(exc)}
    return {"path": str(path), "exists": True, "payload": payload}


def check_config(repo_root: Path, *, timeout: float) -> dict[str, object]:
    binary = repo_root / "bin" / "hidloom-logicd-core"
    if not binary.exists():
        binary = repo_root / "tools" / "hidloom_logicd_core" / "target" / "release" / "hidloom-logicd-core"
    if not binary.exists():
        return {"ok": False, "error": "hidloom-logicd-core binary not found"}
    env = os.environ.copy()
    env.setdefault("HIDLOOM_REPO_ROOT", str(repo_root))
    result = subprocess.run(
        [str(binary), "--check-config"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        env=env,
    )
    payload: dict[str, Any] | None = None
    if result.stdout.strip():
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            payload = None
    return {
        "ok": result.returncode == 0 and isinstance(payload, dict),
        "binary": str(binary),
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "payload": payload,
    }


def file_mode(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"path": str(path), "exists": False}
    return {
        "path": str(path),
        "exists": True,
        "executable": os.access(path, os.X_OK),
        "size": path.stat().st_size,
    }


def evaluate(payload: dict[str, object]) -> tuple[bool, list[str], list[str]]:
    issues: list[str] = []
    warnings: list[str] = []
    files = payload["files"]  # type: ignore[index]
    assert isinstance(files, dict)
    core_bin = files["core_binary"]  # type: ignore[index]
    assert isinstance(core_bin, dict)
    if not core_bin.get("exists"):
        issues.append("hidloom-logicd-core binary is missing")
    elif not core_bin.get("executable"):
        issues.append("hidloom-logicd-core binary is not executable")
    if not files.get("boot_marker_tool", {}).get("exists"):  # type: ignore[union-attr]
        issues.append("boot marker helper is missing")

    units = payload["units"]  # type: ignore[index]
    assert isinstance(units, dict)
    for unit in (HIDD_UNIT, LOGICD_UNIT, MATRIXD_UNIT):
        if units.get(unit, {}).get("active") != "active":  # type: ignore[union-attr]
            issues.append(f"{unit} is not active")
    if units.get(CORE_UNIT, {}).get("active") == "active":  # type: ignore[union-attr]
        issues.append(f"{CORE_UNIT} is active; expected inactive before rehearsal")
    if units.get(CORE_UNIT, {}).get("enabled") == "enabled":  # type: ignore[union-attr]
        issues.append(f"{CORE_UNIT} is enabled; expected disabled before reboot rehearsal")

    config = payload["check_config"]  # type: ignore[index]
    assert isinstance(config, dict)
    if not config.get("ok"):
        issues.append("hidloom-logicd-core --check-config failed")
    else:
        routing = (config.get("payload") or {}).get("routing", {})  # type: ignore[union-attr]
        if routing.get("usb_split_keyboard") is not True:
            warnings.append("usb_split_keyboard is not enabled in core config")
        if routing.get("route") != "jis_special_us_default":
            warnings.append("core config route is not jis_special_us_default")

    recovery_payload = payload["recovery_dry_run"]  # type: ignore[index]
    assert isinstance(recovery_payload, dict)
    step_names = [step.get("name") for step in recovery_payload.get("steps", []) if isinstance(step, dict)]
    for required in ("stop logicd-core", "disable logicd-core", "start logicd", "start matrixd"):
        if required not in step_names:
            issues.append(f"rollback dry-run is missing step: {required}")

    statuses = payload["status_files"]  # type: ignore[index]
    assert isinstance(statuses, dict)
    core_status = statuses.get("logicd_core", {})
    if isinstance(core_status, dict) and core_status.get("exists"):
        status_payload = core_status.get("payload")
        if isinstance(status_payload, dict) and status_payload.get("process") is True:
            warnings.append("logicd-core status still reports process=true")

    return not issues, issues, warnings


def collect_preflight(*, sudo: bool, timeout: float, repo_root: Path = ROOT) -> dict[str, object]:
    core_binary = repo_root / "bin" / "hidloom-logicd-core"
    payload: dict[str, object] = {
        "schema": "logicd-core.active-owner-preflight.v1",
        "mode": "read-only",
        "repo_root": str(repo_root),
        "files": {
            "core_binary": file_mode(core_binary),
            "boot_marker_tool": file_mode(BOOT_MARKER_TOOL),
            "service_unit_source": file_mode(repo_root / "system" / "systemd" / "hidloom-logicd-core.service"),
        },
        "units": {
            unit: unit_state(unit, sudo=sudo, timeout=timeout)
            for unit in (CORE_UNIT, HIDD_UNIT, LOGICD_UNIT, MATRIXD_UNIT)
        },
        "status_files": {
            "hidd": load_status(Path("/run/hidloom/hidd-status.json")),
            "logicd_core": load_status(Path("/run/hidloom/logicd-core-status.json")),
        },
        "check_config": check_config(repo_root, timeout=timeout),
        "recovery_dry_run": recovery.run_recovery(apply=False, sudo=sudo, timeout=timeout, repo_root=repo_root),
        "next_required": [
            "capture boot marker baseline before native owner rehearsal",
            "reboot into explicit native-owner measurement only after operator approval",
            "run live output-enabled keyboard and US sub smoke after reboot marker is acceptable",
        ],
    }
    ok, issues, warnings = evaluate(payload)
    payload["ok"] = ok
    payload["issues"] = issues
    payload["warnings"] = warnings
    return payload


def render_text(payload: dict[str, object]) -> str:
    lines = [
        f"schema: {payload['schema']}",
        f"ok: {payload['ok']}",
    ]
    for label in ("issues", "warnings"):
        values = payload.get(label) or []
        if values:
            lines.append(f"{label}:")
            lines.extend(f"- {value}" for value in values)  # type: ignore[union-attr]
    lines.append("next:")
    lines.extend(f"- {item}" for item in payload["next_required"])  # type: ignore[index]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sudo", action="store_true", help="use sudo for read-only systemctl checks when needed")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--timeout-sec", type=float, default=5.0, help="timeout for each read-only command")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.timeout_sec <= 0:
        raise SystemExit("--timeout-sec must be > 0")
    payload = collect_preflight(sudo=args.sudo, timeout=args.timeout_sec)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(render_text(payload))
    if not payload["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
