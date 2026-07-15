#!/usr/bin/env python3
"""Plan or explicitly publish the first manifest-bounded public main commit."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any

sys.dont_write_bytecode = True

from public_sync_branch import (  # noqa: E402
    ensure_empty_destination,
    run,
    validate_remote,
    verify_committed_tree,
    verify_readiness,
)


REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
EMAIL_RE = re.compile(r"[^\s@]+@[^\s@]+")


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def manifest_sha(root: Path) -> str:
    return hashlib.sha256((root / "PUBLIC_EXPORT_MANIFEST.json").read_bytes()).hexdigest()


def verify_repository_contract(export_root: Path, repository: str) -> None:
    policy = load_json(export_root / "config/public-repository-policy.json")
    if policy.get("repository") != repository:
        raise SystemExit(
            f"repository differs from public policy: expected={policy.get('repository')} actual={repository}"
        )
    if policy.get("repository_settings", {}).get("default_branch") != "main":
        raise SystemExit("public policy default branch must be main")


def verify_empty_remote(remote: str) -> None:
    result = run(["git", "ls-remote", "--heads", "--tags", remote], check=False)
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or f"cannot inspect public remote: {remote}")
    references = [line for line in result.stdout.splitlines() if line.strip()]
    if references:
        names = [line.split("\t", 1)[-1] for line in references[:5]]
        raise SystemExit(f"public remote is not empty: {names}")


def copy_export(export_root: Path, worktree: Path) -> None:
    if (export_root / ".git").exists():
        raise SystemExit("public export must not contain .git")
    for source in export_root.iterdir():
        destination = worktree / source.name
        if source.is_symlink():
            destination.symlink_to(os.readlink(source))
        elif source.is_dir():
            shutil.copytree(source, destination, symlinks=True)
        else:
            shutil.copy2(source, destination)


def verify_index_tree(worktree: Path) -> int:
    manifest = load_json(worktree / "PUBLIC_EXPORT_MANIFEST.json")
    expected = {str(item["path"]) for item in manifest["files"]}
    expected.add("PUBLIC_EXPORT_MANIFEST.json")
    indexed = {
        line
        for line in run(["git", "ls-files"], cwd=worktree).stdout.splitlines()
        if line
    }
    if indexed != expected:
        missing = sorted(expected - indexed)
        unexpected = sorted(indexed - expected)
        raise SystemExit(
            f"indexed public tree mismatch: missing={missing} unexpected={unexpected}"
        )
    return len(indexed)


def create_plan(
    export_root: Path,
    repository: str,
    readiness: dict[str, Any],
) -> dict[str, Any]:
    report = load_json(export_root / "PUBLIC_EXPORT_REPORT.json")
    confirmation = f"INITIALIZE {repository}"
    return {
        "schema": "hidloom.public-repository-bootstrap-plan.v1",
        "executed": False,
        "repository": repository,
        "branch": "main",
        "source_commit": report["source_provenance"]["base_commit"],
        "candidate_version": report["initial_version"],
        "export_manifest_sha256": manifest_sha(export_root),
        "pending_dispositions": readiness["pending_dispositions"],
        "confirmation": confirmation,
        "requirements": [
            "create the GitHub repository as public and completely empty",
            "do not initialize README, LICENSE, or .gitignore on GitHub",
            "use a repository-scoped credential with write access",
            "choose an intentional public commit author name and email",
        ],
        "operations": [
            "verify the approved remote has no branches or tags",
            "create a local main commit containing only manifest-listed paths",
            "push main without force",
            "verify remote main resolves to the created commit",
        ],
    }


def execute(
    export_root: Path,
    repository: str,
    remote: str,
    worktree: Path,
    allow_pending_pid: bool,
    allow_local_remote: bool,
    author_name: str,
    author_email: str,
    plan: dict[str, Any],
) -> dict[str, Any]:
    if worktree == export_root or export_root in worktree.parents:
        raise SystemExit("bootstrap worktree must not be inside the public export")
    validate_remote(remote, repository, allow_local_remote)
    verify_empty_remote(remote)
    ensure_empty_destination(worktree)
    run(["git", "init", "-q", "-b", "main", str(worktree)])
    run(["git", "remote", "add", "origin", remote], cwd=worktree)
    copy_export(export_root, worktree)
    copied_readiness = verify_readiness(worktree, allow_pending_pid)
    if manifest_sha(worktree) != plan["export_manifest_sha256"]:
        raise SystemExit("copied export manifest differs from bootstrap plan")

    run(["git", "add", "-f", "-A"], cwd=worktree)
    indexed_file_count = verify_index_tree(worktree)
    message = f"Publish HIDloom from {plan['source_commit'][:12]}"
    run(
        [
            "git",
            "-c",
            f"user.name={author_name}",
            "-c",
            f"user.email={author_email}",
            "commit",
            "-qm",
            message,
        ],
        cwd=worktree,
    )
    public_commit = run(["git", "rev-parse", "HEAD"], cwd=worktree).stdout.strip()
    committed_file_count = verify_committed_tree(worktree)
    if committed_file_count != indexed_file_count:
        raise SystemExit("indexed and committed public file counts differ")
    if run(["git", "status", "--porcelain"], cwd=worktree).stdout:
        raise SystemExit("bootstrap worktree changed while creating initial commit")

    run(["git", "push", "--quiet", "origin", "HEAD:refs/heads/main"], cwd=worktree)
    remote_main = run(
        ["git", "ls-remote", "--heads", remote, "refs/heads/main"]
    ).stdout.split()
    if not remote_main or remote_main[0] != public_commit:
        raise SystemExit("remote main does not match the bootstrap commit")
    return {
        "schema": "hidloom.public-repository-bootstrap-result.v1",
        "executed": True,
        "repository": repository,
        "branch": "main",
        "source_commit": plan["source_commit"],
        "candidate_version": plan["candidate_version"],
        "public_commit": public_commit,
        "author_name": author_name,
        "committed_file_count": committed_file_count,
        "export_manifest_sha256": plan["export_manifest_sha256"],
        "pending_dispositions": copied_readiness["pending_dispositions"],
        "pushed": True,
        "force_push": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_root", type=Path)
    parser.add_argument("--repository", default="cqa02303/hidloom")
    parser.add_argument("--remote")
    parser.add_argument("--worktree", type=Path)
    parser.add_argument("--allow-pending-pid", action="store_true")
    parser.add_argument("--author-name")
    parser.add_argument("--author-email")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--allow-local-remote", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    export_root = args.export_root.resolve()
    if not REPOSITORY_RE.fullmatch(args.repository):
        parser.error("--repository must be OWNER/REPOSITORY")
    verify_repository_contract(export_root, args.repository)
    readiness = verify_readiness(export_root, args.allow_pending_pid)
    plan = create_plan(export_root, args.repository, readiness)
    if not args.execute:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return

    confirmation = plan["confirmation"]
    if args.confirm != confirmation:
        parser.error(f"--execute requires --confirm {confirmation!r}")
    if not args.remote or not args.worktree:
        parser.error("--remote and --worktree are required with --execute")
    if not args.author_name or "\n" in args.author_name or "\r" in args.author_name:
        parser.error("--author-name is required with --execute and must be one line")
    if not args.author_email or not EMAIL_RE.fullmatch(args.author_email):
        parser.error("--author-email is required with --execute and must be an email address")
    result = execute(
        export_root,
        args.repository,
        args.remote,
        args.worktree.resolve(),
        args.allow_pending_pid,
        args.allow_local_remote,
        args.author_name,
        args.author_email,
        plan,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
