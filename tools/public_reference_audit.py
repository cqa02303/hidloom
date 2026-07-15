#!/usr/bin/env python3
"""Audit publication identity and repository references in a public tree."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any


GITHUB_REFERENCE_RE = re.compile(
    r"(?i)(?P<url>(?:(?:https?|git\+https)://)?github\.com/"
    r"(?P<owner>[A-Za-z0-9_.-]+)/(?P<repository>[A-Za-z0-9_.-]+)"
    r"|git@github\.com:(?P<ssh_owner>[A-Za-z0-9_.-]+)/(?P<ssh_repository>[A-Za-z0-9_.-]+)"
    r"|ssh://git@github\.com/(?P<uri_owner>[A-Za-z0-9_.-]+)/(?P<uri_repository>[A-Za-z0-9_.-]+))"
)
RAW_GITHUB_REFERENCE_RE = re.compile(
    r"(?i)(?P<url>(?:raw\.githubusercontent\.com/|api\.github\.com/repos/)"
    r"(?P<owner>[A-Za-z0-9_.-]+)/(?P<repository>[A-Za-z0-9_.-]+))"
)
ABSOLUTE_LOCAL_REMOTE_RE = re.compile(
    r"(?i)(?P<url>file:///(?:home|Users|tmp|var/tmp)/[^\s\"'`<>]*\.git(?:[/#?][^\s\"'`<>]*)?"
    r"|(?:git|ssh)://(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?/[^\s\"'`<>]+"
    r"|https?://(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?/[^\s\"'`<>]*\.git(?:[/#?][^\s\"'`<>]*)?)"
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalized_repository(match: re.Match[str]) -> tuple[str, str]:
    owner = match.groupdict().get("owner") or match.groupdict().get("ssh_owner") or match.groupdict().get("uri_owner")
    repository = (
        match.groupdict().get("repository")
        or match.groupdict().get("ssh_repository")
        or match.groupdict().get("uri_repository")
    )
    if owner is None or repository is None:
        raise ValueError("repository reference is missing an owner or name")
    return owner.lower(), repository.removesuffix(".git").lower()


def identity_findings(root: Path, policy: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    expected = policy["public_repository"]
    expected_url = f"https://{expected['host']}/{expected['owner']}/{expected['name']}"
    expected_ssh = f"git@{expected['host']}:{expected['owner']}/{expected['name']}.git"
    if expected.get("https_url") != expected_url:
        findings.append(
            {
                "severity": "block",
                "kind": "publication_policy_url_mismatch",
                "path": "config/publication-policy.json",
                "detail": expected.get("https_url"),
            }
        )
    if expected.get("ssh_url") != expected_ssh:
        findings.append(
            {
                "severity": "block",
                "kind": "publication_policy_ssh_mismatch",
                "path": "config/publication-policy.json",
                "detail": expected.get("ssh_url"),
            }
        )
    identity_path = root / "config/project-identity.json"
    export_path = root / "config/public-export.json"
    report_path = root / "PUBLIC_EXPORT_REPORT.json"
    for path, field, actual in (
        (identity_path, "public_repository", load_json(identity_path).get("public_repository")),
        (export_path, "public_repository", load_json(export_path).get("public_repository")),
        (report_path, "public_repository", load_json(report_path).get("public_repository")),
    ):
        if actual != expected["name"]:
            findings.append(
                {
                    "severity": "block",
                    "kind": "public_repository_identity_mismatch",
                    "path": path.relative_to(root).as_posix(),
                    "detail": {"field": field, "expected": expected["name"], "actual": actual},
                }
            )
    return findings


def audit(root: Path, policy_path: Path) -> dict[str, Any]:
    policy = load_json(policy_path)
    if policy.get("schema") != "hidloom.publication-policy.v1":
        raise SystemExit("unsupported publication policy schema")
    expected = policy["public_repository"]
    expected_slug = f"{expected['owner']}/{expected['name']}".lower()
    blocked_slugs = {str(item).lower() for item in policy["blocked_repository_slugs"]}
    allowed_owner_slugs = {
        str(item).lower() for item in policy["allowed_owner_repository_slugs"]
    }
    excluded = set(policy.get("excluded_scan_paths", []))
    findings = identity_findings(root, policy)
    references: list[dict[str, Any]] = []
    files_scanned = 0
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if ".git" in path.relative_to(root).parts or relative in excluded:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        files_scanned += 1
        for line_number, line in enumerate(text.splitlines(), 1):
            matches = list(GITHUB_REFERENCE_RE.finditer(line)) + list(
                RAW_GITHUB_REFERENCE_RE.finditer(line)
            )
            for match in matches:
                owner, repository = normalized_repository(match)
                slug = f"{owner}/{repository}"
                reference = {
                    "path": relative,
                    "line": line_number,
                    "slug": slug,
                    "url": match.group("url"),
                }
                references.append(reference)
                if slug in blocked_slugs:
                    findings.append(
                        {
                            "severity": "block",
                            "kind": "blocked_private_repository_reference",
                            **reference,
                        }
                    )
                elif owner == expected["owner"].lower() and slug not in allowed_owner_slugs:
                    findings.append(
                        {
                            "severity": "block",
                            "kind": "unexpected_owner_repository_reference",
                            **reference,
                        }
                    )
            for match in ABSOLUTE_LOCAL_REMOTE_RE.finditer(line):
                findings.append(
                    {
                        "severity": "block",
                        "kind": "absolute_local_repository_remote",
                        "path": relative,
                        "line": line_number,
                        "url": match.group("url"),
                    }
                )
    findings.sort(key=lambda item: (item["path"], item.get("line", 0), item["kind"]))
    blockers = [item for item in findings if item["severity"] == "block"]
    public_references = [item for item in references if item["slug"] == expected_slug]
    return {
        "schema": "hidloom.public-reference-audit.v1",
        "ready": not blockers,
        "public_repository": {
            "slug": expected_slug,
            "https_url": expected["https_url"],
            "ssh_url": expected["ssh_url"],
        },
        "summary": {
            "files_scanned": files_scanned,
            "repository_references": len(references),
            "public_repository_references": len(public_references),
            "findings": len(findings),
            "blockers": len(blockers),
        },
        "references": references,
        "findings": findings,
    }


def markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# HIDloom Public Reference Audit",
        "",
        f"- Ready: `{str(payload['ready']).lower()}`",
        f"- Expected repository: `{payload['public_repository']['https_url']}`",
        f"- Files scanned: {summary['files_scanned']}",
        f"- Repository references: {summary['repository_references']}",
        f"- Public repository references: {summary['public_repository_references']}",
        f"- Blockers: {summary['blockers']}",
        "",
        "## Findings",
        "",
    ]
    if payload["findings"]:
        lines.extend(
            f"- `{item['severity']}` `{item['kind']}` `{item['path']}`"
            + (f":{item['line']}" if item.get("line") else "")
            for item in payload["findings"]
        )
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    policy = args.policy or root / "config/publication-policy.json"
    payload = audit(root, policy)
    if not args.check_only:
        json_path = args.json or root / "PUBLIC_REFERENCE_AUDIT.json"
        markdown_path = args.markdown or root / "PUBLIC_REFERENCE_AUDIT.md"
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        markdown_path.write_text(markdown(payload), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not payload["ready"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
