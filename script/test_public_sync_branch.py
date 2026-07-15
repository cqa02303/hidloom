#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def main() -> None:
    private_workflow_path = ROOT / ".github/workflows/public-sync.yml"
    public_workflow = (ROOT / ".github/workflows/public-ci.yml").read_text(encoding="utf-8")
    if private_workflow_path.exists():
        private_workflow = private_workflow_path.read_text(encoding="utf-8")
        assert "environment: public-sync" in private_workflow
        assert "PUBLIC_SYNC_DEPLOY_KEY" in private_workflow
        assert "PUBLIC_SYNC_KNOWN_HOSTS" in private_workflow
        assert 'test "$CONFIRMATION" = "SYNC $APPROVED_REPOSITORY"' in private_workflow
        assert "--allow-dirty-source" not in private_workflow
    assert "pull-requests: write" in public_workflow
    assert "GH_REPO:" in public_workflow
    assert "gh pr create" in public_workflow
    assert "--draft" in public_workflow

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        export = workspace / "export"
        seed = workspace / "seed"
        remote = workspace / "public.git"
        worktree = workspace / "sync-worktree"
        inspection = workspace / "inspection"

        run(["python3", str(ROOT / "tools/public_export.py"), str(export), "--draft"], ROOT)
        seed.mkdir()
        run(["git", "init", "-q", "-b", "main"], seed)
        run(["git", "config", "user.name", "Public Fixture"], seed)
        run(["git", "config", "user.email", "fixture@localhost"], seed)
        (seed / "README.md").write_text("old public tree\n", encoding="utf-8")
        (seed / "obsolete-private-note.txt").write_text("remove me\n", encoding="utf-8")
        run(["git", "add", "-A"], seed)
        run(["git", "commit", "-qm", "Initial public tree"], seed)
        run(["git", "init", "-q", "--bare", str(remote)], workspace)
        run(["git", "remote", "add", "public", str(remote)], seed)
        run(["git", "push", "-q", "public", "main"], seed)

        helper = str(export / "tools/public_sync_branch.py")
        dry = run(
            [helper, str(export), "--repository", "cqa02303/hidloom", "--allow-pending-pid"],
            export,
        )
        dry_payload = json.loads(dry.stdout)
        assert dry_payload["executed"] is False
        assert dry_payload["pushed"] is False
        assert dry_payload["branch"].startswith("sync/v0.1.0-")
        assert not worktree.exists()
        assert not any(export.rglob("__pycache__"))

        executed = run(
            [
                helper,
                str(export),
                "--repository",
                "cqa02303/hidloom",
                "--remote",
                str(remote),
                "--base",
                "main",
                "--worktree",
                str(worktree),
                "--allow-pending-pid",
                "--allow-local-remote",
                "--execute",
            ],
            export,
            check=False,
        )
        assert executed.returncode == 0, executed.stdout + executed.stderr
        result = json.loads(executed.stdout)
        assert result["executed"] is True
        assert result["pushed"] is True
        assert len(result["public_commit"]) == 40
        assert result["committed_file_count"] > 1000

        run(["git", "clone", "-q", "--branch", result["branch"], str(remote), str(inspection)], workspace)
        assert (inspection / "PUBLIC_EXPORT_MANIFEST.json").is_file()
        assert not (inspection / "obsolete-private-note.txt").exists()
        readiness = run(
            ["python3", "tools/public_release_readiness.py", ".", "--allow-pending-pid"],
            inspection,
            check=False,
        )
        assert readiness.returncode == 0, readiness.stdout + readiness.stderr
        assert json.loads(readiness.stdout)["ready"] is True
        assert run(["git", "show", "main:README.md"], seed).stdout == "old public tree\n"

        duplicate = run(
            [
                helper,
                str(export),
                "--repository",
                "cqa02303/hidloom",
                "--remote",
                str(remote),
                "--worktree",
                str(workspace / "duplicate"),
                "--allow-pending-pid",
                "--allow-local-remote",
                "--execute",
            ],
            export,
            check=False,
        )
        assert duplicate.returncode != 0
        assert "remote sync branch already exists" in duplicate.stderr

    print("ok: public sync pushes an isolated branch and preserves main")


if __name__ == "__main__":
    main()
