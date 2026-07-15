#!/usr/bin/env python3
"""Regression checks for public community health and export trigger coverage."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from public_community_health import validate  # noqa: E402
from public_export import selected, tracked_files  # noqa: E402


def workflow_paths(path: Path) -> list[str]:
    import yaml

    payload = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    paths = payload["on"]["push"]["paths"]
    assert isinstance(paths, list) and all(isinstance(item, str) for item in paths)
    return paths


def path_matches(path: str, pattern: str) -> bool:
    if pattern == "*":
        return "/" not in path
    if pattern.endswith("/**"):
        return path.startswith(pattern[:-2])
    return path == pattern


def uncovered(paths: list[str], patterns: list[str]) -> list[str]:
    return sorted(path for path in paths if not any(path_matches(path, pattern) for pattern in patterns))


def main() -> None:
    assert validate(ROOT) == []

    with tempfile.TemporaryDirectory() as temporary:
        fixture = Path(temporary) / "fixture"
        shutil.copytree(ROOT / ".github", fixture / ".github")
        (fixture / "config").mkdir()
        shutil.copy2(
            ROOT / "config/public-repository-policy.json",
            fixture / "config/public-repository-policy.json",
        )
        template = fixture / ".github/PULL_REQUEST_TEMPLATE.md"
        original_template = template.read_text(encoding="utf-8")
        template.unlink()
        assert f"missing:.github/PULL_REQUEST_TEMPLATE.md" in validate(fixture)
        template.write_text(original_template.replace("## Validation", "## Checks"), encoding="utf-8")
        assert "missing-pr-heading:Validation" in validate(fixture)

        config = fixture / ".github/ISSUE_TEMPLATE/config.yml"
        config.write_text(
            config.read_text(encoding="utf-8").replace(
                "blank_issues_enabled: false", "blank_issues_enabled: true"
            ),
            encoding="utf-8",
        )
        assert "blank-issues-enabled" in validate(fixture)

        bug = fixture / ".github/ISSUE_TEMPLATE/bug.yml"
        bug.write_text(
            bug.read_text(encoding="utf-8").replace("    id: actual", "    id: expected"),
            encoding="utf-8",
        )
        fixture_issues = validate(fixture)
        assert "duplicate-id:.github/ISSUE_TEMPLATE/bug.yml" in fixture_issues
        assert "missing-id:.github/ISSUE_TEMPLATE/bug.yml:actual" in fixture_issues

    assert uncovered(["README.md", "daemon/logicd/main.py"], ["*"]) == [
        "daemon/logicd/main.py"
    ]
    private_workflow = ROOT / ".github/workflows/public-export-check.yml"
    if private_workflow.is_file():
        manifest = json.loads((ROOT / "config/public-export.json").read_text(encoding="utf-8"))
        public_paths = [path for path in tracked_files() if selected(path, manifest)]
        patterns = workflow_paths(private_workflow)
        assert not any(pattern.startswith("!") for pattern in patterns)
        assert uncovered(public_paths, patterns) == []
        for required_pattern in (
            "*",
            ".github/**",
            "config/**",
            "daemon/**",
            "docs/**",
            "script/**",
            "tools/**",
        ):
            assert required_pattern in patterns, required_pattern

    print("ok: public contribution surface and export trigger coverage")


if __name__ == "__main__":
    main()
