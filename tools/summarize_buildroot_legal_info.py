#!/usr/bin/env python3
"""Normalize Buildroot legal-info into deterministic public release evidence."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def checksums(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        values[relative] = digest
    return values


def package_basename(name: str, version: str) -> str:
    return f"{name}-{version}"


def normalized_version(name: str, version: str, archive: str) -> str:
    if name == "linux" and version == "custom":
        match = re.fullmatch(r"linux-([0-9a-f]{40})\.tar\.gz", archive)
        if match:
            return match.group(1)
    return version


def normalized_site(name: str, site: str) -> str:
    if not site.startswith("/"):
        return site
    if name == "hidloom-matrixd":
        return "project:daemon/matrixd"
    return "project:local-source"


def target_package(
    legal_info: Path,
    row: dict[str, str],
    checksum_map: dict[str, str],
    toolchain: dict[str, Any],
) -> dict[str, Any]:
    name = row["PACKAGE"]
    version = row["VERSION"]
    archive = row["SOURCE ARCHIVE"]
    basename = package_basename(name, version)
    source_relative = f"sources/{basename}/{archive}"
    source_saved = archive != "not saved" and source_relative in checksum_map
    declared_license_files = row["LICENSE FILES"].split()
    saved_license_files = [
        relative
        for relative in declared_license_files
        if f"licenses/{basename}/{relative}" in checksum_map
    ]
    license_name = row["LICENSE"]
    evidence = "buildroot-legal-info"
    license_metadata_complete = bool(license_name and license_name != "unknown") and len(
        saved_license_files
    ) == len(declared_license_files)
    source_sha256 = checksum_map.get(source_relative, "")
    if name == toolchain["package"] and version == toolchain["version"]:
        license_name = toolchain["license_summary"]
        evidence = "bootlin-official-summary"
        license_metadata_complete = (
            source_sha256 == toolchain["archive_sha256"]
            and toolchain.get("review") == "complete"
        )
    review = "complete" if source_saved and license_metadata_complete else "required"
    return {
        "name": name,
        "version": normalized_version(name, version, archive),
        "manifest_version": version,
        "license": license_name,
        "license_files": declared_license_files,
        "license_files_saved": saved_license_files,
        "license_evidence": evidence,
        "source_archive": archive,
        "source_archive_sha256": source_sha256,
        "source_site": normalized_site(name, row["SOURCE SITE"]),
        "source_saved": source_saved,
        "review": review,
    }


def summarize(
    legal_info: Path,
    buildroot_source_path: Path,
    toolchain_path: Path,
) -> dict[str, Any]:
    required = ("manifest.csv", "host-manifest.csv", "README", "legal-info.sha256")
    missing = [name for name in required if not (legal_info / name).is_file()]
    if missing:
        raise SystemExit(f"Buildroot legal-info is incomplete: {missing}")
    buildroot_source = load_json(buildroot_source_path)
    toolchain = load_json(toolchain_path)
    checksum_map = checksums(legal_info / "legal-info.sha256")
    packages = [
        target_package(legal_info, row, checksum_map, toolchain)
        for row in rows(legal_info / "manifest.csv")
    ]
    warnings = [
        line.removeprefix("WARNING: ")
        for line in (legal_info / "README").read_text(encoding="utf-8").splitlines()
        if line.startswith("WARNING: ")
    ]
    release_blockers = []
    if any("Buildroot source code has not been saved" in warning for warning in warnings):
        release_blockers.append(
            {
                "id": "buildroot-source-not-bundled",
                "resolution": "Archive the exact pinned Buildroot commit with the binary release.",
            }
        )
    if any("toolchain-external-bootlin" in warning for warning in warnings):
        release_blockers.append(
            {
                "id": "bootlin-toolchain-compliance-not-bundled",
                "resolution": toolchain["binary_release_requirement"],
            }
        )
    source_audit_ready = bool(packages) and all(item["review"] == "complete" for item in packages)
    return {
        "schema": "hidloom.buildroot-legal-summary.v1",
        "profile": "buildroot-m6",
        "inputs": {
            "manifest_sha256": sha256(legal_info / "manifest.csv"),
            "host_manifest_sha256": sha256(legal_info / "host-manifest.csv"),
            "readme_sha256": sha256(legal_info / "README"),
            "checksum_manifest_sha256": sha256(legal_info / "legal-info.sha256"),
        },
        "buildroot_source": {
            "repository": buildroot_source["repository"],
            "commit": buildroot_source["commit"],
            "reproducible_checkout": True,
            "included_in_legal_info": False,
        },
        "toolchain_evidence": toolchain,
        "source_audit_ready": source_audit_ready,
        "binary_release_ready": source_audit_ready and not release_blockers,
        "summary": {
            "target_packages": len(packages),
            "target_complete": sum(item["review"] == "complete" for item in packages),
            "source_archives_saved": sum(item["source_saved"] for item in packages),
            "host_packages": len(rows(legal_info / "host-manifest.csv")),
            "warnings": len(warnings),
            "release_blockers": len(release_blockers),
        },
        "warnings": warnings,
        "release_blockers": release_blockers,
        "target_packages": packages,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("legal_info", type=Path)
    parser.add_argument(
        "--buildroot-source",
        type=Path,
        default=ROOT / "config" / "buildroot-source.json",
    )
    parser.add_argument(
        "--toolchain-evidence",
        type=Path,
        default=ROOT / "config" / "buildroot-toolchain-evidence.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs" / "ops" / "buildroot-m6-legal-summary.json",
    )
    args = parser.parse_args()
    payload = summarize(
        args.legal_info.resolve(),
        args.buildroot_source.resolve(),
        args.toolchain_evidence.resolve(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
