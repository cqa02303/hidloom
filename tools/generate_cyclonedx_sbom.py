#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
import uuid

ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def component_ref(item: dict[str, Any]) -> str:
    return f"third-party:{item['ecosystem']}:{item['name']}:{item['version']}"


def purl(item: dict[str, Any]) -> str | None:
    version = item["version"]
    if version in {"distribution-selected", "unpinned", "selected-by-Buildroot-config"}:
        return None
    if item["ecosystem"] == "github-actions":
        return f"pkg:github/{item['name']}@{version}"
    ecosystem = {"cargo": "cargo", "pypi": "pypi", "debian": "deb/debian"}.get(item["ecosystem"])
    if not ecosystem:
        return None
    return f"pkg:{ecosystem}/{item['name']}@{version}"


def generate(root: Path) -> dict[str, Any]:
    report = load_json(root / "PUBLIC_EXPORT_REPORT.json")
    inventory = load_json(root / "docs/ops/third-party-inventory.json")
    identity = load_json(root / "config/project-identity.json")
    source_provenance = report["source_provenance"]
    source_commit = source_provenance["base_commit"]
    version = report["initial_version"]
    if source_provenance["publishable"]:
        source_identity = source_commit
        root_ref = f"pkg:github/cqa02303/hidloom@{version}?vcs_url=git%2Bhttps://github.com/cqa02303/hidloom.git%40{source_commit}"
    else:
        source_identity = source_provenance["selected_snapshot_sha256"]
        root_ref = f"pkg:github/cqa02303/hidloom@{version}"
    serial = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"https://github.com/cqa02303/hidloom/{source_provenance['mode']}/{source_identity}/{version}",
    )
    components = []
    for item in inventory["components"]:
        component: dict[str, Any] = {
            "type": "application" if item["ecosystem"] == "github-actions" else "library",
            "bom-ref": component_ref(item),
            "group": item["ecosystem"],
            "name": item["name"],
            "version": item["version"],
            "properties": [
                {"name": "hidloom:license-review", "value": item["review"]},
                {"name": "hidloom:inventory-source", "value": item["source"]},
                {"name": "hidloom:distribution-scope", "value": item["distribution_scope"]},
            ],
        }
        license_name = item["license"]
        if license_name not in {"UNKNOWN", "REVIEW_REQUIRED"}:
            if item["ecosystem"] == "cargo":
                component["licenses"] = [{"expression": license_name}]
            else:
                component["licenses"] = [{"license": {"name": license_name}}]
        package_url = purl(item)
        if package_url:
            component["purl"] = package_url
        components.append(component)
    refs = [item["bom-ref"] for item in components]
    return {
        "$schema": "https://cyclonedx.org/schema/bom-1.7.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.7",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "bom-ref": root_ref,
                "name": identity["project_name"],
                "version": version,
                "licenses": [{"expression": identity["license"]}],
                "purl": root_ref,
                "properties": [
                    {"name": "hidloom:source-base-commit", "value": source_commit},
                    {"name": "hidloom:source-mode", "value": source_provenance["mode"]},
                    {
                        "name": "hidloom:source-snapshot-sha256",
                        "value": source_provenance["selected_snapshot_sha256"],
                    },
                    {"name": "hidloom:device-profiles", "value": ",".join(identity["device_profiles"])},
                ],
            }
        },
        "components": components,
        "dependencies": [{"ref": root_ref, "dependsOn": refs}]
        + [{"ref": ref, "dependsOn": []} for ref in refs],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a deterministic CycloneDX SBOM for HIDloom")
    parser.add_argument("root", nargs="?", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output or root / "SBOM.cdx.json"
    output.write_text(json.dumps(generate(root), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"generated CycloneDX SBOM: {output}")


if __name__ == "__main__":
    main()
