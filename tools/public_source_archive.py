#!/usr/bin/env python3
"""Create a deterministic public source archive with normalized permissions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True

from public_release_bundle import deterministic_tar, load_json, sha256, validate_export_manifest


def outside_source(source: Path, path: Path) -> None:
    try:
        path.relative_to(source)
    except ValueError:
        return
    raise SystemExit(f"archive output must be outside the public source tree: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a manifest-bounded deterministic HIDloom public source archive"
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--root-name", default="hidloom-public")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    source = args.source.resolve()
    archive = args.archive.resolve()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.root_name):
        raise SystemExit(f"invalid archive root name: {args.root_name!r}")
    outside_source(source, archive)
    if args.report:
        outside_source(source, args.report.resolve())

    paths = validate_export_manifest(source)
    report = load_json(source / "PUBLIC_EXPORT_REPORT.json")
    source_provenance = report["source_provenance"]
    archive.parent.mkdir(parents=True, exist_ok=True)
    deterministic_tar(source, archive, args.root_name, paths)
    payload = {
        "schema": "hidloom.public-source-archive.v2",
        "source_commit": source_provenance["base_commit"],
        "source_tree": source_provenance["base_tree"],
        "source_snapshot_sha256": source_provenance["selected_snapshot_sha256"],
        "root_name": args.root_name,
        "file_count": len(paths),
        "archive": {
            "path": archive.name,
            "size": archive.stat().st_size,
            "sha256": sha256(archive),
        },
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        report_path = args.report.resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
