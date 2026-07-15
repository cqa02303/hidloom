#!/usr/bin/env python3
"""Reject mutable or over-broad GitHub Actions workflow dependencies."""
from __future__ import annotations

import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"

ACTION_RE = re.compile(r"(?P<repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@(?P<sha>[0-9a-f]{40})$")
USES_RE = re.compile(
    r"^\s*(?:-\s*)?uses:\s*(?P<reference>[^\s#]+)\s+#\s+(?P<version>v\d+\.\d+\.\d+)\s*$"
)
JOB_RE = re.compile(r"^  (?P<name>[A-Za-z0-9_-]+):\s*$")


def job_blocks(workflow: str) -> dict[str, str]:
    lines = workflow.splitlines()
    jobs_index = lines.index("jobs:")
    starts = [
        (index, match.group("name"))
        for index, line in enumerate(lines[jobs_index + 1 :], start=jobs_index + 1)
        if (match := JOB_RE.fullmatch(line))
    ]
    assert starts, "workflow has no jobs"
    blocks = {}
    for position, (start, name) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        blocks[name] = "\n".join(lines[start:end])
    return blocks


def action_lock() -> tuple[str, dict[str, dict[str, str]]]:
    payload = json.loads((ROOT / "config/github-actions-lock.json").read_text(encoding="utf-8"))
    assert payload["schema"] == "hidloom.github-actions-lock.v1"
    actions = {item["repository"]: item for item in payload["actions"]}
    assert len(actions) == len(payload["actions"])
    for repository, item in actions.items():
        assert re.fullmatch(r"[0-9a-f]{40}", item["commit_sha"]), repository
        assert re.fullmatch(r"\d+\.\d+\.\d+", item["version"]), repository
        assert item["license"] == "MIT", repository
        assert item["release"] == (
            f"https://github.com/{repository}/releases/tag/v{item['version']}"
        )
    return payload["runner"], actions


def validate_workflow(
    path: Path, runner: str, actions: dict[str, dict[str, str]]
) -> tuple[int, set[str]]:
    workflow = path.read_text(encoding="utf-8")
    assert "pull_request_target:" not in workflow, path
    assert "write-all" not in workflow, path
    assert "--allow-dirty-source" not in workflow, path
    assert re.search(r"(?m)^permissions:\n  contents: read$", workflow), path

    jobs = job_blocks(workflow)
    for name, block in jobs.items():
        assert f"runs-on: {runner}" in block, f"{path}:{name}: runner"
        assert re.search(r"(?m)^    timeout-minutes: [1-9][0-9]*$", block), (
            f"{path}:{name}: timeout"
        )

    referenced_actions = set()
    checkout_count = 0
    for line_number, line in enumerate(workflow.splitlines(), start=1):
        if "uses:" not in line:
            continue
        match = USES_RE.fullmatch(line)
        assert match, f"{path}:{line_number}: action must use a full SHA and version comment"
        action = ACTION_RE.fullmatch(match.group("reference"))
        assert action, f"{path}:{line_number}: mutable action reference"
        repository = action.group("repository")
        assert repository in actions, f"{path}:{line_number}: {repository}"
        locked = actions[repository]
        assert action.group("sha") == locked["commit_sha"], f"{path}:{line_number}: lock"
        assert match.group("version") == f"v{locked['version']}", (
            f"{path}:{line_number}: version"
        )
        referenced_actions.add(repository)
        checkout_count += repository == "actions/checkout"

    assert workflow.count("persist-credentials: false") == checkout_count, path
    return len(jobs), referenced_actions


def validate_dependabot() -> None:
    config = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert re.search(r"(?m)^version: 2$", config)
    assert re.search(r"(?m)^  - package-ecosystem: github-actions$", config)
    assert re.search(r"(?m)^    directory: /$", config)
    assert re.search(r"(?m)^      interval: weekly$", config)


def main() -> None:
    workflows = sorted(WORKFLOW_DIR.glob("*.yml"))
    assert workflows
    runner, actions = action_lock()
    totals = [validate_workflow(path, runner, actions) for path in workflows]
    referenced_actions = set().union(*(item[1] for item in totals))
    assert referenced_actions <= set(actions)
    if len(workflows) > 1:
        assert referenced_actions == set(actions)
    validate_dependabot()
    print(
        "ok: GitHub workflow security "
        f"({len(workflows)} workflows, {sum(item[0] for item in totals)} jobs, "
        f"{len(referenced_actions)} locked action dependencies)"
    )


if __name__ == "__main__":
    main()
