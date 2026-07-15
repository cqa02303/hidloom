#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def is_git_checkout(root: Path) -> bool:
    return (root / ".git").exists()


def run(
    command: list[str],
    cwd: Path,
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        worktree_fixture = workspace / "linked-worktree"
        worktree_fixture.mkdir()
        (worktree_fixture / ".git").write_text("gitdir: /tmp/fixture\n", encoding="utf-8")
        assert is_git_checkout(worktree_fixture)
        assert not is_git_checkout(workspace / "plain-export")
        export = workspace / "export" if is_git_checkout(ROOT) else ROOT
        remote = workspace / "public.git"
        worktree = workspace / "bootstrap-worktree"
        inspection = workspace / "inspection"
        rejected_worktree = workspace / "rejected-worktree"

        if export != ROOT:
            run(
                ["python3", str(ROOT / "tools/public_export.py"), str(export), "--draft"],
                ROOT,
            )
        helper = str(export / "tools/public_repository_bootstrap.py")
        plan = run(
            [
                "python3",
                helper,
                str(export),
                "--repository",
                "cqa02303/hidloom",
                "--allow-pending-pid",
            ],
            export,
        )
        plan_payload = json.loads(plan.stdout)
        assert plan_payload["executed"] is False
        assert plan_payload["branch"] == "main"
        assert plan_payload["candidate_version"] == "0.1.0"
        assert plan_payload["confirmation"] == "INITIALIZE cqa02303/hidloom"
        assert plan_payload["operations"] == [
            "verify the approved remote has no branches or tags",
            "create a local main commit containing only manifest-listed paths",
            "push main without force",
            "verify remote main resolves to the created commit",
        ]
        assert not worktree.exists()

        run(["git", "init", "-q", "--bare", str(remote)], workspace)
        rejected = run(
            [
                "python3",
                helper,
                str(export),
                "--repository",
                "cqa02303/hidloom",
                "--remote",
                str(remote),
                "--worktree",
                str(rejected_worktree),
                "--allow-pending-pid",
                "--allow-local-remote",
                "--execute",
                "--confirm",
                "INITIALIZE another/repository",
                "--author-name",
                "Public Fixture",
                "--author-email",
                "fixture@example.invalid",
            ],
            export,
            check=False,
        )
        assert rejected.returncode == 2
        assert "--execute requires --confirm" in rejected.stderr
        assert not rejected_worktree.exists()
        assert run(["git", "ls-remote", "--heads", str(remote)], workspace).stdout == ""

        nested_worktree = export / "nested-bootstrap-worktree"
        nested = run(
            [
                "python3",
                helper,
                str(export),
                "--repository",
                "cqa02303/hidloom",
                "--remote",
                str(remote),
                "--worktree",
                str(nested_worktree),
                "--allow-pending-pid",
                "--allow-local-remote",
                "--execute",
                "--confirm",
                "INITIALIZE cqa02303/hidloom",
                "--author-name",
                "Public Fixture",
                "--author-email",
                "fixture@example.invalid",
            ],
            export,
            check=False,
        )
        assert nested.returncode != 0
        assert "worktree must not be inside the public export" in nested.stderr
        assert not nested_worktree.exists()
        assert run(["git", "ls-remote", "--heads", str(remote)], workspace).stdout == ""

        missing_author = run(
            [
                "python3",
                helper,
                str(export),
                "--repository",
                "cqa02303/hidloom",
                "--remote",
                str(remote),
                "--worktree",
                str(rejected_worktree),
                "--allow-pending-pid",
                "--allow-local-remote",
                "--execute",
                "--confirm",
                "INITIALIZE cqa02303/hidloom",
            ],
            export,
            check=False,
        )
        assert missing_author.returncode == 2
        assert "--author-name is required" in missing_author.stderr
        assert not rejected_worktree.exists()
        assert run(["git", "ls-remote", "--heads", str(remote)], workspace).stdout == ""

        initialized = run(
            [
                "python3",
                helper,
                str(export),
                "--repository",
                "cqa02303/hidloom",
                "--remote",
                str(remote),
                "--worktree",
                str(worktree),
                "--allow-pending-pid",
                "--allow-local-remote",
                "--execute",
                "--confirm",
                "INITIALIZE cqa02303/hidloom",
                "--author-name",
                "Public Fixture",
                "--author-email",
                "fixture@example.invalid",
            ],
            export,
        )
        result = json.loads(initialized.stdout)
        assert result["executed"] is True
        assert result["pushed"] is True
        assert result["force_push"] is False
        assert result["branch"] == "main"
        assert result["author_name"] == "Public Fixture"
        assert len(result["public_commit"]) == 40
        assert result["committed_file_count"] > 1000

        run(["git", "clone", "-q", "--branch", "main", str(remote), str(inspection)], workspace)
        manifest = json.loads(
            (inspection / "PUBLIC_EXPORT_MANIFEST.json").read_text(encoding="utf-8")
        )
        expected = {str(item["path"]) for item in manifest["files"]}
        expected.add("PUBLIC_EXPORT_MANIFEST.json")
        tracked = set(
            run(["git", "ls-files"], inspection).stdout.splitlines()
        )
        assert tracked == expected
        assert result["committed_file_count"] == len(expected)
        assert run(["git", "status", "--porcelain"], inspection).stdout == ""
        assert run(["git", "log", "-1", "--format=%s"], inspection).stdout.startswith(
            "Publish HIDloom from "
        )
        assert run(["git", "log", "-1", "--format=%an <%ae>"], inspection).stdout == (
            "Public Fixture <fixture@example.invalid>\n"
        )
        readiness = run(
            [
                "python3",
                "tools/public_release_readiness.py",
                ".",
                "--allow-pending-pid",
            ],
            inspection,
            check=False,
        )
        assert readiness.returncode == 0, readiness.stdout + readiness.stderr
        assert json.loads(readiness.stdout)["ready"] is True

        duplicate = run(
            [
                "python3",
                helper,
                str(export),
                "--repository",
                "cqa02303/hidloom",
                "--remote",
                str(remote),
                "--worktree",
                str(workspace / "duplicate-worktree"),
                "--allow-pending-pid",
                "--allow-local-remote",
                "--execute",
                "--confirm",
                "INITIALIZE cqa02303/hidloom",
                "--author-name",
                "Public Fixture",
                "--author-email",
                "fixture@example.invalid",
            ],
            export,
            check=False,
        )
        assert duplicate.returncode != 0
        assert "public remote is not empty" in duplicate.stderr
        assert not (workspace / "duplicate-worktree").exists()

        tag_remote = workspace / "tag-only.git"
        tag_seed = workspace / "tag-seed"
        run(["git", "init", "-q", "-b", "main", str(tag_seed)], workspace)
        run(["git", "config", "user.name", "Tag Fixture"], tag_seed)
        run(["git", "config", "user.email", "tag@example.invalid"], tag_seed)
        (tag_seed / "seed.txt").write_text("tag only\n", encoding="utf-8")
        run(["git", "add", "seed.txt"], tag_seed)
        run(["git", "commit", "-qm", "Tag fixture"], tag_seed)
        run(["git", "tag", "v0-fixture"], tag_seed)
        run(["git", "init", "-q", "--bare", str(tag_remote)], workspace)
        run(["git", "remote", "add", "tag-only", str(tag_remote)], tag_seed)
        run(["git", "push", "-q", "tag-only", "refs/tags/v0-fixture"], tag_seed)
        tag_rejected = run(
            [
                "python3",
                helper,
                str(export),
                "--repository",
                "cqa02303/hidloom",
                "--remote",
                str(tag_remote),
                "--worktree",
                str(workspace / "tag-rejected-worktree"),
                "--allow-pending-pid",
                "--allow-local-remote",
                "--execute",
                "--confirm",
                "INITIALIZE cqa02303/hidloom",
                "--author-name",
                "Public Fixture",
                "--author-email",
                "fixture@example.invalid",
            ],
            export,
            check=False,
        )
        assert tag_rejected.returncode != 0
        assert "refs/tags/v0-fixture" in tag_rejected.stderr
        assert not (workspace / "tag-rejected-worktree").exists()

    print("ok: public bootstrap creates one manifest-bounded main commit on an empty remote")


if __name__ == "__main__":
    main()
