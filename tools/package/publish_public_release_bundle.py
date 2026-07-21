#!/usr/bin/env python3
"""Plan or create a guarded draft GitHub Release from a public bundle."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPOSITORY = "cqa02303/hidloom"
SAFE_TAG = re.compile(r"^v[A-Za-z0-9][A-Za-z0-9._+~-]*$")


def run(command: list[str], *, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"invalid JSON file: {path}: {error}") from error
    if not isinstance(payload, dict):
        raise SystemExit(f"JSON root must be an object: {path}")
    return payload


def git_value(arguments: list[str]) -> str | None:
    result = run(["git", *arguments])
    return result.stdout.strip() if result.returncode == 0 else None


def canonical_origin(repository: str) -> bool:
    origin = git_value(["remote", "get-url", "origin"])
    if not origin:
        return False
    accepted = {
        f"https://github.com/{repository}",
        f"https://github.com/{repository}.git",
        f"git@github.com:{repository}",
        f"git@github.com:{repository}.git",
        f"ssh://git@github.com/{repository}",
        f"ssh://git@github.com/{repository}.git",
    }
    return origin in accepted


def checksum_assets(bundle: Path) -> list[Path]:
    checksum = bundle / "SHA256SUMS"
    names: list[str] = []
    for line in checksum.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"[0-9a-f]{64}  ([A-Za-z0-9._+~-]+)", line)
        if not match:
            raise SystemExit("SHA256SUMS contains an invalid entry")
        name = match.group(1)
        if name in names:
            raise SystemExit(f"SHA256SUMS contains a duplicate entry: {name}")
        names.append(name)
    return [*(bundle / name for name in names), checksum]


def verify_local_bundle(bundle: Path) -> None:
    verifier = ROOT / "tools" / "package" / "verify_github_public_release_bundle.py"
    result = run([sys.executable, str(verifier), "--bundle", str(bundle)])
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or result.stdout.strip())


def build_plan(bundle: Path, repository: str, tag: str) -> dict[str, Any]:
    verify_local_bundle(bundle)
    manifest = load_json(bundle / "RELEASE_MANIFEST.json")
    assets = checksum_assets(bundle)
    blockers: list[str] = []
    channels = manifest.get("release_channels") or {}
    selected_channel = channels.get("selected")
    stable_status = (channels.get("statuses") or {}).get("stable-public") or {}
    if selected_channel != "stable-public":
        blockers.append("release-channel-not-stable-public")
    if not stable_status.get("ready"):
        blockers.extend(
            f"release-channel:{item}" for item in stable_status.get("blockers", [])
        )
    source_commit = str(manifest.get("source", {}).get("commit", ""))
    head = git_value(["rev-parse", "HEAD"])
    if head is None:
        blockers.append("not-a-git-checkout")
    elif source_commit != head:
        blockers.append("bundle-source-does-not-match-head")
    status = git_value(["status", "--porcelain=v1", "--untracked-files=normal"])
    if status is None:
        if "not-a-git-checkout" not in blockers:
            blockers.append("git-status-unavailable")
    elif status:
        blockers.append("git-worktree-not-clean")
    if not canonical_origin(repository):
        blockers.append("origin-is-not-public-repository")
    notes = bundle / "RELEASE_NOTES.md"
    command = [
        "gh",
        "release",
        "create",
        tag,
        *(str(path) for path in assets),
        "--repo",
        repository,
        "--target",
        source_commit,
        "--draft",
        "--prerelease",
        "--title",
        f"HIDloom {manifest['version']}",
        "--notes-file",
        str(notes),
    ]
    return {
        "schema": "hidloom.public-release-publish-plan.v2",
        "ready": not blockers,
        "blockers": blockers,
        "repository": repository,
        "tag": tag,
        "bundle": str(bundle),
        "version": manifest["version"],
        "source_commit": source_commit,
        "release_channel": selected_channel,
        "asset_count": len(assets),
        "asset_bytes": sum(path.stat().st_size for path in assets),
        "assets": [path.name for path in assets],
        "confirmation": f"CREATE DRAFT {repository} {tag}",
        "command": command,
    }


def online_preflight(plan: dict[str, Any]) -> None:
    if shutil.which("gh") is None:
        raise SystemExit("missing command: gh")
    repository = plan["repository"]
    viewed = run(["gh", "repo", "view", repository, "--json", "nameWithOwner,visibility"])
    if viewed.returncode != 0:
        raise SystemExit(viewed.stderr.strip() or "cannot inspect public repository")
    metadata = json.loads(viewed.stdout)
    if metadata.get("nameWithOwner") != repository or metadata.get("visibility") != "PUBLIC":
        raise SystemExit("release target is not the canonical public repository")
    commit = run(["gh", "api", f"repos/{repository}/commits/{plan['source_commit']}", "--jq", ".sha"])
    if commit.returncode != 0 or commit.stdout.strip() != plan["source_commit"]:
        raise SystemExit("bundle source commit is not available in the public repository")
    existing = run(["gh", "release", "view", plan["tag"], "--repo", repository])
    if existing.returncode == 0:
        raise SystemExit(f"GitHub Release already exists: {plan['tag']}")
    existing_tag = run(["gh", "api", f"repos/{repository}/git/ref/tags/{plan['tag']}"])
    if existing_tag.returncode == 0:
        raise SystemExit(f"Git tag already exists: {plan['tag']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle", type=Path, default=ROOT / "build" / "zero2w-keyboard-release"
    )
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--tag")
    parser.add_argument("--output-plan", type=Path)
    parser.add_argument("--require-ready", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    if "/" not in args.repository:
        parser.error("--repository must use OWNER/REPO form")
    bundle = args.bundle.resolve()
    manifest = load_json(bundle / "RELEASE_MANIFEST.json")
    tag = args.tag or f"v{manifest.get('version', '')}"
    if not SAFE_TAG.fullmatch(tag):
        parser.error(f"unsafe release tag: {tag}")
    plan = build_plan(bundle, args.repository, tag)
    if args.output_plan:
        args.output_plan.resolve().parent.mkdir(parents=True, exist_ok=True)
        args.output_plan.resolve().write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    print(f"public release draft plan: {plan['tag']}")
    print(f"repository: {plan['repository']}")
    print(f"source: {plan['source_commit']}")
    print(f"channel: {plan['release_channel']}")
    print(f"assets: {plan['asset_count']} ({plan['asset_bytes']} bytes)")
    print(f"ready: {str(plan['ready']).lower()}")
    for blocker in plan["blockers"]:
        print(f"blocker: {blocker}")
    print("command:")
    print(f"  {shlex.join(plan['command'])}")

    if args.require_ready and not plan["ready"]:
        raise SystemExit("public release draft plan is not ready")
    if not args.execute:
        print("dry-run only; pass --execute with the exact confirmation to create a draft")
        return
    if not plan["ready"]:
        raise SystemExit("refusing to create a draft while release blockers remain")
    if args.confirm != plan["confirmation"]:
        raise SystemExit(f"execution requires --confirm {shlex.quote(plan['confirmation'])}")
    online_preflight(plan)
    created = run(plan["command"])
    if created.returncode != 0:
        raise SystemExit(created.stderr.strip() or created.stdout.strip())
    verifier = ROOT / "tools" / "package" / "verify_github_public_release_bundle.py"
    verified = run(
        [
            sys.executable,
            str(verifier),
            "--tag",
            plan["tag"],
            "--repository",
            plan["repository"],
        ]
    )
    if verified.returncode != 0:
        raise SystemExit(verified.stderr.strip() or verified.stdout.strip())
    print(f"created and verified draft prerelease: {plan['tag']}")


if __name__ == "__main__":
    main()
