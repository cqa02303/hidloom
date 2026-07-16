#!/usr/bin/env python3
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from public_repository_policy import (  # noqa: E402
    REPOSITORY_AUDIT_ONLY_FIELDS,
    REPOSITORY_OPTIONAL_RESPONSE_FIELDS,
    audit_snapshots,
    expected_state,
    load_json,
    mutation_operations,
    plan_payload,
    unobservable_repository_fields,
    validate_contract,
)


def compliant_snapshots(expected: dict[str, object]) -> dict[str, dict[str, object]]:
    protection = expected["branch_protection"]
    assert isinstance(protection, dict)
    branch = {
        "required_status_checks": deepcopy(protection["required_status_checks"]),
        "required_pull_request_reviews": None,
        "restrictions": None,
    }
    for field in (
        "enforce_admins",
        "required_linear_history",
        "allow_force_pushes",
        "allow_deletions",
        "block_creations",
        "required_conversation_resolution",
        "lock_branch",
    ):
        branch[field] = {"enabled": protection[field]}
    repository = deepcopy(expected["repository"])
    repository.pop("has_downloads")
    return {
        "repository": repository,
        "actions_permissions": deepcopy(expected["actions_permissions"]),
        "selected_actions": deepcopy(expected["selected_actions"]),
        "workflow_permissions": deepcopy(expected["workflow_permissions"]),
        "private_vulnerability_reporting": deepcopy(
            expected["private_vulnerability_reporting"]
        ),
        "branch_protection": branch,
    }


def write_fake_gh(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
method = args[args.index("--method") + 1]
endpoint = next(item for item in args if item.startswith("/repos/"))
body = json.loads(sys.stdin.read()) if "--input" in args else None
record = {"method": method, "endpoint": endpoint, "body": body, "args": args}
with Path(os.environ["HIDLOOM_FAKE_GH_LOG"]).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(record, sort_keys=True) + "\\n")
if method == "GET":
    fixtures = json.loads(Path(os.environ["HIDLOOM_FAKE_GH_FIXTURE"]).read_text())
    payload = fixtures[endpoint]
    status = payload.pop("__error_status__", None)
    print(json.dumps(payload))
    if status is not None:
        print(payload.get("message", "GitHub API error"), file=sys.stderr)
        raise SystemExit(1)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def run_tool(
    command: str,
    fake_gh: Path,
    fixture: Path,
    log: Path,
    *,
    confirm: str | None = None,
) -> subprocess.CompletedProcess[str]:
    args = [
        "python3",
        str(ROOT / "tools/public_repository_policy.py"),
        command,
        "--gh",
        str(fake_gh),
    ]
    if confirm is not None:
        args.extend(["--confirm", confirm])
    environment = os.environ.copy()
    environment["GH_HOST"] = "github.enterprise.invalid"
    environment["HIDLOOM_FAKE_GH_FIXTURE"] = str(fixture)
    environment["HIDLOOM_FAKE_GH_LOG"] = str(log)
    return subprocess.run(args, capture_output=True, text=True, env=environment)


def read_records(log: Path) -> list[dict[str, object]]:
    parsed = [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if line
    ]
    for record in parsed:
        arguments = record["args"]
        assert isinstance(arguments, list)
        host_index = arguments.index("--hostname")
        assert arguments[host_index + 1] == "github.com"
    return parsed


def main() -> None:
    policy = load_json(ROOT / "config/public-repository-policy.json")
    assert policy["schema"] == "hidloom.public-repository-policy.v3"
    assert policy["api_host"] == "github.com"
    assert validate_contract(ROOT, policy) == []
    expected = expected_state(ROOT, policy)
    assert expected["branch_protection"]["required_status_checks"] == {
        "strict": True,
        "contexts": ["validate"],
    }
    plan = plan_payload(policy, expected)
    assert plan["schema"] == "hidloom.public-repository-policy-plan.v1"
    assert plan["api_host"] == "github.com"
    assert plan["mutating"] is False
    assert plan["confirmation"] == "APPLY cqa02303/hidloom"
    assert plan["repository_audit_only_fields"] == list(REPOSITORY_AUDIT_ONLY_FIELDS)
    assert plan["repository_optional_response_fields"] == list(
        REPOSITORY_OPTIONAL_RESPONSE_FIELDS
    )
    assert "never change visibility" in plan["audit_only_drift_policy"]
    operations = mutation_operations(expected)
    assert [operation.name for operation in operations] == [
        "repository-settings",
        "actions-permissions",
        "selected-actions",
        "workflow-permissions",
        "private-vulnerability-reporting",
        "branch-protection",
    ]
    selected = next(operation for operation in operations if operation.name == "selected-actions")
    assert selected.body == {
        "github_owned_allowed": False,
        "verified_allowed": False,
        "patterns_allowed": [
            "actions/cache@55cc8345863c7cc4c66a329aec7e433d2d1c52a9",
            "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0",
        ],
    }
    repository_settings = next(
        operation for operation in operations if operation.name == "repository-settings"
    )
    assert repository_settings.body == {
        "description": (
            "HIDloom programmable keyboard software and reproducible appliance image"
        ),
        "homepage": "https://github.com/cqa02303/hidloom",
        "default_branch": "main",
        "has_issues": True,
        "has_projects": False,
        "has_wiki": False,
        "is_template": False,
        "allow_squash_merge": True,
        "allow_merge_commit": False,
        "allow_rebase_merge": True,
        "allow_auto_merge": False,
        "delete_branch_on_merge": True,
        "security_and_analysis": {
            "secret_scanning": {"status": "enabled"},
            "secret_scanning_push_protection": {"status": "enabled"},
        },
    }
    assert set(REPOSITORY_AUDIT_ONLY_FIELDS).isdisjoint(repository_settings.body)

    snapshots = compliant_snapshots(expected)
    assert audit_snapshots(expected, snapshots) == []
    assert unobservable_repository_fields(snapshots) == [
        "repository.has_downloads"
    ]
    observed_legacy = deepcopy(snapshots)
    observed_legacy["repository"]["has_downloads"] = False
    assert audit_snapshots(expected, observed_legacy) == []
    assert unobservable_repository_fields(observed_legacy) == []
    omitted_false = deepcopy(snapshots)
    omitted_false["branch_protection"].pop("block_creations")
    assert audit_snapshots(expected, omitted_false) == []
    drift = deepcopy(snapshots)
    drift["repository"]["visibility"] = "private"
    drift["repository"]["has_discussions"] = True
    drift["repository"]["has_downloads"] = True
    drift["repository"]["allow_merge_commit"] = True
    drift["actions_permissions"]["sha_pinning_required"] = False
    drift["selected_actions"]["patterns_allowed"] = []
    drift["branch_protection"]["required_status_checks"]["contexts"] = ["other"]
    issues = audit_snapshots(expected, drift)
    assert "repository.visibility:mismatch" in issues
    assert "repository.has_discussions:mismatch" in issues
    assert "repository.has_downloads:mismatch" in issues
    assert "repository.allow_merge_commit:mismatch" in issues
    assert "actions_permissions.sha_pinning_required:mismatch" in issues
    assert "selected_actions.patterns_allowed:mismatch" in issues
    assert "branch_protection.required_status_checks.contexts:mismatch" in issues

    invalid_policy = deepcopy(policy)
    invalid_policy["selected_actions"]["locked_repositories"] = ["actions/checkout"]
    assert "policy-workflow-action-set-mismatch" in validate_contract(ROOT, invalid_policy)
    wrong_api_host = deepcopy(policy)
    wrong_api_host["api_host"] = "github.enterprise.invalid"
    assert "unsupported-api-host" in validate_contract(ROOT, wrong_api_host)

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        fake_gh = workspace / "gh"
        fixture = workspace / "fixture.json"
        log = workspace / "gh.ndjson"
        write_fake_gh(fake_gh)
        endpoints = expected["endpoints"]
        assert isinstance(endpoints, dict)
        fixture.write_text(
            json.dumps({endpoints[name]: value for name, value in snapshots.items()}),
            encoding="utf-8",
        )

        audit = run_tool("audit", fake_gh, fixture, log)
        assert audit.returncode == 0, audit.stdout + audit.stderr
        audit_payload = json.loads(audit.stdout)
        assert audit_payload["api_host"] == "github.com"
        assert audit_payload["ready"] is True
        assert audit_payload["unobservable_fields"] == [
            "repository.has_downloads"
        ]
        records = read_records(log)
        assert len(records) == 6
        assert {record["method"] for record in records} == {"GET"}
        assert all("X-GitHub-Api-Version: 2026-03-10" in record["args"] for record in records)

        log.unlink()
        rejected = run_tool(
            "apply",
            fake_gh,
            fixture,
            log,
            confirm="APPLY another/repository",
        )
        assert rejected.returncode == 2
        assert "apply requires --confirm" in rejected.stderr
        assert not log.exists()

        applied = run_tool(
            "apply",
            fake_gh,
            fixture,
            log,
            confirm="APPLY cqa02303/hidloom",
        )
        assert applied.returncode == 0, applied.stdout + applied.stderr
        applied_payload = json.loads(applied.stdout)
        assert applied_payload["api_host"] == "github.com"
        assert applied_payload["applied"] == [operation.name for operation in operations]
        assert applied_payload["audit"]["ready"] is True
        assert applied_payload["audit"]["unobservable_fields"] == [
            "repository.has_downloads"
        ]
        records = read_records(log)
        assert [record["method"] for record in records] == [
            "PATCH",
            "PUT",
            "PUT",
            "PUT",
            "PUT",
            "PUT",
            "GET",
            "GET",
            "GET",
            "GET",
            "GET",
            "GET",
        ]
        private_reporting = next(
            record
            for record in records
            if record["endpoint"].endswith("private-vulnerability-reporting")
            and record["method"] == "PUT"
        )
        assert private_reporting["body"] is None

        drift_fixture = deepcopy({endpoints[name]: value for name, value in snapshots.items()})
        drift_fixture[endpoints["actions_permissions"]]["sha_pinning_required"] = False
        fixture.write_text(json.dumps(drift_fixture), encoding="utf-8")
        drift_audit = run_tool("audit", fake_gh, fixture, log)
        assert drift_audit.returncode == 2
        assert json.loads(drift_audit.stdout)["ready"] is False

        log.unlink()
        preapply_fixture = deepcopy(
            {endpoints[name]: value for name, value in snapshots.items()}
        )
        preapply_fixture[endpoints["actions_permissions"]] = {
            "enabled": True,
            "allowed_actions": "all",
            "sha_pinning_required": False,
        }
        preapply_fixture[endpoints["selected_actions"]] = {
            "__error_status__": "409",
            "message": "Conflict",
            "status": "409",
        }
        preapply_fixture[endpoints["branch_protection"]] = {
            "__error_status__": "404",
            "message": "Branch not protected",
            "status": "404",
        }
        fixture.write_text(json.dumps(preapply_fixture), encoding="utf-8")
        preapply_audit = run_tool("audit", fake_gh, fixture, log)
        assert preapply_audit.returncode == 2
        preapply_payload = json.loads(preapply_audit.stdout)
        assert preapply_payload["schema"] == "hidloom.public-repository-policy-audit.v1"
        assert preapply_payload["ready"] is False
        assert "actions_permissions.allowed_actions:mismatch" in preapply_payload["issues"]
        assert "actions_permissions.sha_pinning_required:mismatch" in preapply_payload["issues"]
        assert "selected_actions.github_owned_allowed:missing" in preapply_payload["issues"]
        assert "branch_protection.required_status_checks:expected-object" in preapply_payload["issues"]
        records = read_records(log)
        assert len(records) == 5
        assert not any(
            record["endpoint"] == endpoints["selected_actions"] for record in records
        )

    print("ok: public repository policy is declarative, auditable, and confirmation-gated")


if __name__ == "__main__":
    main()
