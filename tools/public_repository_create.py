#!/usr/bin/env python3
"""Plan, audit, or explicitly create the empty HIDloom public repository."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

sys.dont_write_bytecode = True

from public_repository_policy import (
    REPOSITORY_OPTIONAL_RESPONSE_FIELDS,
    load_json,
    validate_contract,
)


ROOT = Path(__file__).resolve().parents[1]


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
        *,
        allow_not_found: bool = False,
    ) -> Any | None:
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
            detail = (
                completed.stderr.strip()
                or completed.stdout.strip()
                or "unknown GitHub API error"
            )
            if allow_not_found and ("HTTP 404" in detail or "Not Found" in detail):
                return None
            raise GitHubApiError(f"{method} {endpoint}: {detail}")
        text = completed.stdout.strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise GitHubApiError(f"{method} {endpoint}: response is not JSON") from error


def creation_contract(policy: dict[str, Any]) -> dict[str, Any]:
    repository = policy["repository"]
    owner, name = repository.split("/", 1)
    creation = policy["repository_creation"]
    if creation["owner_type"] != "user":
        raise ValueError("only user-owned public repository creation is supported")
    body = {"name": name}
    body.update(
        {
            field: creation[field]
            for field in (
                "description",
                "homepage",
                "private",
                "has_issues",
                "has_projects",
                "has_wiki",
                "has_discussions",
                "has_downloads",
                "is_template",
                "auto_init",
                "allow_squash_merge",
                "allow_merge_commit",
                "allow_rebase_merge",
                "allow_auto_merge",
                "delete_branch_on_merge",
            )
        }
    )
    return {
        "repository": repository,
        "owner": owner,
        "name": name,
        "api_host": policy["api_host"],
        "api_version": policy["api_version"],
        "repository_endpoint": f"/repos/{repository}",
        "branches_endpoint": f"/repos/{repository}/branches?per_page=100",
        "tags_endpoint": f"/repos/{repository}/tags?per_page=100",
        "create_endpoint": "/user/repos",
        "create_body": body,
    }


def plan_payload(contract: dict[str, Any]) -> dict[str, Any]:
    repository = contract["repository"]
    return {
        "schema": "hidloom.public-repository-create-plan.v1",
        "repository": repository,
        "api_host": contract["api_host"],
        "api_version": contract["api_version"],
        "mutating": False,
        "confirmation": f"CREATE PUBLIC {repository}",
        "operations": [
            {
                "name": "verify-authenticated-owner",
                "method": "GET",
                "endpoint": "/user",
                "expected_login": contract["owner"],
            },
            {
                "name": "verify-repository-absent",
                "method": "GET",
                "endpoint": contract["repository_endpoint"],
                "expected_status": 404,
            },
            {
                "name": "create-empty-public-repository",
                "method": "POST",
                "endpoint": contract["create_endpoint"],
                "body": contract["create_body"],
            },
        ],
        "safeguards": [
            "refuse an authenticated GitHub account other than the configured owner",
            "refuse creation when the canonical repository already exists",
            "omit README, license template, and gitignore template initialization",
            "never delete or rename a repository during recovery",
        ],
    }


def collect_snapshot(
    client: GitHubClient,
    contract: dict[str, Any],
) -> dict[str, Any]:
    repository = client.request(
        "GET",
        contract["repository_endpoint"],
        allow_not_found=True,
    )
    if repository is None:
        return {
            "exists": False,
            "repository": None,
            "branches": [],
            "tags": [],
        }
    if not isinstance(repository, dict):
        raise GitHubApiError("repository response root is not an object")
    branches = client.request("GET", contract["branches_endpoint"])
    tags = client.request("GET", contract["tags_endpoint"])
    if not isinstance(branches, list):
        raise GitHubApiError("branches response root is not an array")
    if not isinstance(tags, list):
        raise GitHubApiError("tags response root is not an array")
    return {
        "exists": True,
        "repository": repository,
        "branches": branches,
        "tags": tags,
    }


def audit_snapshot(
    contract: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    issues: list[str] = []
    unobservable_fields: list[str] = []
    repository = snapshot.get("repository")
    if snapshot.get("exists") is not True or not isinstance(repository, dict):
        issues.append("repository:not-found")
    else:
        expected = {
            "full_name": contract["repository"],
            "name": contract["name"],
            "visibility": "public",
            "private": False,
            "fork": False,
            "archived": False,
            "description": contract["create_body"]["description"],
            "homepage": contract["create_body"]["homepage"],
            "has_issues": contract["create_body"]["has_issues"],
            "has_projects": contract["create_body"]["has_projects"],
            "has_wiki": contract["create_body"]["has_wiki"],
            "has_discussions": contract["create_body"]["has_discussions"],
            "has_downloads": contract["create_body"]["has_downloads"],
            "is_template": contract["create_body"]["is_template"],
            "allow_squash_merge": contract["create_body"]["allow_squash_merge"],
            "allow_merge_commit": contract["create_body"]["allow_merge_commit"],
            "allow_rebase_merge": contract["create_body"]["allow_rebase_merge"],
            "allow_auto_merge": contract["create_body"]["allow_auto_merge"],
            "delete_branch_on_merge": contract["create_body"]["delete_branch_on_merge"],
            "size": 0,
        }
        for field, expected_value in expected.items():
            if field in REPOSITORY_OPTIONAL_RESPONSE_FIELDS and (
                field not in repository or repository[field] is None
            ):
                unobservable_fields.append(f"repository.{field}")
                continue
            if repository.get(field) != expected_value:
                issues.append(f"repository.{field}:mismatch")
        owner = repository.get("owner")
        if not isinstance(owner, dict) or owner.get("login") != contract["owner"]:
            issues.append("repository.owner.login:mismatch")
        if snapshot.get("branches") != []:
            issues.append("repository.branches:not-empty")
        if snapshot.get("tags") != []:
            issues.append("repository.tags:not-empty")
    exists = snapshot.get("exists") is True and isinstance(repository, dict)
    return {
        "schema": "hidloom.public-repository-create-audit.v1",
        "repository": contract["repository"],
        "api_host": contract["api_host"],
        "exists": snapshot.get("exists") is True,
        "ready": not issues,
        "issues": sorted(set(issues)),
        "unobservable_fields": sorted(set(unobservable_fields)),
        "checks": {
            "canonical_identity": exists and not any(
                item.startswith("repository.full_name")
                or item.startswith("repository.name")
                or item.startswith("repository.owner")
                for item in issues
            ),
            "public_visibility": exists and not any(
                item.startswith("repository.visibility")
                or item.startswith("repository.private")
                for item in issues
            ),
            "empty_repository": exists and not any(
                item.startswith("repository.size")
                or item.startswith("repository.branches")
                or item.startswith("repository.tags")
                for item in issues
            ),
            "creation_settings": exists and not any(
                item.startswith("repository.description")
                or item.startswith("repository.homepage")
                or item.startswith("repository.has_")
                or item.startswith("repository.is_template")
                or item.startswith("repository.allow_")
                or item.startswith("repository.delete_branch_on_merge")
                or item.startswith("repository.fork")
                or item.startswith("repository.archived")
                for item in issues
            ),
        },
    }


def create_repository(
    client: GitHubClient,
    contract: dict[str, Any],
) -> dict[str, Any]:
    authenticated = client.request("GET", "/user")
    if not isinstance(authenticated, dict) or authenticated.get("login") != contract["owner"]:
        raise GitHubApiError(
            "authenticated GitHub account does not match the configured repository owner"
        )
    existing = client.request(
        "GET",
        contract["repository_endpoint"],
        allow_not_found=True,
    )
    if existing is not None:
        raise GitHubApiError("canonical public repository already exists")
    created = client.request(
        "POST",
        contract["create_endpoint"],
        contract["create_body"],
    )
    if not isinstance(created, dict):
        raise GitHubApiError("repository creation response root is not an object")
    audit = audit_snapshot(contract, collect_snapshot(client, contract))
    return {
        "schema": "hidloom.public-repository-create-result.v1",
        "repository": contract["repository"],
        "api_host": contract["api_host"],
        "created": True,
        "mutating": True,
        "audit": audit,
        "recovery": (
            "do not delete or rename automatically; inspect the repository and continue "
            "with bootstrap only when the audit is ready"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "audit", "create"))
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
        issues = validate_contract(root, policy)
        if issues:
            raise ValueError(f"invalid public repository policy: {issues}")
        contract = creation_contract(policy)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        parser.error(str(error))

    if args.command == "plan":
        payload = plan_payload(contract)
    else:
        client = GitHubClient(
            args.gh,
            contract["api_host"],
            contract["api_version"],
        )
        try:
            if args.command == "audit":
                payload = audit_snapshot(contract, collect_snapshot(client, contract))
            else:
                confirmation = f"CREATE PUBLIC {contract['repository']}"
                if args.confirm != confirmation:
                    parser.error(f"create requires --confirm {confirmation!r}")
                payload = create_repository(client, contract)
        except GitHubApiError as error:
            payload = {
                "schema": "hidloom.public-repository-create-error.v1",
                "repository": contract["repository"],
                "api_host": contract["api_host"],
                "created": False,
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
