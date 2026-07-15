#!/usr/bin/env python3
"""Regression checks for the Codex task mailbox helper."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import codex_task_mailbox as mailbox  # noqa: E402

TOOL = ROOT / "tools" / "codex_task_mailbox.py"
TOOLS_README = ROOT / "tools" / "README.md"

VALID_TASK = {
    "version": 1,
    "id": "real-device-preflight-20260613-120000",
    "mode": "read_only",
    "requested_by": "desktop-codex",
    "summary": "JIS main / US sub split and service health preflight",
    "checks": [
        "systemctl is-active hidloom-usb-gadget viald hidloom-hidd hidloom-uidd hidloom-outputd hidloom-logicd-core logicd-companion matrixd ledd i2cd httpd btd",
        "ls -l /dev/hidg0 /dev/hidg1 /dev/hidg2",
        "ls -l /tmp/usbd_hid_reports.sock /tmp/matrix_events.sock /tmp/ledd_events.sock",
        "read config/default/config.json settings.usb_split_keyboard",
    ],
    "write_policy": "write result only under codex_tasks/done or codex_tasks/failed",
}


def test_valid_task_schema() -> None:
    validation = mailbox.validate_task(dict(VALID_TASK))
    assert validation.ok, validation.errors


def test_rejects_write_mode_and_dangerous_checks() -> None:
    task = dict(VALID_TASK)
    task["mode"] = "write"
    task["checks"] = [
        "systemctl restart logicd",
        "git status",
        "pnputil /add-driver driver.inf /install",
        "rm -rf /tmp/anything",
    ]
    validation = mailbox.validate_task(task)
    assert not validation.ok
    text = "\n".join(validation.errors)
    assert "mode must be read_only" in text
    assert "systemctl restart logicd" in text
    assert "git status" in text
    assert "pnputil" in text
    assert "rm -rf" in text


def test_rejects_result_path_escape() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        mailbox.ensure_mailbox(root)
        try:
            mailbox.result_paths(root, "../escape", "done")
        except ValueError as exc:
            assert "task_id" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("path escape was accepted")

        try:
            mailbox.result_paths(root, "task", "running")
        except ValueError as exc:
            assert "status" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("non-result status was accepted")


def test_dry_run_writes_done_result() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "mailbox"
        mailbox.ensure_mailbox(root)
        task_path = root / "inbox" / "task.json"
        task_path.write_text(json.dumps(VALID_TASK), encoding="utf-8")

        result = mailbox.run_task(task_path, mailbox_root=root, dry_run=True)
        assert result["status"] == "done", result
        md_path = Path(result["markdown"])
        json_path = Path(result["json"])
        assert md_path.exists()
        assert json_path.exists()
        assert root / "done" in md_path.parents
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert payload["checks"][0]["status"] == "skipped"
        assert payload["checks"][0]["dry_run"] is True


def test_run_next_claims_inbox_task() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "mailbox"
        mailbox.ensure_mailbox(root)
        task_path = root / "inbox" / "task.json"
        task_path.write_text(json.dumps(VALID_TASK), encoding="utf-8")
        claimed = mailbox.claim_next(root)
        assert claimed == root / "running" / "task.json"
        assert claimed.exists()
        assert not task_path.exists()


def run_cli(arguments: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), *arguments],
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_cli_and_public_documentation_match() -> None:
    help_result = run_cli(["--help"])
    for option in ("--mailbox", "--validate", "--run", "--run-next", "--dry-run"):
        assert option in help_result.stdout

    readme = TOOLS_README.read_text(encoding="utf-8")
    section = readme.split("## codex_task_mailbox.py", 1)[1].split("\n## ", 1)[0]
    for command in (
        "python3 tools/codex_task_mailbox.py --validate /path/to/task.json",
        "python3 tools/codex_task_mailbox.py --mailbox /path/to/codex_tasks --run /path/to/task.json --dry-run",
        "python3 tools/codex_task_mailbox.py --mailbox /path/to/codex_tasks --run-next --dry-run",
    ):
        assert command in section
    assert "add-note" not in section
    assert "codex_task_mailbox.py list" not in section
    assert "JSONL" not in section

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "mailbox"
        task_path = Path(tmp) / "task.json"
        task_path.write_text(json.dumps(VALID_TASK), encoding="utf-8")

        validation = json.loads(
            run_cli(["--mailbox", str(root), "--validate", str(task_path)]).stdout
        )
        assert validation == {"ok": True, "errors": []}
        assert not root.exists(), "validation unexpectedly created mailbox state"

        result = json.loads(
            run_cli(
                ["--mailbox", str(root), "--run", str(task_path), "--dry-run"]
            ).stdout
        )
        assert result["status"] == "done"
        assert all((root / dirname).is_dir() for dirname in mailbox.REQUIRED_DIRS)

        next_path = root / "inbox" / "next.json"
        next_task = dict(VALID_TASK, id="next-task")
        next_path.write_text(json.dumps(next_task), encoding="utf-8")
        next_result = json.loads(
            run_cli(["--mailbox", str(root), "--run-next", "--dry-run"]).stdout
        )
        assert next_result["status"] == "done"
        assert not next_path.exists()

        conflict = run_cli(
            ["--validate", str(task_path), "--run", str(task_path)], check=False
        )
        assert conflict.returncode == 2
        assert "not allowed with argument" in conflict.stderr

        invalid_dry_run = run_cli(["--dry-run"], check=False)
        assert invalid_dry_run.returncode == 2
        assert "requires --run or --run-next" in invalid_dry_run.stderr


def test_private_repo_samples_are_valid_when_present() -> None:
    sample = ROOT / "codex_tasks" / "inbox" / "example-read-only-preflight.task.json.sample"
    if not sample.exists():
        return
    task = json.loads(sample.read_text(encoding="utf-8"))
    validation = mailbox.validate_task(task)
    assert validation.ok, validation.errors

    result_json = ROOT / "codex_tasks" / "done" / "example-read-only-preflight.result.json.sample"
    result_markdown = ROOT / "codex_tasks" / "done" / "example-read-only-preflight.result.md.sample"
    result = json.loads(result_json.read_text(encoding="utf-8"))
    markdown = result_markdown.read_text(encoding="utf-8")
    assert result["task"] == task
    assert [item["check"] for item in result["checks"]] == task["checks"]
    assert all(f"### `{check}`" in markdown for check in task["checks"])

    readme = (ROOT / "codex_tasks" / "README.md").read_text(encoding="utf-8")
    assert "The initial policy is read-only only" in readme
    assert "does not edit docs, config, systemd units, or git" in readme


def main() -> None:
    test_valid_task_schema()
    test_rejects_write_mode_and_dangerous_checks()
    test_rejects_result_path_escape()
    test_dry_run_writes_done_result()
    test_run_next_claims_inbox_task()
    test_cli_and_public_documentation_match()
    test_private_repo_samples_are_valid_when_present()
    print("ok: Codex task mailbox")


if __name__ == "__main__":
    main()
