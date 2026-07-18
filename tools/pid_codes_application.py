#!/usr/bin/env python3
"""Validate and render the pid.codes application draft for HIDloom."""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from public_usb_identity import (
    ContractError,
    validate_contract as validate_usb_contract,
)

ROOT = Path(__file__).resolve().parents[1]
HEX_U16_RE = re.compile(r"[0-9A-Fa-f]{4}")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_u16(value: object, label: str) -> str:
    text = str(value)
    if not HEX_U16_RE.fullmatch(text):
        raise ValueError(f"{label} must be exactly four hexadecimal digits")
    return text.upper()


def validate(root: Path) -> dict[str, Any]:
    try:
        request = validate_usb_contract(root)
    except ContractError as exc:
        raise SystemExit(
            "pid.codes application validation failed:\n- public USB identity: "
            + "\n- public USB identity: ".join(exc.issues)
        )
    assignment = request["assignment"]
    identity = load_json(root / "config/project-identity.json")
    repository_policy = load_json(root / "config/public-repository-policy.json")
    errors: list[str] = []

    if assignment.get("registry") != "pid.codes":
        errors.append("public USB identity registry must be pid.codes")
    if assignment.get("registry_repository") != "https://github.com/pidcodes/pidcodes.github.com":
        errors.append("pid.codes registry repository is not canonical")
    try:
        vid = normalize_u16(assignment.get("vid"), "VID")
        pid = normalize_u16(assignment.get("pid"), "PID candidate")
    except ValueError as exc:
        errors.append(str(exc))
        vid = ""
        pid = ""
    if vid and vid != "1209":
        errors.append("pid.codes application must use VID 1209")
    if pid and int(pid, 16) < 0x2000:
        errors.append("PID candidate is inside a VID 1209 reserved range")
    if assignment.get("status") != "candidate-unassigned":
        errors.append("PID application draft must remain candidate-unassigned")
    if assignment.get("activate_only_after_pid_codes_merge") is not True:
        errors.append("PID candidate activation must wait for the pid.codes merge")
    if assignment.get("recheck_availability_before_request") is not True:
        errors.append("PID availability must be rechecked immediately before requesting it")

    owner_config = request.get("owner") if isinstance(request.get("owner"), dict) else {}
    device = request.get("device") if isinstance(request.get("device"), dict) else {}
    repository = str(repository_policy.get("repository", ""))
    repository_parts = repository.split("/", 1)
    if len(repository_parts) == 2:
        repository_owner, repository_name = repository_parts
    else:
        repository_owner, repository_name = "", ""
        errors.append("public repository policy must use owner/name form")
    owner = {
        "slug": repository_owner,
        "title": repository_owner,
        "site": f"https://github.com/{repository_owner}/" if repository_owner else "",
        "description": owner_config.get("description"),
    }
    expected_repository_url = f"https://github.com/{repository}"
    if repository_name != identity.get("public_repository"):
        errors.append("owner/project identity does not match public repository policy")
    if device.get("site") != expected_repository_url or device.get("source") != expected_repository_url:
        errors.append("pid.codes site/source must use the canonical public repository URL")
    if device.get("license") != identity.get("license"):
        errors.append("pid.codes license does not match canonical project identity")
    for section_name, section, fields in (
        ("owner", owner, ("slug", "title", "site", "description")),
        ("device", device, ("title", "license", "site", "source", "description")),
    ):
        for field in fields:
            if not isinstance(section.get(field), str) or not section[field].strip():
                errors.append(f"{section_name}.{field} is required")

    if not (root / "LICENSE").is_file():
        errors.append("LICENSE is missing")
    if not any((root / "kicad").rglob("*.kicad_sch")):
        errors.append("modifiable KiCad schematics are missing")
    if not any((root / "kicad").rglob("*.kicad_pcb")):
        errors.append("modifiable KiCad PCB layouts are missing")
    if errors:
        raise SystemExit("pid.codes application validation failed:\n- " + "\n- ".join(errors))

    return {
        "schema": "hidloom.pid-codes-application-plan.v1",
        "status": assignment["status"],
        "registry_repository": assignment["registry_repository"],
        "candidate": {
            "vid": f"0x{vid}",
            "pid": f"0x{pid}",
            "path": f"{vid}/{pid}/index.md",
        },
        "owner_path": f"org/{owner['slug']}/index.md",
        "activation_allowed": False,
        "availability_recheck_required": True,
        "recorded_availability_evidence": assignment.get("availability_evidence", {}),
        "recorded_application_evidence": assignment.get("application_evidence", {}),
        "owner": owner,
        "device": device,
    }


def check_canonical_upstream(
    plan: dict[str, Any], upstream: Path
) -> dict[str, Any]:
    if not upstream.is_dir():
        raise SystemExit(f"pid.codes upstream checkout not found: {upstream}")
    vid_page = upstream / "1209/index.md"
    if not vid_page.is_file():
        raise SystemExit(f"pid.codes VID 1209 marker not found: {vid_page}")
    vid_text = vid_page.read_text(encoding="utf-8", errors="replace")
    if "layout: vid" not in vid_text or "vid: 1209" not in vid_text:
        raise SystemExit(f"invalid pid.codes VID 1209 marker: {vid_page}")
    if not (upstream / "org").is_dir():
        raise SystemExit(f"pid.codes organisation directory not found: {upstream / 'org'}")
    commit_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=upstream,
        capture_output=True,
        text=True,
    )
    if commit_result.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", commit_result.stdout.strip()):
        raise SystemExit("pid.codes upstream checkout must have a committed Git HEAD")
    commit = commit_result.stdout.strip()
    remote_result = subprocess.run(
        ["git", "config", "--get", "remote.origin.url"],
        cwd=upstream,
        capture_output=True,
        text=True,
    )
    allowed_remotes = {
        plan["registry_repository"],
        plan["registry_repository"] + ".git",
        "git@github.com:pidcodes/pidcodes.github.com.git",
    }
    remote = remote_result.stdout.strip()
    if remote_result.returncode != 0 or remote not in allowed_remotes:
        raise SystemExit(f"pid.codes upstream origin is not canonical: {remote or '<missing>'}")
    rewrite_result = subprocess.run(
        ["git", "config", "--get-regexp", r"^url\..*\.insteadof$"],
        cwd=upstream,
        capture_output=True,
        text=True,
    )
    if rewrite_result.returncode not in {0, 1}:
        raise SystemExit("pid.codes Git URL rewrite configuration could not be read")
    rewrite_values: list[str] = []
    for line in rewrite_result.stdout.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or not parts[1]:
            raise SystemExit("pid.codes Git URL rewrite configuration is malformed")
        rewrite_values.append(parts[1])
    if any(remote.startswith(value) for value in rewrite_values):
        raise SystemExit("pid.codes canonical origin must not use a Git URL rewrite")
    status_result = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=upstream,
        capture_output=True,
    )
    if status_result.returncode != 0:
        raise SystemExit("pid.codes upstream checkout status could not be read")
    if status_result.stdout:
        raise SystemExit("pid.codes upstream checkout must be clean")
    origin_head_result = subprocess.run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
        cwd=upstream,
        capture_output=True,
        text=True,
    )
    origin_head_ref = origin_head_result.stdout.strip()
    if (
        origin_head_result.returncode != 0
        or not origin_head_ref.startswith("refs/remotes/origin/")
    ):
        raise SystemExit("pid.codes upstream checkout has no canonical origin/HEAD")
    ref_check = subprocess.run(
        ["git", "check-ref-format", origin_head_ref],
        cwd=upstream,
        capture_output=True,
        text=True,
    )
    if ref_check.returncode != 0:
        raise SystemExit(f"pid.codes upstream origin/HEAD is invalid: {origin_head_ref}")
    origin_head_commit_result = subprocess.run(
        ["git", "rev-parse", origin_head_ref],
        cwd=upstream,
        capture_output=True,
        text=True,
    )
    origin_head_commit = origin_head_commit_result.stdout.strip()
    if (
        origin_head_commit_result.returncode != 0
        or not re.fullmatch(r"[0-9a-f]{40}", origin_head_commit)
    ):
        raise SystemExit("pid.codes upstream origin/HEAD commit could not be resolved")
    if commit != origin_head_commit:
        raise SystemExit(
            "pid.codes upstream checkout HEAD does not match origin/HEAD: "
            f"head={commit} origin_head={origin_head_commit}"
        )
    remote_head_result = subprocess.run(
        ["git", "ls-remote", "--exit-code", "origin", "HEAD"],
        cwd=upstream,
        capture_output=True,
        text=True,
    )
    remote_head_lines = [
        line.split() for line in remote_head_result.stdout.splitlines() if line.strip()
    ]
    if (
        remote_head_result.returncode != 0
        or len(remote_head_lines) != 1
        or len(remote_head_lines[0]) != 2
        or remote_head_lines[0][1] != "HEAD"
        or not re.fullmatch(r"[0-9a-f]{40}", remote_head_lines[0][0])
    ):
        raise SystemExit("pid.codes canonical remote HEAD could not be resolved")
    remote_head_commit = remote_head_lines[0][0]
    if origin_head_commit != remote_head_commit:
        raise SystemExit(
            "pid.codes upstream origin/HEAD does not match canonical remote HEAD: "
            f"origin_head={origin_head_commit} remote_head={remote_head_commit}"
        )
    return {
        "checkout": str(upstream.resolve()),
        "checked_date": date.today().isoformat(),
        "commit": commit,
        "origin": remote,
        "origin_head_ref": origin_head_ref,
        "origin_head_commit": origin_head_commit,
        "remote_head_commit": remote_head_commit,
        "checkout_clean": True,
        "head_matches_origin_head": True,
        "origin_head_matches_remote_head": True,
    }


def check_upstream(plan: dict[str, Any], upstream: Path) -> dict[str, Any]:
    upstream_check = check_canonical_upstream(plan, upstream)
    candidate = upstream / Path(plan["candidate"]["path"]).parent
    if candidate.exists():
        raise SystemExit(f"PID candidate is already present in upstream checkout: {candidate}")
    owner = upstream / plan["owner_path"]
    upstream_check.update({
        "candidate_path_absent": True,
        "owner_path_absent": not owner.exists(),
    })
    return upstream_check


def validate_recorded_availability(
    plan: dict[str, Any], upstream_check: dict[str, Any]
) -> None:
    recorded = plan.get("recorded_availability_evidence")
    if not isinstance(recorded, dict):
        raise SystemExit("recorded pid.codes availability evidence is missing")
    expected = {
        "checked_date": upstream_check["checked_date"],
        "upstream_commit": upstream_check["commit"],
        "origin_head_ref": upstream_check["origin_head_ref"],
        "remote_head_commit": upstream_check["remote_head_commit"],
        "checkout_clean": upstream_check["checkout_clean"],
        "head_matches_origin_head": upstream_check["head_matches_origin_head"],
        "origin_head_matches_remote_head": upstream_check[
            "origin_head_matches_remote_head"
        ],
        "candidate_path_absent": upstream_check["candidate_path_absent"],
        "owner_path_absent": upstream_check["owner_path_absent"],
    }
    mismatches = [
        field for field, value in expected.items() if recorded.get(field) != value
    ]
    if mismatches:
        raise SystemExit(
            "recorded pid.codes availability evidence does not match the checked "
            "origin/HEAD: "
            + ", ".join(mismatches)
        )


def org_page(plan: dict[str, Any]) -> str:
    owner = plan["owner"]
    return (
        "---\n"
        "layout: org\n"
        f"title: {owner['title']}\n"
        f"site: {owner['site']}\n"
        "---\n"
        f"{owner['description']}\n"
    )


def device_page(plan: dict[str, Any]) -> str:
    device = plan["device"]
    return (
        "---\n"
        "layout: pid\n"
        f"title: {device['title']}\n"
        f"owner: {plan['owner']['slug']}\n"
        f"license: {device['license']}\n"
        f"site: {device['site']}\n"
        f"source: {device['source']}\n"
        "---\n"
        f"{device['description']}\n"
    )


def write_application(plan: dict[str, Any], output: Path, *, force: bool) -> None:
    if output.exists():
        if not force:
            raise SystemExit(f"output already exists: {output}")
        if not output.is_dir():
            raise SystemExit(f"output is not a directory: {output}")
        expected_files = {
            Path(plan["owner_path"]),
            Path(plan["candidate"]["path"]),
        }
        symlinks = sorted(
            path.relative_to(output) for path in output.rglob("*") if path.is_symlink()
        )
        if symlinks:
            raise SystemExit(
                "refusing to replace output containing symlinks: "
                + ", ".join(path.as_posix() for path in symlinks)
            )
        actual_files = {
            path.relative_to(output)
            for path in output.rglob("*")
            if not path.is_dir()
        }
        unexpected = sorted(actual_files - expected_files)
        if unexpected:
            raise SystemExit(
                "refusing to replace output with unexpected files: "
                + ", ".join(path.as_posix() for path in unexpected)
            )
    output.mkdir(parents=True, exist_ok=True)
    owner_path = output / plan["owner_path"]
    candidate_path = output / plan["candidate"]["path"]
    owner_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    owner_path.write_text(org_page(plan), encoding="utf-8")
    candidate_path.write_text(device_page(plan), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--upstream-checkout", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    plan = validate(root)
    upstream = args.upstream_checkout.resolve() if args.upstream_checkout else None
    if args.upstream_checkout:
        upstream_check = check_upstream(plan, upstream)
        validate_recorded_availability(plan, upstream_check)
        plan["upstream_check"] = upstream_check
    if args.output:
        if upstream is None:
            raise SystemExit("--output requires --upstream-checkout")
        output = args.output.resolve()
        if output == Path(output.anchor) or output == root or root in output.parents:
            raise SystemExit("output must be outside the HIDloom source repository")
        if upstream is not None and (output == upstream or upstream in output.parents):
            raise SystemExit("output must not replace or modify the pid.codes upstream checkout")
        write_application(plan, output, force=args.force)
        plan["output"] = str(output)
    print(json.dumps(plan, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
