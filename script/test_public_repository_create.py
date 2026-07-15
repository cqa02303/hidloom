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

from public_repository_create import (  # noqa: E402
    audit_snapshot,
    creation_contract,
    plan_payload,
)
from public_repository_policy import load_json, validate_contract  # noqa: E402


def repository_payload(contract: dict[str, object]) -> dict[str, object]:
    body = contract["create_body"]
    assert isinstance(body, dict)
    return {
        "full_name": contract["repository"],
        "name": contract["name"],
        "owner": {"login": contract["owner"]},
        "visibility": "public",
        "private": False,
        "fork": False,
        "archived": False,
        "default_branch": "main",
        "description": body["description"],
        "homepage": body["homepage"],
        "has_issues": body["has_issues"],
        "has_projects": body["has_projects"],
        "has_wiki": body["has_wiki"],
        "has_discussions": body["has_discussions"],
        "is_template": body["is_template"],
        "allow_squash_merge": body["allow_squash_merge"],
        "allow_merge_commit": body["allow_merge_commit"],
        "allow_rebase_merge": body["allow_rebase_merge"],
        "allow_auto_merge": body["allow_auto_merge"],
        "delete_branch_on_merge": body["delete_branch_on_merge"],
        "size": 0,
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
endpoint = next(item for item in args if item.startswith("/"))
body = json.loads(sys.stdin.read()) if "--input" in args else None
state_path = Path(os.environ["HIDLOOM_FAKE_GH_STATE"])
state = json.loads(state_path.read_text(encoding="utf-8"))
record = {"method": method, "endpoint": endpoint, "body": body, "args": args}
with Path(os.environ["HIDLOOM_FAKE_GH_LOG"]).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(record, sort_keys=True) + "\\n")

if method == "GET" and endpoint == "/user":
    print(json.dumps({"login": state["authenticated_login"]}))
elif method == "GET" and endpoint == "/repos/cqa02303/hidloom":
    if state["repository"] is None:
        print("gh: Not Found (HTTP 404)", file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps(state["repository"]))
elif method == "GET" and endpoint == "/repos/cqa02303/hidloom/branches?per_page=100":
    print(json.dumps(state["branches"]))
elif method == "GET" and endpoint == "/repos/cqa02303/hidloom/tags?per_page=100":
    print(json.dumps(state["tags"]))
elif method == "POST" and endpoint == "/user/repos":
    if state["repository"] is not None:
        print("gh: repository already exists (HTTP 422)", file=sys.stderr)
        raise SystemExit(1)
    state["repository"] = {
        "full_name": "cqa02303/hidloom",
        "name": body["name"],
        "owner": {"login": state["authenticated_login"]},
        "visibility": "private" if body["private"] else "public",
        "private": body["private"],
        "fork": False,
        "archived": False,
        "default_branch": "main",
        "description": body["description"],
        "homepage": body["homepage"],
        "has_issues": body["has_issues"],
        "has_projects": body["has_projects"],
        "has_wiki": body["has_wiki"],
        "has_discussions": body["has_discussions"],
        "is_template": body["is_template"],
        "allow_squash_merge": body["allow_squash_merge"],
        "allow_merge_commit": body["allow_merge_commit"],
        "allow_rebase_merge": body["allow_rebase_merge"],
        "allow_auto_merge": body["allow_auto_merge"],
        "delete_branch_on_merge": body["delete_branch_on_merge"],
        "size": 0,
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")
    print(json.dumps(state["repository"]))
else:
    print(f"unexpected fake GitHub API request: {method} {endpoint}", file=sys.stderr)
    raise SystemExit(1)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def run_tool(
    command: str,
    fake_gh: Path,
    state: Path,
    log: Path,
    *,
    confirm: str | None = None,
) -> subprocess.CompletedProcess[str]:
    arguments = [
        "python3",
        str(ROOT / "tools/public_repository_create.py"),
        command,
        "--gh",
        str(fake_gh),
    ]
    if confirm is not None:
        arguments.extend(["--confirm", confirm])
    environment = os.environ.copy()
    environment["GH_HOST"] = "github.enterprise.invalid"
    environment["HIDLOOM_FAKE_GH_STATE"] = str(state)
    environment["HIDLOOM_FAKE_GH_LOG"] = str(log)
    return subprocess.run(
        arguments,
        capture_output=True,
        text=True,
        env=environment,
    )


def records(log: Path) -> list[dict[str, object]]:
    if not log.exists():
        return []
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
    owner_slug = "c" + "qa" + "02303"
    policy = load_json(ROOT / "config/public-repository-policy.json")
    assert policy["schema"] == "hidloom.public-repository-policy.v3"
    assert policy["api_host"] == "github.com"
    assert validate_contract(ROOT, policy) == []
    contract = creation_contract(policy)
    plan = plan_payload(contract)
    assert plan["schema"] == "hidloom.public-repository-create-plan.v1"
    assert plan["api_host"] == "github.com"
    assert plan["mutating"] is False
    assert plan["confirmation"] == "CREATE PUBLIC cqa02303/hidloom"
    assert [operation["name"] for operation in plan["operations"]] == [
        "verify-authenticated-owner",
        "verify-repository-absent",
        "create-empty-public-repository",
    ]
    create_body = contract["create_body"]
    assert create_body == {
        "name": "hidloom",
        "description": (
            "HIDloom programmable keyboard software and reproducible appliance image"
        ),
        "homepage": "https://github.com/cqa02303/hidloom",
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
    assert "license_template" not in create_body
    assert "gitignore_template" not in create_body

    invalid_policy = deepcopy(policy)
    invalid_policy["repository_creation"]["auto_init"] = True
    assert "unsafe-repository-creation:auto_init" in validate_contract(
        ROOT, invalid_policy
    )
    wrong_api_host = deepcopy(policy)
    wrong_api_host["api_host"] = "github.enterprise.invalid"
    assert "unsupported-api-host" in validate_contract(ROOT, wrong_api_host)
    unknown_creation_field = deepcopy(policy)
    unknown_creation_field["repository_creation"]["license_template"] = "gpl-3.0"
    assert "repository-creation-field-set-mismatch" in validate_contract(
        ROOT, unknown_creation_field
    )
    absent_audit = audit_snapshot(
        contract,
        {"exists": False, "repository": None, "branches": [], "tags": []},
    )
    assert absent_audit["ready"] is False
    assert absent_audit["issues"] == ["repository:not-found"]
    assert absent_audit["unobservable_fields"] == []
    assert set(absent_audit["checks"].values()) == {False}
    ready_audit = audit_snapshot(
        contract,
        {
            "exists": True,
            "repository": repository_payload(contract),
            "branches": [],
            "tags": [],
        },
    )
    assert ready_audit["ready"] is True
    assert ready_audit["unobservable_fields"] == ["repository.has_downloads"]
    observed_legacy = repository_payload(contract)
    observed_legacy["has_downloads"] = False
    observed_audit = audit_snapshot(
        contract,
        {
            "exists": True,
            "repository": observed_legacy,
            "branches": [],
            "tags": [],
        },
    )
    assert observed_audit["ready"] is True
    assert observed_audit["unobservable_fields"] == []
    observed_legacy["has_downloads"] = True
    legacy_drift = audit_snapshot(
        contract,
        {
            "exists": True,
            "repository": observed_legacy,
            "branches": [],
            "tags": [],
        },
    )
    assert legacy_drift["ready"] is False
    assert legacy_drift["issues"] == ["repository.has_downloads:mismatch"]

    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary)
        fake_gh = workspace / "gh"
        state_path = workspace / "state.json"
        log = workspace / "gh.ndjson"
        write_fake_gh(fake_gh)
        state = {
            "authenticated_login": owner_slug,
            "repository": None,
            "branches": [],
            "tags": [],
        }
        state_path.write_text(json.dumps(state), encoding="utf-8")

        audit = run_tool("audit", fake_gh, state_path, log)
        assert audit.returncode == 2
        audit_payload = json.loads(audit.stdout)
        assert audit_payload["api_host"] == "github.com"
        assert audit_payload["exists"] is False
        assert audit_payload["issues"] == ["repository:not-found"]
        assert [record["method"] for record in records(log)] == ["GET"]
        assert [record["endpoint"] for record in records(log)] == [
            "/repos/cqa02303/hidloom"
        ]

        log.unlink()
        rejected = run_tool(
            "create",
            fake_gh,
            state_path,
            log,
            confirm="CREATE PUBLIC other/repository",
        )
        assert rejected.returncode == 2
        assert "create requires --confirm" in rejected.stderr
        assert not log.exists()

        state["authenticated_login"] = "unexpected-owner"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        wrong_owner = run_tool(
            "create",
            fake_gh,
            state_path,
            log,
            confirm="CREATE PUBLIC cqa02303/hidloom",
        )
        assert wrong_owner.returncode == 2
        assert json.loads(wrong_owner.stdout)["created"] is False
        assert [record["endpoint"] for record in records(log)] == ["/user"]

        log.unlink()
        state["authenticated_login"] = owner_slug
        state_path.write_text(json.dumps(state), encoding="utf-8")
        created = run_tool(
            "create",
            fake_gh,
            state_path,
            log,
            confirm="CREATE PUBLIC cqa02303/hidloom",
        )
        assert created.returncode == 0, created.stdout + created.stderr
        created_payload = json.loads(created.stdout)
        assert created_payload["api_host"] == "github.com"
        assert created_payload["created"] is True
        assert created_payload["audit"]["ready"] is True
        assert created_payload["audit"]["unobservable_fields"] == [
            "repository.has_downloads"
        ]
        creation_records = records(log)
        assert [record["method"] for record in creation_records] == [
            "GET",
            "GET",
            "POST",
            "GET",
            "GET",
            "GET",
        ]
        posted = creation_records[2]
        assert posted["endpoint"] == "/user/repos"
        assert posted["body"] == create_body
        assert "license_template" not in posted["body"]
        assert "gitignore_template" not in posted["body"]
        assert "visibility" not in posted["body"]
        assert posted["body"]["private"] is False
        assert posted["body"]["auto_init"] is False

        log.unlink()
        repeated = run_tool(
            "create",
            fake_gh,
            state_path,
            log,
            confirm="CREATE PUBLIC cqa02303/hidloom",
        )
        assert repeated.returncode == 2
        assert "already exists" in json.loads(repeated.stdout)["error"]
        assert [record["method"] for record in records(log)] == ["GET", "GET"]

        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["repository"]["visibility"] = "private"
        state["repository"]["private"] = True
        state["branches"] = [{"name": "unexpected"}]
        state_path.write_text(json.dumps(state), encoding="utf-8")
        log.unlink()
        drift = run_tool("audit", fake_gh, state_path, log)
        assert drift.returncode == 2
        drift_payload = json.loads(drift.stdout)
        assert "repository.visibility:mismatch" in drift_payload["issues"]
        assert "repository.private:mismatch" in drift_payload["issues"]
        assert "repository.branches:not-empty" in drift_payload["issues"]
        assert drift_payload["checks"]["public_visibility"] is False

        state["repository"]["visibility"] = "public"
        state["repository"]["private"] = False
        state["repository"]["allow_merge_commit"] = True
        state["branches"] = []
        state_path.write_text(json.dumps(state), encoding="utf-8")
        log.unlink()
        merge_drift = run_tool("audit", fake_gh, state_path, log)
        assert merge_drift.returncode == 2
        merge_drift_payload = json.loads(merge_drift.stdout)
        assert "repository.allow_merge_commit:mismatch" in merge_drift_payload["issues"]
        assert merge_drift_payload["checks"]["creation_settings"] is False

    print("ok: public repository creation is empty, public, and confirmation-gated")


if __name__ == "__main__":
    main()
