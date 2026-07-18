#!/usr/bin/env python3
"""Verify a merged pid.codes request and stage the HIDloom allocation state."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from pid_codes_application import (
    check_canonical_upstream,
    device_page,
    org_page,
    validate as validate_application,
)
from public_usb_identity import (
    CONTRACT_PATH,
    ContractError,
    validate_contract,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "hidloom.pid-codes-allocation-plan.v1"
CANONICAL_REPOSITORY = "pidcodes/pidcodes.github.com"
COMMIT_RE = re.compile(r"[0-9a-f]{40}")


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"JSON root must be an object: {path}")
    return payload


def normalize_merged_at(value: object) -> str:
    text = str(value)
    try:
        timestamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise SystemExit(f"pid.codes mergedAt is invalid: {text or '<missing>'}")
    if timestamp.tzinfo is None:
        raise SystemExit("pid.codes mergedAt must include a timezone")
    return timestamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_pull_request(application: dict[str, Any]) -> dict[str, Any]:
    number = application["pull_request_number"]
    command = [
        "gh",
        "pr",
        "view",
        str(number),
        "--repo",
        CANONICAL_REPOSITORY,
        "--json",
        "state,isDraft,headRefOid,mergedAt,mergeCommit,url,statusCheckRollup",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True)
    except FileNotFoundError:
        raise SystemExit("gh CLI is required to verify the pid.codes pull request")
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise SystemExit(f"pid.codes pull request query failed: {detail}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise SystemExit("pid.codes pull request query returned invalid JSON")
    if not isinstance(payload, dict):
        raise SystemExit("pid.codes pull request query did not return an object")
    if payload.get("url") != application["pull_request_url"]:
        raise SystemExit("pid.codes pull request URL does not match recorded evidence")
    if payload.get("headRefOid") != application["head_commit"]:
        raise SystemExit("pid.codes pull request head does not match recorded evidence")
    if payload.get("isDraft") is not False:
        raise SystemExit("pid.codes pull request is still a draft")
    if payload.get("state") != "MERGED":
        raise SystemExit(
            "pid.codes pull request is not merged: "
            f"state={payload.get('state', '<missing>')}"
        )
    merge_commit_payload = payload.get("mergeCommit")
    merge_commit = (
        merge_commit_payload.get("oid")
        if isinstance(merge_commit_payload, dict)
        else None
    )
    if not COMMIT_RE.fullmatch(str(merge_commit or "")):
        raise SystemExit("pid.codes pull request merge commit is missing or invalid")
    merged_at = normalize_merged_at(payload.get("mergedAt"))

    check_rollup = payload.get("statusCheckRollup")
    if not isinstance(check_rollup, list):
        raise SystemExit("pid.codes pull request check rollup is missing")
    observed_outcomes: dict[str, list[str]] = {}
    for check in check_rollup:
        if not isinstance(check, dict):
            continue
        name = check.get("name") or check.get("context")
        outcome = check.get("conclusion") or check.get("state")
        if isinstance(name, str) and isinstance(outcome, str):
            observed_outcomes.setdefault(name, []).append(outcome.upper())
    required_checks = application["required_checks"]
    missing = [name for name in required_checks if name not in observed_outcomes]
    failed = [
        f"{name}={','.join(observed_outcomes[name])}"
        for name in required_checks
        if name in observed_outcomes
        and any(outcome != "SUCCESS" for outcome in observed_outcomes[name])
    ]
    if missing:
        raise SystemExit(
            "pid.codes pull request required checks are missing: " + ", ".join(missing)
        )
    if failed:
        raise SystemExit(
            "pid.codes pull request required checks are not successful: "
            + ", ".join(failed)
        )
    return {
        "number": number,
        "url": payload["url"],
        "state": payload["state"],
        "head_commit": payload["headRefOid"],
        "merge_commit": merge_commit,
        "merged_at": merged_at,
        "required_checks": {name: "SUCCESS" for name in required_checks},
    }


def require_tracked_file(upstream: Path, relative: str) -> Path:
    path = upstream / relative
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"pid.codes allocated path is not a regular file: {relative}")
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative],
        cwd=upstream,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"pid.codes allocated path is not tracked: {relative}")
    return path


def check_allocated_upstream(
    plan: dict[str, Any], upstream: Path, pull_request: dict[str, Any]
) -> dict[str, Any]:
    upstream_check = check_canonical_upstream(plan, upstream)
    candidate_relative = plan["candidate"]["path"]
    owner_relative = plan["owner_path"]
    candidate_path = require_tracked_file(upstream, candidate_relative)
    owner_path = require_tracked_file(upstream, owner_relative)
    expected_candidate = device_page(plan)
    expected_owner = org_page(plan)
    candidate_text = candidate_path.read_text(encoding="utf-8")
    owner_text = owner_path.read_text(encoding="utf-8")
    if candidate_text != expected_candidate:
        raise SystemExit("pid.codes allocated device page does not match the approved application")
    if owner_text != expected_owner:
        raise SystemExit("pid.codes owner page does not match the approved application")
    ancestor = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            pull_request["merge_commit"],
            upstream_check["commit"],
        ],
        cwd=upstream,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0:
        raise SystemExit(
            "pid.codes pull request merge commit is not reachable from canonical HEAD"
        )
    upstream_check.update(
        {
            "candidate_path": candidate_relative,
            "candidate_path_present": True,
            "candidate_sha256": hashlib.sha256(
                candidate_text.encode("utf-8")
            ).hexdigest(),
            "owner_path": owner_relative,
            "owner_path_present": True,
            "owner_sha256": hashlib.sha256(owner_text.encode("utf-8")).hexdigest(),
            "content_verified": True,
            "merge_commit_reachable": True,
        }
    )
    return upstream_check


def build_proposed_contract(
    root: Path,
    contract: dict[str, Any],
    application: dict[str, Any],
    pull_request: dict[str, Any],
    upstream_check: dict[str, Any],
) -> dict[str, Any]:
    proposed = copy.deepcopy(contract)
    assignment = proposed["assignment"]
    assignment["status"] = "assigned"
    assignment["allocation_evidence"] = {
        "merged_date": pull_request["merged_at"][:10],
        "merged_at": pull_request["merged_at"],
        "upstream_commit": upstream_check["commit"],
        "origin_head_ref": upstream_check["origin_head_ref"],
        "remote_head_commit": upstream_check["remote_head_commit"],
        "checkout_clean": upstream_check["checkout_clean"],
        "head_matches_origin_head": upstream_check["head_matches_origin_head"],
        "origin_head_matches_remote_head": upstream_check[
            "origin_head_matches_remote_head"
        ],
        "pull_request_number": pull_request["number"],
        "pull_request_url": pull_request["url"],
        "pull_request_head": pull_request["head_commit"],
        "merge_commit": pull_request["merge_commit"],
        "merge_commit_reachable": upstream_check["merge_commit_reachable"],
        "required_checks": pull_request["required_checks"],
        "candidate_path": application["candidate_path"],
        "candidate_path_present": upstream_check["candidate_path_present"],
        "owner_path": application["owner_path"],
        "owner_path_present": upstream_check["owner_path_present"],
        "content_verified": upstream_check["content_verified"],
    }
    formal = proposed["profiles"]["public_formal"]
    formal["status"] = "assigned-ready"
    formal["public_release_allowed"] = True
    try:
        validate_contract(root, contract=proposed)
    except ContractError as exc:
        raise SystemExit(
            "proposed public USB identity validation failed:\n- "
            + "\n- ".join(exc.issues)
        )
    return proposed


def write_contract(root: Path, original: bytes, proposed: dict[str, Any]) -> None:
    destination = root / CONTRACT_PATH
    if destination.read_bytes() != original:
        raise SystemExit("public USB identity changed during allocation verification")
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    if temporary.exists():
        raise SystemExit(f"temporary allocation file already exists: {temporary}")
    payload = json.dumps(proposed, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(destination.stat().st_mode & 0o777)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--upstream-checkout", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm")
    args = parser.parse_args()

    root = args.root.resolve()
    upstream = args.upstream_checkout.resolve()
    contract_path = root / CONTRACT_PATH
    original = contract_path.read_bytes()
    application_plan = validate_application(root)
    application = application_plan["recorded_application_evidence"]
    if application.get("candidate_path") != application_plan["candidate"]["path"]:
        raise SystemExit("recorded pid.codes candidate path does not match the application")
    if application.get("owner_path") != application_plan["owner_path"]:
        raise SystemExit("recorded pid.codes owner path does not match the application")
    pull_request = check_pull_request(application)
    upstream_check = check_allocated_upstream(
        application_plan, upstream, pull_request
    )
    contract = load_json(contract_path)
    proposed = build_proposed_contract(
        root, contract, application, pull_request, upstream_check
    )
    confirmation = (
        "APPLY PID.CODES ALLOCATION "
        f"{application_plan['candidate']['vid'][2:]}:"
        f"{application_plan['candidate']['pid'][2:]} "
        f"PR#{application['pull_request_number']}"
    )
    if args.confirm and not args.apply:
        raise SystemExit("--confirm is only valid with --apply")
    applied = False
    if args.apply:
        if args.confirm != confirmation:
            raise SystemExit(f"allocation apply requires --confirm {confirmation!r}")
        write_contract(root, original, proposed)
        applied = True

    allocation = proposed["assignment"]["allocation_evidence"]
    result = {
        "schema": SCHEMA,
        "status": "applied" if applied else "verified-ready-to-apply",
        "applied": applied,
        "contract_path": str(contract_path),
        "active_runtime_profile": proposed["active_runtime_profile"],
        "runtime_profile_changed": False,
        "assignment_status": proposed["assignment"]["status"],
        "public_profile_status": proposed["profiles"]["public_formal"]["status"],
        "public_release_allowed": proposed["profiles"]["public_formal"][
            "public_release_allowed"
        ],
        "pull_request": pull_request,
        "upstream_check": upstream_check,
        "allocation_evidence": allocation,
        "confirmation_required": None if applied else confirmation,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
