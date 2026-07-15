#!/usr/bin/env python3
"""Read-only Codex task mailbox helper for keyboard-side observation."""
from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAILBOX = ROOT / "codex_tasks"

REQUIRED_DIRS = ("inbox", "running", "done", "failed")
ALLOWED_RESULT_DIRS = ("done", "failed")
FORBIDDEN_CHECK_MARKERS = (
    " systemctl restart ",
    " systemctl stop ",
    " systemctl start ",
    " service restart ",
    " service stop ",
    " service start ",
    " pnputil ",
    " reg add ",
    " reg delete ",
    " git ",
    " rm ",
    " del ",
    " remove-item ",
    " mv ",
    " move-item ",
    " cp ",
    " copy-item ",
    " >",
    ">>",
)


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: tuple[str, ...]


def ensure_mailbox(root: Path = DEFAULT_MAILBOX) -> None:
    for name in REQUIRED_DIRS:
        (root / name).mkdir(parents=True, exist_ok=True)


def load_task(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalized_check(check: str) -> str:
    return " " + " ".join(check.strip().lower().split()) + " "


def _is_allowed_check(check: str) -> bool:
    stripped = check.strip()
    lowered = _normalized_check(stripped)
    if any(marker in lowered for marker in FORBIDDEN_CHECK_MARKERS):
        return False
    return (
        stripped.startswith("systemctl is-active ")
        or stripped.startswith("ls -l /dev/hidg")
        or stripped.startswith("ls -l /tmp/")
        or stripped == "read config/default/config.json settings.usb_split_keyboard"
        or stripped.startswith("journalctl -u ")
    )


def validate_task(task: dict[str, Any]) -> ValidationResult:
    errors: list[str] = []
    if task.get("version") != 1:
        errors.append("version must be 1")
    task_id = task.get("id")
    if not isinstance(task_id, str) or not task_id.strip():
        errors.append("id must be a non-empty string")
    elif any(part in task_id for part in ("/", "\\", "..")):
        errors.append("id must not contain path separators or '..'")
    if task.get("mode") != "read_only":
        errors.append("mode must be read_only")
    if task.get("requested_by") != "desktop-codex":
        errors.append("requested_by must be desktop-codex")
    checks = task.get("checks")
    if not isinstance(checks, list) or not checks:
        errors.append("checks must be a non-empty list")
    else:
        for idx, check in enumerate(checks):
            if not isinstance(check, str) or not check.strip():
                errors.append(f"checks[{idx}] must be a non-empty string")
            elif not _is_allowed_check(check):
                errors.append(f"checks[{idx}] is not an allowed read-only check: {check}")
    policy = task.get("write_policy")
    if policy != "write result only under codex_tasks/done or codex_tasks/failed":
        errors.append("write_policy must restrict results to codex_tasks/done or codex_tasks/failed")
    return ValidationResult(ok=not errors, errors=tuple(errors))


def result_paths(mailbox_root: Path, task_id: str, status: str) -> tuple[Path, Path]:
    if status not in ALLOWED_RESULT_DIRS:
        raise ValueError(f"status must be one of {ALLOWED_RESULT_DIRS}")
    if any(part in task_id for part in ("/", "\\", "..")):
        raise ValueError("task_id must not contain path separators or '..'")
    result_dir = mailbox_root / status
    md_path = (result_dir / f"{task_id}.result.md").resolve()
    json_path = (result_dir / f"{task_id}.result.json").resolve()
    allowed_root = result_dir.resolve()
    if allowed_root not in md_path.parents or allowed_root not in json_path.parents:
        raise ValueError("result path escapes mailbox result directory")
    return md_path, json_path


def _run_check(check: str, *, dry_run: bool, cwd: Path) -> dict[str, Any]:
    if dry_run:
        return {"check": check, "status": "skipped", "dry_run": True, "stdout": "", "stderr": "", "returncode": None}

    if check == "read config/default/config.json settings.usb_split_keyboard":
        config = json.loads((cwd / "config" / "default" / "config.json").read_text(encoding="utf-8"))
        value = config.get("settings", {}).get("usb_split_keyboard")
        return {
            "check": check,
            "status": "ok",
            "stdout": json.dumps(value, ensure_ascii=False, sort_keys=True),
            "stderr": "",
            "returncode": 0,
        }

    argv = shlex.split(check)
    proc = subprocess.run(argv, cwd=str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, check=False)
    return {
        "check": check,
        "status": "ok" if proc.returncode == 0 else "failed",
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "returncode": proc.returncode,
    }


def write_result(mailbox_root: Path, task: dict[str, Any], status: str, result: dict[str, Any]) -> tuple[Path, Path]:
    md_path, json_path = result_paths(mailbox_root, str(task["id"]), status)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# {task['id']} result",
        "",
        f"- status: {status}",
        f"- summary: {task.get('summary', '')}",
        f"- generated_at: {result['generated_at']}",
        "",
        "## Checks",
        "",
    ]
    for item in result.get("checks", []):
        lines.extend(
            [
                f"### `{item['check']}`",
                "",
                f"- status: {item['status']}",
                f"- returncode: {item.get('returncode')}",
                "",
                "```text",
                item.get("stdout") or "",
                "```",
                "",
            ]
        )
        if item.get("stderr"):
            lines.extend(["stderr:", "", "```text", item["stderr"], "```", ""])

    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return md_path, json_path


def run_task(task_path: Path, *, mailbox_root: Path = DEFAULT_MAILBOX, dry_run: bool = False) -> dict[str, Any]:
    ensure_mailbox(mailbox_root)
    task = load_task(task_path)
    validation = validate_task(task)
    generated_at = datetime.now(timezone.utc).isoformat()
    status = "done" if validation.ok else "failed"

    if validation.ok:
        checks = [_run_check(check, dry_run=dry_run, cwd=ROOT) for check in task["checks"]]
        if any(item["status"] == "failed" for item in checks):
            status = "failed"
        result = {"task": task, "status": status, "generated_at": generated_at, "checks": checks, "errors": []}
    else:
        result = {"task": task, "status": status, "generated_at": generated_at, "checks": [], "errors": list(validation.errors)}

    md_path, json_path = write_result(mailbox_root, task, status, result)
    return {"status": status, "markdown": str(md_path), "json": str(json_path), "errors": result["errors"]}


def claim_next(mailbox_root: Path = DEFAULT_MAILBOX) -> Path | None:
    ensure_mailbox(mailbox_root)
    inbox = mailbox_root / "inbox"
    running = mailbox_root / "running"
    candidates = sorted(path for path in inbox.glob("*.json") if path.is_file())
    if not candidates:
        return None
    src = candidates[0]
    dst = running / src.name
    shutil.move(str(src), str(dst))
    return dst


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mailbox", type=Path, default=DEFAULT_MAILBOX)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--validate", type=Path, help="validate one task JSON")
    action.add_argument("--run", type=Path, help="run one task JSON and write result")
    action.add_argument("--run-next", action="store_true", help="claim the first inbox task and run it")
    parser.add_argument("--dry-run", action="store_true", help="write a result without executing checks")
    args = parser.parse_args(argv)

    if args.dry_run and not (args.run or args.run_next):
        parser.error("--dry-run requires --run or --run-next")
    if args.validate:
        task = load_task(args.validate)
        validation = validate_task(task)
        print(json.dumps({"ok": validation.ok, "errors": list(validation.errors)}, ensure_ascii=False, indent=2))
        return 0 if validation.ok else 1
    if args.run:
        print(json.dumps(run_task(args.run, mailbox_root=args.mailbox, dry_run=args.dry_run), ensure_ascii=False, indent=2))
        return 0
    if args.run_next:
        task_path = claim_next(args.mailbox)
        if task_path is None:
            print(json.dumps({"status": "idle", "message": "no inbox tasks"}, ensure_ascii=False))
            return 0
        print(json.dumps(run_task(task_path, mailbox_root=args.mailbox, dry_run=args.dry_run), ensure_ascii=False, indent=2))
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
