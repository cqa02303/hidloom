#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

sys.dont_write_bytecode = True

from public_export_manifest import verify as verify_export_manifest
from public_release_bundle import SOURCE_PUBLIC_CHANNEL, load_release_channel_policy


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a non-mutating HIDloom public sync plan")
    parser.add_argument("export_root", type=Path)
    parser.add_argument("--repository", default="cqa02303/hidloom")
    parser.add_argument("--version")
    parser.add_argument("--channel", choices=(SOURCE_PUBLIC_CHANNEL,), default=SOURCE_PUBLIC_CHANNEL)
    parser.add_argument("--allow-pending-pid", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = args.export_root.resolve()
    report = load_json(root / "PUBLIC_EXPORT_REPORT.json")
    channel_policy = load_release_channel_policy(root)
    verification = verify_export_manifest(root)
    if not verification["ready"]:
        details = verification["mismatches"] + verification["source_provenance_issues"]
        raise SystemExit("public export verification failed: " + ", ".join(details))
    required = [item for item in report["findings"] if item["disposition"].endswith("_required")]
    allowed = {"pid_codes_migration_required"}
    unexpected = [item for item in required if item["disposition"] not in allowed]
    if unexpected:
        raise SystemExit("public export contains unexpected action-required findings")
    version = args.version or report["initial_version"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", version):
        raise SystemExit(f"invalid version: {version}")
    commit = verification["source_provenance"]["base_commit"]
    manifest_path = root / "PUBLIC_EXPORT_MANIFEST.json"
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    branch = f"sync/v{version}-{commit[:12]}"
    payload = {
        "schema": "hidloom.public-sync-plan.v2",
        "release_channel": args.channel,
        "release_channel_policy_schema": channel_policy["schema"],
        "dry_run": True,
        "source_commit": commit,
        "version": version,
        "repository": args.repository,
        "branch": branch,
        "export_manifest_sha256": manifest_sha256,
        "pending_dispositions": sorted({item["disposition"] for item in required}),
        "commands": [
            f"git -C {root} init",
            f"git -C {root} checkout -b {branch}",
            f"git -C {root} add -f -A",
            f"git -C {root} commit -m 'Sync HIDloom v{version} from {commit[:12]}'",
            f"git -C {root} remote add public git@github.com:{args.repository}.git",
            f"git -C {root} push public {branch}",
            f"gh pr create --repo {args.repository} --head {branch} --base main --draft",
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
