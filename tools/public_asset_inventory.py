#!/usr/bin/env python3
"""Validate and report provenance for every asset in a HIDloom public tree."""
from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path
import re
import subprocess
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ASSET_SUFFIXES = {
    ".blend", ".f3d", ".gif", ".ico", ".jpeg", ".jpg", ".kicad_pcb",
    ".kicad_pro", ".kicad_sch", ".mp3", ".mp4", ".otf", ".pdf", ".png",
    ".step", ".stl", ".stp", ".svg", ".ttf", ".wav", ".webm", ".webp",
    ".wrl", ".zip",
}
GENERATED_REPORTS = {
    "PUBLIC_ASSET_PROVENANCE.json",
    "PUBLIC_ASSET_PROVENANCE.md",
    "PUBLIC_EXPORT_MANIFEST.json",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def selected(path: str, export: dict[str, Any]) -> bool:
    included = path in export["include_files"] or any(
        path.startswith(prefix) for prefix in export["include_prefixes"]
    )
    return included and not any(fnmatch.fnmatch(path, pattern) for pattern in export["exclude_globs"])


def source_paths(root: Path) -> list[str]:
    if (root / ".git").exists():
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
        )
        paths = [item.decode() for item in result.stdout.split(b"\0") if item]
        export = load_json(root / "config" / "public-export.json")
        return [path for path in paths if selected(path, export)]
    paths = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(root).parts
    ]
    export_path = root / "config" / "public-export.json"
    if export_path.is_file():
        excluded = load_json(export_path)["exclude_globs"]
        paths = [
            path for path in paths if not any(fnmatch.fnmatch(path, pattern) for pattern in excluded)
        ]
    return paths


def is_binary(path: Path) -> bool:
    try:
        path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def discover_assets(root: Path) -> list[str]:
    assets = []
    for relative in source_paths(root):
        path = root / relative
        if not path.is_file() or path.name in GENERATED_REPORTS:
            continue
        if path.suffix.lower() in ASSET_SUFFIXES or is_binary(path):
            assets.append(relative)
    return sorted(set(assets))


def validate_record(root: Path, record: dict[str, Any]) -> list[str]:
    errors = []
    required = (
        "id", "category", "provenance", "license", "license_file", "review", "paths", "evidence"
    )
    for key in required:
        if not record.get(key):
            errors.append(f"{record.get('id', '<unknown>')}:missing-{key}")
    if record.get("review") != "complete":
        errors.append(f"{record.get('id', '<unknown>')}:review-not-complete")
    license_file = record.get("license_file")
    if license_file and not (root / license_file).is_file():
        errors.append(f"{record.get('id', '<unknown>')}:missing-license-file:{license_file}")
    evidence = record.get("evidence", {})
    if evidence.get("type") == "git-first-add":
        if not re.fullmatch(r"[0-9a-f]{40}", str(evidence.get("commit", ""))):
            errors.append(f"{record.get('id', '<unknown>')}:invalid-git-commit")
    elif evidence.get("type") == "reproducible-generator":
        for key in ("generator", "test"):
            relative = evidence.get(key, "")
            if not relative or not (root / relative).is_file():
                errors.append(f"{record.get('id', '<unknown>')}:missing-{key}:{relative}")
    else:
        errors.append(f"{record.get('id', '<unknown>')}:unsupported-evidence")
    upstream = record.get("upstream_material")
    if upstream is not None and (not upstream.get("license") or not upstream.get("references")):
        errors.append(f"{record.get('id', '<unknown>')}:incomplete-upstream-material")
    return errors


def audit(root: Path, manifest_path: Path) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    invalid_records = []
    duplicate_ids = []
    duplicate_paths = []
    ids: set[str] = set()
    declared: set[str] = set()
    for record in manifest.get("records", []):
        record_id = str(record.get("id", ""))
        if record_id in ids:
            duplicate_ids.append(record_id)
        ids.add(record_id)
        invalid_records.extend(validate_record(root, record))
        for relative in record.get("paths", []):
            if Path(relative).is_absolute() or ".." in Path(relative).parts:
                invalid_records.append(f"{record_id}:unsafe-path:{relative}")
                continue
            if relative in declared:
                duplicate_paths.append(relative)
            declared.add(relative)
    actual = set(discover_assets(root))
    missing_declarations = sorted(actual - declared)
    stale_declarations = sorted(declared - actual)
    ready = (
        manifest.get("schema") == "hidloom.public-assets.v1"
        and not duplicate_ids
        and not duplicate_paths
        and not invalid_records
        and not missing_declarations
        and not stale_declarations
    )
    return {
        "schema": "hidloom.public-asset-provenance.v1",
        "ready": ready,
        "summary": {
            "records": len(manifest.get("records", [])),
            "assets": len(actual),
            "declared": len(declared),
            "missing_declarations": len(missing_declarations),
            "stale_declarations": len(stale_declarations),
            "invalid_records": len(invalid_records),
        },
        "missing_declarations": missing_declarations,
        "stale_declarations": stale_declarations,
        "duplicate_ids": sorted(duplicate_ids),
        "duplicate_paths": sorted(duplicate_paths),
        "invalid_records": sorted(invalid_records),
        "records": manifest.get("records", []),
    }


def markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# HIDloom Public Asset Provenance",
        "",
        f"- Ready: `{str(payload['ready']).lower()}`",
        f"- Asset records: {summary['records']}",
        f"- Assets: {summary['assets']}",
        f"- Missing declarations: {summary['missing_declarations']}",
        f"- Stale declarations: {summary['stale_declarations']}",
        "",
        "| Record | Category | Provenance | License | Assets | Review |",
        "|---|---|---|---|---:|---|",
    ]
    for record in payload["records"]:
        lines.append(
            f"| {record['id']} | {record['category']} | {record['provenance']} | "
            f"{record['license']} | {len(record['paths'])} | {record['review']} |"
        )
    lines.extend(["", "## Findings", ""])
    findings = (
        [f"missing declaration: `{path}`" for path in payload["missing_declarations"]]
        + [f"stale declaration: `{path}`" for path in payload["stale_declarations"]]
        + [f"duplicate path: `{path}`" for path in payload["duplicate_paths"]]
        + [f"invalid record: `{error}`" for error in payload["invalid_records"]]
    )
    lines.extend(f"- {finding}" for finding in findings or ["None"])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=ROOT)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = args.manifest or root / "config" / "public-assets.json"
    payload = audit(root, manifest)
    if not args.check_only:
        json_path = args.json or root / "PUBLIC_ASSET_PROVENANCE.json"
        markdown_path = args.markdown or root / "PUBLIC_ASSET_PROVENANCE.md"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        markdown_path.write_text(markdown(payload), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not payload["ready"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
