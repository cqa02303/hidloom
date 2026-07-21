#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
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


def create_plan(
    export_root: Path,
    repository: str,
    version: str | None,
    release_channel: str,
) -> dict[str, Any]:
    command = [
        "python3",
        str(export_root / "tools" / "public_sync_plan.py"),
        str(export_root),
        "--repository",
        repository,
        "--channel",
        release_channel,
    ]
    if version:
        command.extend(["--version", version])
    return json.loads(run(command, cwd=export_root).stdout)


def verify_readiness(export_root: Path, release_channel: str) -> dict[str, Any]:
    command = [
        "python3",
        str(export_root / "tools" / "public_release_readiness.py"),
        str(export_root),
        "--channel",
        release_channel,
    ]
    result = run(command, cwd=export_root)
    payload = json.loads(result.stdout)
    if not payload["ready"]:
        raise SystemExit("public export readiness failed")
    return payload


def validate_remote(remote: str, repository: str, allow_local_remote: bool) -> None:
    accepted = {
        f"git@github.com:{repository}.git",
        f"https://github.com/{repository}.git",
        f"https://github.com/{repository}",
    }
    if remote in accepted:
        return
    if allow_local_remote and "://" not in remote and not remote.startswith("git@"):
        return
    raise SystemExit(f"remote does not match approved repository {repository}: {remote}")


def ensure_empty_destination(path: Path) -> None:
    if path.exists() and any(path.iterdir()):
        raise SystemExit(f"sync worktree is not empty: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)


def replace_worktree(worktree: Path, export_root: Path) -> None:
    for child in worktree.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    for source in export_root.iterdir():
        if source.name == ".git":
            continue
        destination = worktree / source.name
        if source.is_symlink():
            destination.symlink_to(os.readlink(source))
        elif source.is_dir():
            shutil.copytree(source, destination, symlinks=True)
        else:
            shutil.copy2(source, destination)


def manifest_sha(root: Path) -> str:
    return hashlib.sha256((root / "PUBLIC_EXPORT_MANIFEST.json").read_bytes()).hexdigest()


def verify_committed_tree(worktree: Path) -> int:
    manifest = json.loads((worktree / "PUBLIC_EXPORT_MANIFEST.json").read_text(encoding="utf-8"))
    expected = {str(item["path"]) for item in manifest["files"]}
    expected.add("PUBLIC_EXPORT_MANIFEST.json")
    committed = {
        line
        for line in run(["git", "ls-tree", "-r", "--name-only", "HEAD"], cwd=worktree).stdout.splitlines()
        if line
    }
    if committed != expected:
        missing = sorted(expected - committed)
        unexpected = sorted(committed - expected)
        raise SystemExit(f"committed public tree mismatch: missing={missing} unexpected={unexpected}")
    return len(committed)


def execute(args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    export_root = args.export_root.resolve()
    worktree = args.worktree.resolve()
    validate_remote(args.remote, args.repository, args.allow_local_remote)
    ensure_empty_destination(worktree)

    existing = run(
        ["git", "ls-remote", "--exit-code", "--heads", args.remote, plan["branch"]],
        check=False,
    )
    if existing.returncode == 0:
        raise SystemExit(f"remote sync branch already exists: {plan['branch']}")
    if existing.returncode != 2:
        raise SystemExit(existing.stderr.strip() or "failed to inspect remote sync branch")

    run(["git", "clone", "--quiet", "--branch", args.base, "--single-branch", args.remote, str(worktree)])
    run(["git", "checkout", "-q", "-b", plan["branch"]], cwd=worktree)
    replace_worktree(worktree, export_root)
    copied_readiness = verify_readiness(worktree, args.channel)
    if manifest_sha(worktree) != plan["export_manifest_sha256"]:
        raise SystemExit("copied export manifest differs from sync plan")

    run(["git", "add", "-f", "-A"], cwd=worktree)
    status = run(["git", "status", "--porcelain"], cwd=worktree).stdout
    if not status:
        raise SystemExit("public sync contains no changes")
    message = f"Sync HIDloom v{plan['version']} from {plan['source_commit'][:12]}"
    run(
        [
            "git",
            "-c",
            "user.name=HIDloom Public Sync",
            "-c",
            "user.email=hidloom-sync.invalid",
            "commit",
            "-qm",
            message,
        ],
        cwd=worktree,
    )
    commit = run(["git", "rev-parse", "HEAD"], cwd=worktree).stdout.strip()
    committed_file_count = verify_committed_tree(worktree)
    run(["git", "push", "--quiet", "origin", f"HEAD:refs/heads/{plan['branch']}"], cwd=worktree)
    return {
        "schema": "hidloom.public-sync-result.v1",
        "executed": True,
        "repository": args.repository,
        "base": args.base,
        "branch": plan["branch"],
        "source_commit": plan["source_commit"],
        "release_channel": args.channel,
        "public_commit": commit,
        "committed_file_count": committed_file_count,
        "export_manifest_sha256": plan["export_manifest_sha256"],
        "pending_dispositions": copied_readiness["pending_dispositions"],
        "pushed": True,
        "draft_pr": "requested from public Public CI after branch validation",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely prepare and push a HIDloom public sync branch")
    parser.add_argument("export_root", type=Path)
    parser.add_argument("--repository", default="cqa02303/hidloom")
    parser.add_argument("--remote")
    parser.add_argument("--base", default="main")
    parser.add_argument("--version")
    parser.add_argument("--worktree", type=Path)
    parser.add_argument("--channel", choices=("source-public",), default="source-public")
    parser.add_argument("--allow-pending-pid", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--allow-local-remote", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    export_root = args.export_root.resolve()
    readiness = verify_readiness(export_root, args.channel)
    plan = create_plan(export_root, args.repository, args.version, args.channel)
    if not args.execute:
        print(
            json.dumps(
                {
                    "schema": "hidloom.public-sync-result.v1",
                    "executed": False,
                    "repository": args.repository,
                    "base": args.base,
                    "branch": plan["branch"],
                    "source_commit": plan["source_commit"],
                    "release_channel": args.channel,
                    "export_manifest_sha256": plan["export_manifest_sha256"],
                    "pending_dispositions": readiness["pending_dispositions"],
                    "pushed": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if not args.remote or not args.worktree:
        parser.error("--remote and --worktree are required with --execute")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository):
        parser.error("--repository must be OWNER/REPOSITORY")
    if args.base != "main":
        parser.error("--base must be main")
    print(json.dumps(execute(args, plan), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
