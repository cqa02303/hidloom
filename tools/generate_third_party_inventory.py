#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CARGO_MANIFESTS = tuple(sorted(ROOT.glob("tools/*/Cargo.toml")))
SETUP_SCRIPT = ROOT / "system/install/setup_fresh_rpi.sh"
BUILDROOT_SUMMARY = ROOT / "docs/ops/buildroot-m6-legal-summary.json"
PUBLIC_CI_WORKFLOW = ROOT / ".github/workflows/public-ci.yml"
GITHUB_ACTIONS_LOCK = ROOT / "config/github-actions-lock.json"
GITHUB_ACTION_RE = re.compile(
    r"^\s*(?:-\s*)?uses:\s*"
    r"(?P<repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@(?P<commit>[0-9a-f]{40})"
    r"\s+#\s+v(?P<version>\d+\.\d+\.\d+)\s*$",
    re.MULTILINE,
)
NON_REDISTRIBUTED_SCOPES = {"ci-action-reference", "external-install-dependency"}


def cargo_components() -> list[dict[str, Any]]:
    components: dict[tuple[str, str], dict[str, Any]] = {}
    for manifest in CARGO_MANIFESTS:
        result = subprocess.run(
            [
                "cargo",
                "metadata",
                "--offline",
                "--format-version",
                "1",
                "--manifest-path",
                str(manifest),
            ],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        metadata = json.loads(result.stdout)
        workspace = set(metadata["workspace_members"])
        for package in metadata["packages"]:
            if package["id"] in workspace:
                continue
            key = (package["name"], package["version"])
            components[key] = {
                "ecosystem": "cargo",
                "name": package["name"],
                "version": package["version"],
                "license": package.get("license") or "UNKNOWN",
                "source": package.get("repository") or package.get("homepage") or "Cargo.lock",
                "review": "complete" if package.get("license") else "required",
                "distribution_scope": "linked-binary",
            }
    return [components[key] for key in sorted(components)]


def shell_package_block(text: str, marker: str) -> list[str]:
    match = re.search(marker + r"(?P<body>(?:\s*\\?\n?\s*[A-Za-z0-9_.+-]+)+)", text)
    if not match:
        return []
    return re.findall(r"^[ \t]*([A-Za-z0-9_.+-]+)[ \t]*\\?$", match.group("body"), re.MULTILINE)


def shell_array_values(text: str, variable: str) -> list[str]:
    values: list[str] = []
    pattern = re.compile(
        rf"(?:local\s+)?{re.escape(variable)}\s*(?:\+)?=\s*\((?P<body>.*?)\)",
        re.DOTALL,
    )
    for match in pattern.finditer(text):
        lexer = shlex.shlex(match.group("body"), posix=True)
        lexer.whitespace_split = True
        lexer.commenters = "#"
        values.extend(token for token in lexer if re.fullmatch(r"[A-Za-z0-9_.+-]+", token))
    return values


def system_components() -> list[dict[str, Any]]:
    text = SETUP_SCRIPT.read_text(encoding="utf-8")
    apt = shell_array_values(text, "packages") or shell_package_block(text, r"apt-get install -y \\\n")
    pip = shell_package_block(text, r"python3 -m pip install --break-system-packages --upgrade \\\n")
    components = []
    for ecosystem, names in (("debian", apt), ("pypi", pip)):
        for name in sorted(set(names)):
            components.append(
                {
                    "ecosystem": ecosystem,
                    "name": name,
                    "version": "distribution-selected" if ecosystem == "debian" else "unpinned",
                    "license": "REVIEW_REQUIRED",
                    "source": "system/install/setup_fresh_rpi.sh",
                    "review": "not-redistributed",
                    "distribution_scope": "external-install-dependency",
                }
            )
    return components


def github_action_components() -> list[dict[str, Any]]:
    text = PUBLIC_CI_WORKFLOW.read_text(encoding="utf-8")
    lock = json.loads(GITHUB_ACTIONS_LOCK.read_text(encoding="utf-8"))
    if lock["schema"] != "hidloom.github-actions-lock.v1":
        raise ValueError("unsupported GitHub Actions lock schema")
    metadata = {item["repository"]: item for item in lock["actions"]}
    components: dict[str, dict[str, Any]] = {}
    for match in GITHUB_ACTION_RE.finditer(text):
        repository = match.group("repository")
        if repository not in metadata:
            raise ValueError(f"unreviewed public GitHub Action: {repository}")
        action = metadata[repository]
        if match.group("commit") != action["commit_sha"]:
            raise ValueError(f"GitHub Action commit does not match lock: {repository}")
        if match.group("version") != action["version"]:
            raise ValueError(f"GitHub Action version does not match lock: {repository}")
        candidate = {
            "ecosystem": "github-actions",
            "name": repository,
            "version": match.group("version"),
            "license": action["license"],
            "source": f"https://github.com/{repository}/tree/{match.group('commit')}",
            "review": "not-redistributed",
            "distribution_scope": "ci-action-reference",
            "commit_sha": match.group("commit"),
        }
        previous = components.setdefault(repository, candidate)
        if previous != candidate:
            raise ValueError(f"inconsistent public GitHub Action reference: {repository}")
    public_actions = {"actions/cache", "actions/checkout"}
    if set(components) != public_actions:
        missing = sorted(public_actions - set(components))
        raise ValueError(f"missing reviewed public GitHub Actions: {missing}")
    return [components[name] for name in sorted(components)]


def buildroot_components() -> list[dict[str, Any]]:
    summary = json.loads(BUILDROOT_SUMMARY.read_text(encoding="utf-8"))
    return [
        {
            "ecosystem": "buildroot",
            "name": item["name"],
            "version": item["version"],
            "license": item["license"],
            "source": f"{item['source_site']}#{item['source_archive']}",
            "review": item["review"],
            "distribution_scope": "buildroot-image-component",
            "license_evidence": item["license_evidence"],
            "source_archive_sha256": item["source_archive_sha256"],
        }
        for item in summary["target_packages"]
    ]


def inventory() -> dict[str, Any]:
    components = (
        cargo_components()
        + system_components()
        + github_action_components()
        + buildroot_components()
    )
    components.sort(key=lambda item: (item["ecosystem"], item["name"].lower(), item["version"]))
    redistributed = [
        item
        for item in components
        if item["distribution_scope"] not in NON_REDISTRIBUTED_SCOPES
    ]
    return {
        "schema": "hidloom.third-party-inventory.v2",
        "generated_from": [
            "tools/*/Cargo.lock",
            "system/install/setup_fresh_rpi.sh",
            ".github/workflows/public-ci.yml",
            "config/github-actions-lock.json",
            "docs/ops/buildroot-m6-legal-summary.json",
        ],
        "components": components,
        "summary": {
            "total": len(components),
            "complete": sum(item["review"] == "complete" for item in components),
            "not_redistributed": sum(item["review"] == "not-redistributed" for item in components),
            "review_required": sum(item["review"] == "required" for item in components),
            "redistributed_total": len(redistributed),
            "redistributed_complete": sum(
                item["review"] == "complete" for item in redistributed
            ),
            "redistributed_review_required": sum(
                item["review"] == "required" for item in redistributed
            ),
        },
    }


def markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# HIDloom Third-Party Inventory",
        "",
        "This file is generated by `tools/generate_third_party_inventory.py`.",
        "It is an inventory, not a final legal notice or source-offer determination.",
        "",
        f"- Components: {summary['total']}",
        f"- Metadata-complete: {summary['complete']}",
        f"- Not redistributed dependencies: {summary['not_redistributed']}",
        f"- Review required: {summary['review_required']}",
        f"- Redistributed components: {summary['redistributed_total']}",
        "",
        "| Ecosystem | Component | Version | Declared license | Distribution scope | Review |",
        "|---|---|---|---|---|---|",
    ]
    for item in payload["components"]:
        lines.append(
            f"| {item['ecosystem']} | {item['name']} | {item['version']} | "
            f"{item['license']} | {item['distribution_scope']} | {item['review']} |"
        )
    lines.extend(
        [
            "",
            "`external-install-dependency` entries are installed by the target package manager and are not embedded in the HIDloom split Debian packages.",
            "`ci-action-reference` entries run on GitHub-hosted infrastructure from immutable commit SHAs and are not distributed in HIDloom artifacts.",
            "Buildroot entries come from the exact M6 legal-info output rather than broad configuration guesses.",
            "Binary release source bundling remains a separate gate in `docs/ops/buildroot-m6-legal-summary.json`.",
            "Use `tools/collect_license_evidence.py` and `tools/buildroot_legal_info.py` to collect those artifacts.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the HIDloom third-party dependency inventory")
    parser.add_argument("--json", type=Path, default=ROOT / "docs/ops/third-party-inventory.json")
    parser.add_argument("--markdown", type=Path, default=ROOT / "THIRD_PARTY_NOTICES.md")
    args = parser.parse_args()
    payload = inventory()
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown.write_text(markdown(payload), encoding="utf-8")
    print(
        f"generated third-party inventory: total={payload['summary']['total']} "
        f"review_required={payload['summary']['review_required']}"
    )


if __name__ == "__main__":
    main()
