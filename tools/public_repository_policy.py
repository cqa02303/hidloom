#!/usr/bin/env python3
"""Plan, audit, or explicitly apply the HIDloom public repository policy."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
from typing import Any
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "config" / "public-repository-policy.json"
ACTION_USE_RE = re.compile(
    r"^\s*(?:-\s*)?uses:\s*"
    r"(?P<repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@(?P<commit>[0-9a-f]{40})"
    r"\s+#\s+v(?P<version>\d+\.\d+\.\d+)\s*$"
)
REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
REPOSITORY_PATCH_FIELDS = (
    "description",
    "homepage",
    "default_branch",
    "has_issues",
    "has_projects",
    "has_wiki",
    "is_template",
    "allow_squash_merge",
    "allow_merge_commit",
    "allow_rebase_merge",
    "allow_auto_merge",
    "delete_branch_on_merge",
)
REPOSITORY_AUDIT_ONLY_FIELDS = (
    "visibility",
    "private",
    "archived",
    "has_discussions",
    "has_downloads",
)
REPOSITORY_OPTIONAL_RESPONSE_FIELDS = (
    "has_downloads",
)
OPTIONAL_RESPONSE_PATHS = frozenset(
    f"repository.{field}" for field in REPOSITORY_OPTIONAL_RESPONSE_FIELDS
)


@dataclass(frozen=True)
class Operation:
    name: str
    method: str
    endpoint: str
    body: dict[str, Any] | None

    def payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "method": self.method,
            "endpoint": self.endpoint,
            "body": self.body,
        }


class GitHubApiError(RuntimeError):
    pass


class GitHubClient:
    def __init__(self, executable: str, api_host: str, api_version: str) -> None:
        self.executable = executable
        self.api_host = api_host
        self.api_version = api_version

    def request(
        self,
        method: str,
        endpoint: str,
        body: dict[str, Any] | None = None,
        accepted_error_statuses: frozenset[str] = frozenset(),
    ) -> dict[str, Any]:
        command = [
            self.executable,
            "api",
            "--hostname",
            self.api_host,
            "--method",
            method,
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            f"X-GitHub-Api-Version: {self.api_version}",
            endpoint,
        ]
        encoded = None
        if body is not None:
            command.extend(["--input", "-"])
            encoded = json.dumps(body, separators=(",", ":"))
        try:
            completed = subprocess.run(
                command,
                input=encoded,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except OSError as error:
            raise GitHubApiError(f"cannot execute {self.executable}: {error}") from error
        if completed.returncode != 0:
            try:
                error_payload = json.loads(completed.stdout)
            except json.JSONDecodeError:
                error_payload = None
            if (
                isinstance(error_payload, dict)
                and str(error_payload.get("status", "")) in accepted_error_statuses
            ):
                return {}
            detail = completed.stderr.strip() or completed.stdout.strip() or "unknown GitHub API error"
            raise GitHubApiError(f"{method} {endpoint}: {detail}")
        text = completed.stdout.strip()
        if not text:
            return {}
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise GitHubApiError(f"{method} {endpoint}: response is not JSON") from error
        if not isinstance(payload, dict):
            raise GitHubApiError(f"{method} {endpoint}: response root is not an object")
        return payload


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def workflow_actions(root: Path) -> dict[str, tuple[str, str]]:
    workflow = (root / ".github/workflows/public-ci.yml").read_text(encoding="utf-8")
    actions: dict[str, tuple[str, str]] = {}
    for line_number, line in enumerate(workflow.splitlines(), start=1):
        if "uses:" not in line:
            continue
        match = ACTION_USE_RE.fullmatch(line)
        if not match:
            raise ValueError(f"mutable public workflow action at line {line_number}")
        repository = match.group("repository")
        candidate = (match.group("commit"), match.group("version"))
        previous = actions.setdefault(repository, candidate)
        if previous != candidate:
            raise ValueError(f"inconsistent public workflow action: {repository}")
    return actions


def validate_contract(root: Path, policy: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if policy.get("schema") != "hidloom.public-repository-policy.v3":
        return ["unsupported-policy-schema"]
    repository = policy.get("repository")
    if not isinstance(repository, str) or not REPOSITORY_RE.fullmatch(repository):
        issues.append("invalid-repository")
    if policy.get("api_host") != "github.com":
        issues.append("unsupported-api-host")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(policy.get("api_version", ""))):
        issues.append("invalid-api-version")

    creation = policy.get("repository_creation", {})
    if not isinstance(creation, dict):
        return ["invalid-repository-creation"]
    expected_homepage = f"https://github.com/{repository}" if isinstance(repository, str) else ""
    description = creation.get("description")
    if creation.get("owner_type") != "user":
        issues.append("unsupported-repository-owner-type")
    if (
        not isinstance(description, str)
        or not description.strip()
        or len(description) > 350
        or "\n" in description
        or "\r" in description
    ):
        issues.append("invalid-repository-description")
    if creation.get("homepage") != expected_homepage:
        issues.append("repository-homepage-mismatch")
    expected_creation_flags = {
        "private": False,
        "has_issues": True,
        "has_projects": False,
        "has_wiki": False,
        "has_discussions": False,
        "has_downloads": False,
        "is_template": False,
        "auto_init": False,
        "allow_squash_merge": True,
        "allow_merge_commit": False,
        "allow_rebase_merge": True,
        "allow_auto_merge": False,
        "delete_branch_on_merge": True,
    }
    for field, expected_value in expected_creation_flags.items():
        if creation.get(field) != expected_value:
            issues.append(f"unsafe-repository-creation:{field}")
    expected_creation_fields = {
        "owner_type",
        "description",
        "homepage",
        *expected_creation_flags,
    }
    if set(creation) != expected_creation_fields:
        issues.append("repository-creation-field-set-mismatch")

    settings = policy.get("repository_settings", {})
    if not isinstance(settings, dict):
        return sorted(set([*issues, "invalid-repository-settings"]))
    if settings.get("visibility") != "public":
        issues.append("repository-must-be-public")
    if settings.get("private") is not False:
        issues.append("repository-must-not-be-private")
    if settings.get("default_branch") != "main":
        issues.append("default-branch-must-be-main")
    if settings.get("archived") is not False:
        issues.append("repository-must-not-be-archived")
    expected_repository_settings = {
        "description": description,
        "homepage": expected_homepage,
        "has_issues": True,
        "has_projects": False,
        "has_wiki": False,
        "has_discussions": False,
        "has_downloads": False,
        "is_template": False,
        "allow_squash_merge": True,
        "allow_merge_commit": False,
        "allow_rebase_merge": True,
        "allow_auto_merge": False,
        "delete_branch_on_merge": True,
    }
    for field, expected_value in expected_repository_settings.items():
        if settings.get(field) != expected_value:
            issues.append(f"repository-setting-mismatch:{field}")
    security = settings.get("security_and_analysis", {})
    for feature in ("secret_scanning", "secret_scanning_push_protection"):
        if security.get(feature, {}).get("status") != "enabled":
            issues.append(f"security-feature-disabled:{feature}")

    actions_permissions = policy.get("actions_permissions", {})
    if actions_permissions != {
        "enabled": True,
        "allowed_actions": "selected",
        "sha_pinning_required": True,
    }:
        issues.append("unsafe-actions-permissions")
    selected = policy.get("selected_actions", {})
    if selected.get("github_owned_allowed") is not False:
        issues.append("all-github-actions-allowed")
    if selected.get("verified_allowed") is not False:
        issues.append("all-verified-actions-allowed")
    locked_repositories = selected.get("locked_repositories")
    if not isinstance(locked_repositories, list) or not locked_repositories:
        issues.append("locked-action-set-empty")
        locked_repositories = []

    workflow_permissions = policy.get("workflow_permissions", {})
    if workflow_permissions.get("default_workflow_permissions") != "read":
        issues.append("default-workflow-permissions-not-read")
    if workflow_permissions.get("can_approve_pull_request_reviews") is not True:
        issues.append("sync-pr-creation-disabled")
    if policy.get("private_vulnerability_reporting", {}).get("enabled") is not True:
        issues.append("private-vulnerability-reporting-disabled")

    protection = policy.get("branch_protection", {})
    required = protection.get("required_status_checks", {})
    if required.get("strict") is not True:
        issues.append("required-checks-not-strict")
    if required.get("contexts") != ["Public CI / validate"]:
        issues.append("required-check-set-mismatch")
    for field in (
        "enforce_admins",
        "required_linear_history",
        "required_conversation_resolution",
    ):
        if protection.get(field) is not True:
            issues.append(f"branch-protection-disabled:{field}")
    for field in ("allow_force_pushes", "allow_deletions", "lock_branch"):
        if protection.get(field) is not False:
            issues.append(f"unsafe-branch-protection:{field}")
    if protection.get("required_pull_request_reviews") is not None:
        issues.append("unexpected-required-review-policy")
    if protection.get("restrictions") is not None:
        issues.append("unexpected-push-restrictions")

    lock = load_json(root / "config/github-actions-lock.json")
    if lock.get("schema") != "hidloom.github-actions-lock.v1":
        issues.append("unsupported-actions-lock-schema")
        lock_actions: dict[str, dict[str, Any]] = {}
    else:
        lock_actions = {item["repository"]: item for item in lock.get("actions", [])}
    try:
        public_actions = workflow_actions(root)
    except (OSError, ValueError) as error:
        issues.append(f"public-workflow:{error}")
        public_actions = {}
    if set(locked_repositories) != set(public_actions):
        issues.append("policy-workflow-action-set-mismatch")
    for action in locked_repositories:
        metadata = lock_actions.get(action)
        workflow = public_actions.get(action)
        if metadata is None:
            issues.append(f"policy-action-not-locked:{action}")
        elif workflow != (metadata.get("commit_sha"), metadata.get("version")):
            issues.append(f"policy-action-lock-mismatch:{action}")
    return sorted(set(issues))


def expected_state(root: Path, policy: dict[str, Any]) -> dict[str, Any]:
    issues = validate_contract(root, policy)
    if issues:
        raise ValueError(f"invalid public repository policy: {issues}")
    lock = load_json(root / "config/github-actions-lock.json")
    lock_actions = {item["repository"]: item for item in lock["actions"]}
    selected = policy["selected_actions"]
    patterns = [
        f"{repository}@{lock_actions[repository]['commit_sha']}"
        for repository in sorted(selected["locked_repositories"])
    ]
    branch = quote(policy["repository_settings"]["default_branch"], safe="")
    base = f"/repos/{policy['repository']}"
    return {
        "repository": policy["repository_settings"],
        "actions_permissions": policy["actions_permissions"],
        "selected_actions": {
            "github_owned_allowed": selected["github_owned_allowed"],
            "verified_allowed": selected["verified_allowed"],
            "patterns_allowed": patterns,
        },
        "workflow_permissions": policy["workflow_permissions"],
        "private_vulnerability_reporting": policy["private_vulnerability_reporting"],
        "branch_protection": policy["branch_protection"],
        "endpoints": {
            "repository": base,
            "actions_permissions": f"{base}/actions/permissions",
            "selected_actions": f"{base}/actions/permissions/selected-actions",
            "workflow_permissions": f"{base}/actions/permissions/workflow",
            "private_vulnerability_reporting": f"{base}/private-vulnerability-reporting",
            "branch_protection": f"{base}/branches/{branch}/protection",
        },
    }


def mutation_operations(expected: dict[str, Any]) -> list[Operation]:
    settings = expected["repository"]
    repository_body = {field: settings[field] for field in REPOSITORY_PATCH_FIELDS}
    repository_body["security_and_analysis"] = settings["security_and_analysis"]
    endpoints = expected["endpoints"]
    return [
        Operation("repository-settings", "PATCH", endpoints["repository"], repository_body),
        Operation(
            "actions-permissions",
            "PUT",
            endpoints["actions_permissions"],
            expected["actions_permissions"],
        ),
        Operation(
            "selected-actions",
            "PUT",
            endpoints["selected_actions"],
            expected["selected_actions"],
        ),
        Operation(
            "workflow-permissions",
            "PUT",
            endpoints["workflow_permissions"],
            expected["workflow_permissions"],
        ),
        Operation(
            "private-vulnerability-reporting",
            "PUT",
            endpoints["private_vulnerability_reporting"],
            None,
        ),
        Operation(
            "branch-protection",
            "PUT",
            endpoints["branch_protection"],
            expected["branch_protection"],
        ),
    ]


def audit_operations(expected: dict[str, Any]) -> list[Operation]:
    return [
        Operation(name, "GET", endpoint, None)
        for name, endpoint in expected["endpoints"].items()
    ]


def compare_value(
    expected: Any,
    actual: Any,
    path: str,
    issues: list[str],
) -> None:
    if path in OPTIONAL_RESPONSE_PATHS and actual is None:
        return
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            issues.append(f"{path}:expected-object")
            return
        for key, value in expected.items():
            child_path = f"{path}.{key}"
            if key not in actual:
                if child_path not in OPTIONAL_RESPONSE_PATHS:
                    issues.append(f"{child_path}:missing")
                continue
            compare_value(value, actual[key], child_path, issues)
        return
    if isinstance(expected, list):
        if not isinstance(actual, list) or sorted(expected) != sorted(actual):
            issues.append(f"{path}:mismatch")
        return
    if expected != actual:
        issues.append(f"{path}:mismatch")


def audit_snapshots(expected: dict[str, Any], snapshots: dict[str, dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    compare_value(expected["repository"], snapshots.get("repository"), "repository", issues)
    compare_value(
        expected["actions_permissions"],
        snapshots.get("actions_permissions"),
        "actions_permissions",
        issues,
    )
    compare_value(
        expected["selected_actions"],
        snapshots.get("selected_actions"),
        "selected_actions",
        issues,
    )
    compare_value(
        expected["workflow_permissions"],
        snapshots.get("workflow_permissions"),
        "workflow_permissions",
        issues,
    )
    compare_value(
        expected["private_vulnerability_reporting"],
        snapshots.get("private_vulnerability_reporting"),
        "private_vulnerability_reporting",
        issues,
    )

    protection = snapshots.get("branch_protection")
    if not isinstance(protection, dict):
        issues.append("branch_protection:expected-object")
        return sorted(set(issues))
    expected_protection = expected["branch_protection"]
    compare_value(
        expected_protection["required_status_checks"],
        protection.get("required_status_checks"),
        "branch_protection.required_status_checks",
        issues,
    )
    for field in (
        "enforce_admins",
        "required_linear_history",
        "allow_force_pushes",
        "allow_deletions",
        "block_creations",
        "required_conversation_resolution",
        "lock_branch",
    ):
        actual = protection.get(field)
        if actual is None and expected_protection[field] is False:
            continue
        compare_value(
            {"enabled": expected_protection[field]},
            actual,
            f"branch_protection.{field}",
            issues,
        )
    for field in ("required_pull_request_reviews", "restrictions"):
        if protection.get(field) is not None:
            issues.append(f"branch_protection.{field}:unexpected")
    return sorted(set(issues))


def collect_snapshots(client: GitHubClient, expected: dict[str, Any]) -> dict[str, dict[str, Any]]:
    operations = {operation.name: operation for operation in audit_operations(expected)}
    snapshots: dict[str, dict[str, Any]] = {}
    for name in ("repository", "actions_permissions"):
        operation = operations[name]
        snapshots[name] = client.request(operation.method, operation.endpoint)

    selected = operations["selected_actions"]
    if snapshots["actions_permissions"].get("allowed_actions") == "selected":
        snapshots["selected_actions"] = client.request(selected.method, selected.endpoint)
    else:
        snapshots["selected_actions"] = {}

    for name in ("workflow_permissions", "private_vulnerability_reporting"):
        operation = operations[name]
        snapshots[name] = client.request(operation.method, operation.endpoint)

    protection = operations["branch_protection"]
    snapshots["branch_protection"] = client.request(
        protection.method,
        protection.endpoint,
        accepted_error_statuses=frozenset({"404"}),
    )
    return snapshots


def plan_payload(policy: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "hidloom.public-repository-policy-plan.v1",
        "repository": policy["repository"],
        "api_host": policy["api_host"],
        "api_version": policy["api_version"],
        "mutating": False,
        "confirmation": f"APPLY {policy['repository']}",
        "repository_audit_only_fields": list(REPOSITORY_AUDIT_ONLY_FIELDS),
        "repository_optional_response_fields": list(
            REPOSITORY_OPTIONAL_RESPONSE_FIELDS
        ),
        "audit_only_drift_policy": (
            "stop after audit failure and inspect manually; never change visibility, "
            "archive state, discussions, or an observed legacy downloads value automatically"
        ),
        "operations": [operation.payload() for operation in mutation_operations(expected)],
    }


def unobservable_repository_fields(
    snapshots: dict[str, dict[str, Any]],
) -> list[str]:
    repository = snapshots.get("repository")
    if not isinstance(repository, dict):
        return []
    return [
        f"repository.{field}"
        for field in REPOSITORY_OPTIONAL_RESPONSE_FIELDS
        if field not in repository or repository[field] is None
    ]


def audit_payload(
    policy: dict[str, Any],
    expected: dict[str, Any],
    snapshots: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    issues = audit_snapshots(expected, snapshots)
    return {
        "schema": "hidloom.public-repository-policy-audit.v1",
        "repository": policy["repository"],
        "api_host": policy["api_host"],
        "api_version": policy["api_version"],
        "ready": not issues,
        "issues": issues,
        "unobservable_fields": unobservable_repository_fields(snapshots),
        "checks": {
            "public_main_repository": not any(item.startswith("repository.") for item in issues),
            "actions_locked": not any(item.startswith("actions_") or item.startswith("selected_actions") for item in issues),
            "workflow_permissions": not any(item.startswith("workflow_permissions") for item in issues),
            "private_vulnerability_reporting": not any(item.startswith("private_vulnerability_reporting") for item in issues),
            "main_branch_protected": not any(item.startswith("branch_protection") for item in issues),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "audit", "apply"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--gh", default="gh")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    policy_path = args.policy.resolve() if args.policy else root / "config/public-repository-policy.json"
    try:
        policy = load_json(policy_path)
        expected = expected_state(root, policy)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        parser.error(str(error))

    if args.command == "plan":
        payload = plan_payload(policy, expected)
    else:
        client = GitHubClient(
            args.gh,
            policy["api_host"],
            policy["api_version"],
        )
        try:
            applied: list[str] = []
            if args.command == "apply":
                confirmation = f"APPLY {policy['repository']}"
                if args.confirm != confirmation:
                    parser.error(f"apply requires --confirm {confirmation!r}")
                for operation in mutation_operations(expected):
                    client.request(operation.method, operation.endpoint, operation.body)
                    applied.append(operation.name)
            snapshots = collect_snapshots(client, expected)
            payload = audit_payload(policy, expected, snapshots)
            if args.command == "apply":
                payload = {
                    "schema": "hidloom.public-repository-policy-apply.v1",
                    "repository": policy["repository"],
                    "api_host": policy["api_host"],
                    "api_version": policy["api_version"],
                    "applied": applied,
                    "audit": payload,
                }
        except GitHubApiError as error:
            payload = {
                "schema": "hidloom.public-repository-policy-error.v1",
                "repository": policy["repository"],
                "api_host": policy["api_host"],
                "api_version": policy["api_version"],
                "error": str(error),
            }

    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    ready = payload.get("ready", payload.get("audit", {}).get("ready", False))
    if args.command != "plan" and not ready:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
