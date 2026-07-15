#!/usr/bin/env python3
"""Validate public GitHub contribution and community health files."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
ISSUE_FORMS = {
    ".github/ISSUE_TEMPLATE/bug.yml": {
        "version",
        "runtime",
        "profile",
        "expected",
        "actual",
        "reproduce",
        "safety",
    },
    ".github/ISSUE_TEMPLATE/feature.yml": {
        "problem",
        "proposal",
        "runtime",
        "compatibility",
        "terms",
    },
}
PULL_REQUEST_TEMPLATE = ".github/PULL_REQUEST_TEMPLATE.md"
PULL_REQUEST_HEADINGS = (
    "## Summary",
    "## Compatibility",
    "## Validation",
    "## Hardware Validation",
    "## Publication Checklist",
)
PULL_REQUEST_PHRASES = (
    "Raspberry Pi OS impact",
    "Buildroot inclusion decision",
    "focused tests",
    "Real-device testing",
    "No credentials, private addresses",
    "No generated release images",
    "third-party material",
    "`SECURITY.md`",
)


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to validate GitHub community files") from exc
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError("cannot parse YAML") from exc
    if not isinstance(payload, dict):
        raise ValueError("YAML root must be an object")
    return payload


def canonical_public_repository(root: Path) -> str:
    path = root / "config/public-repository-policy.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("cannot read canonical public repository policy") from exc
    repository = payload.get("repository") if isinstance(payload, dict) else None
    if not isinstance(repository, str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository
    ):
        raise ValueError("canonical public repository is invalid")
    return f"https://github.com/{repository}"


def validate_issue_form(root: Path, relative: str, expected_ids: set[str]) -> list[str]:
    path = root / relative
    if not path.is_file():
        return [f"missing:{relative}"]
    try:
        payload = load_yaml(path)
    except (OSError, RuntimeError, ValueError) as exc:
        return [f"invalid-yaml:{relative}:{exc}"]

    issues: list[str] = []
    for field in ("name", "description", "title"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            issues.append(f"missing-field:{relative}:{field}")
    labels = payload.get("labels")
    if not isinstance(labels, list) or not labels or not all(isinstance(item, str) for item in labels):
        issues.append(f"invalid-labels:{relative}")
    body = payload.get("body")
    if not isinstance(body, list) or not body:
        return sorted(set(issues + [f"invalid-body:{relative}"]))

    identifiers: list[str] = []
    for index, item in enumerate(body):
        if not isinstance(item, dict):
            issues.append(f"invalid-body-item:{relative}:{index}")
            continue
        identifier = item.get("id")
        if isinstance(identifier, str):
            identifiers.append(identifier)
        if item.get("type") == "checkboxes":
            attributes = item.get("attributes")
            options = attributes.get("options", []) if isinstance(attributes, dict) else []
            if not isinstance(options, list) or not options:
                issues.append(f"empty-checkboxes:{relative}:{identifier or index}")
            elif any(not isinstance(option, dict) or option.get("required") is not True for option in options):
                issues.append(f"optional-safety-checkbox:{relative}:{identifier or index}")
    if len(identifiers) != len(set(identifiers)):
        issues.append(f"duplicate-id:{relative}")
    missing_ids = sorted(expected_ids - set(identifiers))
    issues.extend(f"missing-id:{relative}:{identifier}" for identifier in missing_ids)

    serialized = json.dumps(payload, ensure_ascii=False).lower()
    for phrase in ("credential", "private"):
        if phrase not in serialized:
            issues.append(f"missing-safety-guidance:{relative}:{phrase}")
    if relative.endswith("bug.yml") and "security.md" not in serialized:
        issues.append(f"missing-security-route:{relative}")
    return sorted(set(issues))


def validate_issue_config(root: Path) -> list[str]:
    relative = ".github/ISSUE_TEMPLATE/config.yml"
    path = root / relative
    if not path.is_file():
        return [f"missing:{relative}"]
    try:
        payload = load_yaml(path)
    except (OSError, RuntimeError, ValueError) as exc:
        return [f"invalid-yaml:{relative}:{exc}"]
    issues: list[str] = []
    if payload.get("blank_issues_enabled") is not False:
        issues.append("blank-issues-enabled")
    links = payload.get("contact_links")
    try:
        expected_url = f"{canonical_public_repository(root)}/security/policy"
    except ValueError as exc:
        issues.append(f"invalid-public-repository-policy:{exc}")
        expected_url = ""
    if not isinstance(links, list) or not any(
        isinstance(item, dict) and item.get("url") == expected_url for item in links
    ):
        issues.append("missing-private-security-route")
    return issues


def validate_pull_request_template(root: Path) -> list[str]:
    path = root / PULL_REQUEST_TEMPLATE
    if not path.is_file():
        return [f"missing:{PULL_REQUEST_TEMPLATE}"]
    text = path.read_text(encoding="utf-8")
    issues = [
        f"missing-pr-heading:{heading.removeprefix('## ')}"
        for heading in PULL_REQUEST_HEADINGS
        if heading not in text
    ]
    issues.extend(
        f"missing-pr-guidance:{phrase}"
        for phrase in PULL_REQUEST_PHRASES
        if phrase not in text
    )
    checkbox_count = len(re.findall(r"(?m)^- \[ \] ", text))
    if checkbox_count < 8:
        issues.append(f"insufficient-pr-checklist:{checkbox_count}")
    return sorted(set(issues))


def validate(root: Path) -> list[str]:
    issues: list[str] = []
    for relative, expected_ids in ISSUE_FORMS.items():
        issues.extend(validate_issue_form(root, relative, expected_ids))
    issues.extend(validate_issue_config(root))
    issues.extend(validate_pull_request_template(root))
    return sorted(set(issues))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    issues = validate(root)
    if issues:
        for issue in issues:
            print(issue, file=sys.stderr)
        raise SystemExit(1)
    print("ok: public community health files are complete and safe")


if __name__ == "__main__":
    main()
