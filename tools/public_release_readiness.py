#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

sys.dont_write_bytecode = True

from public_community_health import validate as validate_community_health
from public_export import validate_public_documentation_audit
from public_export_manifest import verify as verify_export_manifest
from public_repository_policy import validate_contract as validate_repository_policy
from public_usb_identity import ContractError, validate_contract as validate_usb_contract
from development_residue_hygiene import scan as scan_development_residue
from repository_hygiene import tracked_files

ROOT = Path(__file__).resolve().parents[1]
ACTION_USE_RE = re.compile(
    r"^\s*(?:-\s*)?uses:\s*"
    r"(?P<repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@(?P<commit>[0-9a-f]{40})"
    r"\s+#\s+v(?P<version>\d+\.\d+\.\d+)\s*$"
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_manifest(root: Path) -> tuple[list[str], list[str], dict[str, Any]]:
    manifest = load_json(root / "PUBLIC_EXPORT_MANIFEST.json")
    verification = verify_export_manifest(root)
    mismatches = list(verification["mismatches"])
    expected = set()
    for item in manifest["files"]:
        relative = item["path"]
        expected.add(relative)
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if (path.is_file() or path.is_symlink())
        and ".git" not in path.relative_to(root).parts
        and path.name != "PUBLIC_EXPORT_MANIFEST.json"
    }
    return mismatches, sorted(actual - expected), verification


def verify_github_actions(root: Path, inventory: dict[str, Any]) -> list[str]:
    issues = []
    lock = load_json(root / "config/github-actions-lock.json")
    if lock.get("schema") != "hidloom.github-actions-lock.v1":
        return ["unsupported-lock-schema"]
    actions = {item["repository"]: item for item in lock["actions"]}
    if len(actions) != len(lock["actions"]):
        issues.append("duplicate-lock-entry")

    workflow = (root / ".github/workflows/public-ci.yml").read_text(encoding="utf-8")
    referenced = set()
    for line_number, line in enumerate(workflow.splitlines(), start=1):
        if "uses:" not in line:
            continue
        match = ACTION_USE_RE.fullmatch(line)
        if not match:
            issues.append(f"mutable-action:{line_number}")
            continue
        repository = match.group("repository")
        action = actions.get(repository)
        if action is None:
            issues.append(f"unreviewed-action:{repository}")
            continue
        if match.group("commit") != action["commit_sha"]:
            issues.append(f"commit-mismatch:{repository}")
        if match.group("version") != action["version"]:
            issues.append(f"version-mismatch:{repository}")
        referenced.add(repository)

    expected = {"actions/cache", "actions/checkout"}
    if referenced != expected:
        issues.append("public-action-set-mismatch")
    if f"runs-on: {lock['runner']}" not in workflow or "ubuntu-latest" in workflow:
        issues.append("runner-policy-mismatch")

    dependabot = (root / ".github/dependabot.yml").read_text(encoding="utf-8")
    if "package-ecosystem: github-actions" not in dependabot:
        issues.append("dependabot-ecosystem-missing")
    if "directory: /" not in dependabot or "interval: weekly" not in dependabot:
        issues.append("dependabot-schedule-missing")

    inventory_actions = {
        (item["name"], item["version"], item.get("commit_sha"))
        for item in inventory["components"]
        if item["ecosystem"] == "github-actions"
    }
    locked_public_actions = {
        (repository, actions[repository]["version"], actions[repository]["commit_sha"])
        for repository in expected
    }
    if inventory_actions != locked_public_actions:
        issues.append("inventory-action-set-mismatch")
    return issues


def validate_public_identity(
    root: Path,
    report: dict[str, Any],
    repository_policy: dict[str, Any],
) -> list[str]:
    issues: list[str] = []
    try:
        identity = load_json(root / "config/project-identity.json")
    except (OSError, json.JSONDecodeError):
        identity = {}
        issues.append("project-identity-unreadable")
    try:
        usb_identity = load_json(root / "config/public-usb-identity.json")
    except (OSError, json.JSONDecodeError):
        usb_identity = {}
        issues.append("public-usb-identity-unreadable")
    else:
        try:
            usb_identity = validate_usb_contract(root)
        except ContractError as exc:
            issues.extend(f"public-usb-contract:{issue}" for issue in exc.issues)
            if not isinstance(usb_identity, dict):
                usb_identity = {}
    authors_path = root / "AUTHORS.md"
    authors = (
        authors_path.read_text(encoding="utf-8", errors="replace")
        if authors_path.is_file()
        else ""
    )
    copyright_policy = identity.get("copyright")
    if not isinstance(copyright_policy, dict):
        copyright_policy = {}

    if identity.get("schema") != "hidloom.project-identity.v1":
        issues.append("unsupported-project-identity-schema")
    if identity.get("initial_public_version") != report.get("initial_version"):
        issues.append("initial-version-mismatch")
    if identity.get("license") != report.get("expected_license"):
        issues.append("project-license-mismatch")
    if copyright_policy != {
        "model": "individual-contributors",
        "assignment_required": False,
        "public_notice": "HIDloom contributors",
    }:
        issues.append("copyright-policy-mismatch")
    if "HIDloom contributors" not in authors or "does not require copyright assignment" not in authors:
        issues.append("authors-policy-missing")

    repository = str(repository_policy.get("repository", ""))
    expected_url = f"https://github.com/{repository}"
    owner = usb_identity.get("owner") if isinstance(usb_identity.get("owner"), dict) else {}
    device = usb_identity.get("device") if isinstance(usb_identity.get("device"), dict) else {}
    repository_parts = repository.split("/", 1)
    if len(repository_parts) != 2 or repository_parts[1] != identity.get("public_repository"):
        issues.append("public-usb-owner-repository-mismatch")
    if not isinstance(owner.get("description"), str) or not owner["description"].strip():
        issues.append("public-usb-owner-description-missing")
    if device.get("site") != expected_url or device.get("source") != expected_url:
        issues.append("public-usb-source-url-mismatch")
    if device.get("license") != identity.get("license"):
        issues.append("public-usb-license-mismatch")
    return issues


def evaluate_binary_distribution(
    root: Path,
    buildroot_legal: dict[str, Any],
    compliance_bundle: Path | None,
) -> dict[str, Any]:
    raw_release_blockers = sorted(
        str(item.get("id", "")) for item in buildroot_legal.get("release_blockers", [])
    )
    raw_ready = bool(buildroot_legal.get("binary_release_ready")) and not raw_release_blockers
    result: dict[str, Any] = {
        "ready": raw_ready,
        "status": "raw-legal-info-ready" if raw_ready else "compliance-bundle-required",
        "raw_legal_info_ready": raw_ready,
        "raw_release_blockers": raw_release_blockers,
        "compliance_bundle_provided": compliance_bundle is not None,
        "compliance_bundle_verified": False,
        "issues": [] if raw_ready else ["compliance-bundle-required"],
        "evidence": None,
    }
    if compliance_bundle is None:
        return result

    result.update(
        {
            "ready": False,
            "status": "invalid-compliance-bundle",
            "issues": [],
        }
    )
    tool = root / "tools" / "buildroot_compliance_bundle.py"
    if not tool.is_file():
        result["issues"].append("compliance-verifier-missing")
        return result
    if not compliance_bundle.is_file():
        result["issues"].append("compliance-bundle-missing")
        return result
    completed = subprocess.run(
        ["python3", str(tool), "verify", str(compliance_bundle), "--json"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        result["issues"].append("compliance-bundle-verification-failed")
        return result
    try:
        evidence = json.loads(completed.stdout)
    except json.JSONDecodeError:
        result["issues"].append("compliance-verifier-invalid-json")
        return result

    expected_source = load_json(root / "config/buildroot-source.json")
    expected_toolchain = load_json(root / "config/buildroot-toolchain-evidence.json")
    expected_resolved = raw_release_blockers
    if evidence.get("profile") != "buildroot-m6" or not evidence.get("binary_release_ready"):
        result["issues"].append("compliance-profile-not-binary-ready")
    if evidence.get("buildroot_commit") != expected_source.get("commit"):
        result["issues"].append("compliance-buildroot-commit-mismatch")
    if evidence.get("bootlin_version") != expected_toolchain.get("version"):
        result["issues"].append("compliance-toolchain-version-mismatch")
    if evidence.get("resolved_release_blockers") != expected_resolved:
        result["issues"].append("compliance-resolved-blockers-mismatch")
    if result["issues"]:
        return result

    result.update(
        {
            "ready": True,
            "status": "verified-compliance-bundle",
            "compliance_bundle_verified": True,
            "evidence": {
                key: evidence[key]
                for key in (
                    "schema",
                    "profile",
                    "archive_sha256",
                    "archive_size",
                    "manifest_sha256",
                    "binary_release_ready",
                    "resolved_release_blockers",
                    "buildroot_commit",
                    "bootlin_version",
                    "summary",
                )
            },
        }
    )
    return result


def evaluate(
    root: Path,
    *,
    allow_pending_pid: bool,
    compliance_bundle: Path | None = None,
    require_binary_distribution: bool = False,
) -> dict[str, Any]:
    report = load_json(root / "PUBLIC_EXPORT_REPORT.json")
    inventory = load_json(root / "docs/ops/third-party-inventory.json")
    buildroot_legal = load_json(root / "docs/ops/buildroot-m6-legal-summary.json")
    privacy = load_json(root / "PUBLIC_PRIVACY_AUDIT.json")
    assets = load_json(root / "PUBLIC_ASSET_PROVENANCE.json")
    references = load_json(root / "PUBLIC_REFERENCE_AUDIT.json")
    documentation = load_json(root / "PUBLIC_DOCUMENTATION_AUDIT.json")
    documentation_issues = validate_public_documentation_audit(documentation, root=root)
    documentation_summary = documentation.get("summary")
    if not isinstance(documentation_summary, dict):
        documentation_summary = {}
    github_actions_issues = verify_github_actions(root, inventory)
    repository_policy = load_json(root / "config/public-repository-policy.json")
    repository_policy_issues = validate_repository_policy(root, repository_policy)
    community_health_issues = validate_community_health(root)
    public_identity_issues = validate_public_identity(root, report, repository_policy)
    manifest_mismatches, unlisted_files, manifest_verification = verify_manifest(root)
    development_paths, _development_modes, _development_inventory = tracked_files(root)
    development_findings, _development_counts = scan_development_residue(
        root, development_paths
    )
    development_residue_issues = [
        f"{finding.kind}:{finding.path}:{finding.detail}"
        for finding in development_findings
    ]
    source_provenance = manifest_verification["source_provenance"]
    if not isinstance(source_provenance, dict):
        source_provenance = {}
    blockers = [item for item in report["findings"] if item["severity"] == "block"]
    required = [item for item in report["findings"] if item["disposition"].endswith("_required")]
    allowed_dispositions = {"pid_codes_migration_required"} if allow_pending_pid else set()
    unexpected_required = [item for item in required if item["disposition"] not in allowed_dispositions]
    required_files = (
        ".env.example",
        "README.md",
        "INSTALL.md",
        "AUTHORS.md",
        "LICENSE",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "SUPPORT.md",
        "CODE_OF_CONDUCT.md",
        "THIRD_PARTY_NOTICES.md",
        "SBOM.cdx.json",
        "PUBLIC_EXPORT_MANIFEST.json",
        "PUBLIC_PRIVACY_AUDIT.json",
        "PUBLIC_PRIVACY_AUDIT.md",
        "PUBLIC_ASSET_PROVENANCE.json",
        "PUBLIC_ASSET_PROVENANCE.md",
        "PUBLIC_REFERENCE_AUDIT.json",
        "PUBLIC_REFERENCE_AUDIT.md",
        "PUBLIC_DOCUMENTATION_AUDIT.json",
        "PUBLIC_DOCUMENTATION_AUDIT.md",
        ".github/ISSUE_TEMPLATE/bug.yml",
        ".github/ISSUE_TEMPLATE/config.yml",
        ".github/ISSUE_TEMPLATE/feature.yml",
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".github/dependabot.yml",
        ".github/workflows/public-ci.yml",
        "config/github-actions-lock.json",
        "config/public-usb-identity.json",
        "config/public-repository-policy.json",
        "script/test_github_workflow_security.py",
        "script/test_development_residue_hygiene.py",
        "script/test_pid_codes_allocation.py",
        "script/test_pid_codes_application.py",
        "script/test_public_usb_identity.py",
        "script/test_public_community_health.py",
        "script/test_public_repository_bootstrap.py",
        "script/test_public_repository_policy.py",
        "script/test_public_source_archive.py",
        "tools/public_repository_bootstrap.py",
        "tools/public_community_health.py",
        "tools/development_residue_hygiene.py",
        "tools/pid_codes_allocation.py",
        "tools/pid_codes_application.py",
        "tools/public_usb_identity.py",
        "tools/public_repository_policy.py",
        "tools/public_source_archive.py",
    )
    missing_files = [path for path in required_files if not (root / path).is_file()]
    checks = {
        "no_blockers": not blockers,
        "no_unexpected_required": not unexpected_required,
        "required_files_present": not missing_files,
        "third_party_inventory_present": inventory["summary"]["total"] > 0,
        "third_party_redistributed_complete": inventory["summary"][
            "redistributed_review_required"
        ]
        == 0,
        "github_actions_supply_chain_ready": not github_actions_issues,
        "community_health_ready": not community_health_issues,
        "public_repository_policy_ready": not repository_policy_issues,
        "public_identity_ready": not public_identity_issues,
        "development_residue_ready": not development_residue_issues,
        "buildroot_source_audit_ready": buildroot_legal["source_audit_ready"]
        and buildroot_legal["summary"]["target_complete"]
        == buildroot_legal["summary"]["target_packages"],
        "source_provenance_ready": manifest_verification["source_publishable"]
        and not manifest_verification["source_provenance_issues"],
        "source_selection_ready": not manifest_verification["source_selection_issues"],
        "manifest_integrity": not manifest_mismatches,
        "no_unlisted_files": not unlisted_files,
        "privacy_audit_ready": privacy["ready"] and privacy["summary"]["blockers"] == 0,
        "asset_provenance_ready": assets["ready"]
        and assets["summary"]["missing_declarations"] == 0
        and assets["summary"]["stale_declarations"] == 0,
        "public_reference_audit_ready": references["ready"]
        and references["summary"]["blockers"] == 0,
        "public_documentation_audit_ready": not documentation_issues
        and documentation.get("ready") is True
        and documentation_summary.get("broken_links") == 0
        and documentation_summary.get("orphaned_documents") == 0,
    }
    binary_distribution = evaluate_binary_distribution(
        root,
        buildroot_legal,
        compliance_bundle,
    )
    source_publication_ready = all(checks.values())
    return {
        "schema": "hidloom.public-release-readiness.v3",
        "evaluation_scope": (
            "binary-distribution" if require_binary_distribution else "source-publication"
        ),
        "source_commit": str(source_provenance.get("base_commit", "")),
        "source_provenance": source_provenance,
        "initial_version": report["initial_version"],
        "allow_pending_pid": allow_pending_pid,
        "source_publication_ready": source_publication_ready,
        "ready": source_publication_ready
        and (not require_binary_distribution or binary_distribution["ready"]),
        "checks": checks,
        "blocking_count": len(blockers),
        "action_required_count": len(required),
        "unexpected_required_count": len(unexpected_required),
        "pending_dispositions": sorted({item["disposition"] for item in required}),
        "missing_files": missing_files,
        "github_actions_issues": github_actions_issues,
        "community_health_issues": community_health_issues,
        "repository_policy_issues": repository_policy_issues,
        "public_identity_issues": public_identity_issues,
        "development_residue_issues": development_residue_issues,
        "documentation_audit_issues": documentation_issues,
        "manifest_mismatches": manifest_mismatches,
        "source_provenance_issues": manifest_verification["source_provenance_issues"],
        "source_selection_issues": manifest_verification["source_selection_issues"],
        "unlisted_files": unlisted_files,
        "third_party_summary": inventory["summary"],
        "buildroot_legal_summary": buildroot_legal["summary"],
        "binary_distribution_ready": binary_distribution["ready"],
        "binary_distribution_status": binary_distribution["status"],
        "binary_distribution_issues": binary_distribution["issues"],
        "binary_distribution": binary_distribution,
        "privacy_summary": privacy["summary"],
        "asset_summary": assets["summary"],
        "reference_summary": references["summary"],
        "documentation_summary": documentation_summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a generated HIDloom public export")
    parser.add_argument("root", nargs="?", type=Path, default=ROOT)
    parser.add_argument("--allow-pending-pid", action="store_true")
    parser.add_argument("--compliance-bundle", type=Path)
    parser.add_argument("--require-binary-distribution", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    compliance_bundle = args.compliance_bundle.resolve() if args.compliance_bundle else None
    payload = evaluate(
        args.root.resolve(),
        allow_pending_pid=args.allow_pending_pid,
        compliance_bundle=compliance_bundle,
        require_binary_distribution=(
            args.require_binary_distribution or compliance_bundle is not None
        ),
    )
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    if not payload["ready"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
