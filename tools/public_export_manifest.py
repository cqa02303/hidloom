#!/usr/bin/env python3
"""Verify or materialize the exact file set in a HIDloom public export manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
from typing import Any


MANIFEST_NAME = "PUBLIC_EXPORT_MANIFEST.json"
REPORT_NAME = "PUBLIC_EXPORT_REPORT.json"
MANIFEST_SCHEMA = "hidloom.public-export-manifest.v2"
REPORT_SCHEMA = "hidloom.public-export-report.v2"
PROVENANCE_SCHEMA = "hidloom.source-provenance.v1"
HEX40_RE = re.compile(r"[0-9a-f]{40}")
HEX64_RE = re.compile(r"[0-9a-f]{64}")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def load_manifest(root: Path) -> dict[str, Any]:
    path = root / MANIFEST_NAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != MANIFEST_SCHEMA:
        raise SystemExit("unsupported public export manifest schema")
    return payload


def load_report(root: Path) -> dict[str, Any]:
    path = root / REPORT_NAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != REPORT_SCHEMA:
        raise SystemExit("unsupported public export report schema")
    return payload


def validate_source_provenance(provenance: Any) -> list[str]:
    if not isinstance(provenance, dict):
        return ["source-provenance:not-object"]
    issues: list[str] = []
    if provenance.get("schema") != PROVENANCE_SCHEMA:
        issues.append("source-provenance:schema")
    mode = provenance.get("mode")
    publishable = provenance.get("publishable")
    if mode not in {"clean-head", "dirty-worktree"}:
        issues.append("source-provenance:mode")
    if not isinstance(publishable, bool):
        issues.append("source-provenance:publishable-type")
    elif publishable != (mode == "clean-head"):
        issues.append("source-provenance:publishable-mode-mismatch")
    for field in ("base_commit", "base_tree"):
        if not HEX40_RE.fullmatch(str(provenance.get(field, ""))):
            issues.append(f"source-provenance:{field}")
    if not isinstance(provenance.get("base_revision_count"), int) or provenance.get(
        "base_revision_count", 0
    ) <= 0:
        issues.append("source-provenance:base_revision_count")
    if not isinstance(provenance.get("selected_path_count"), int) or provenance.get(
        "selected_path_count", 0
    ) <= 0:
        issues.append("source-provenance:selected_path_count")
    if not HEX64_RE.fullmatch(str(provenance.get("selected_snapshot_sha256", ""))):
        issues.append("source-provenance:selected_snapshot_sha256")
    return issues


def validate_source_selection(selection: Any, file_count: Any) -> list[str]:
    if not isinstance(selection, dict):
        return ["source-selection:not-object"]
    expected_fields = {
        "tracked_paths",
        "public_source_paths",
        "private_only_paths",
        "generated_output_paths",
        "unclassified_paths",
    }
    issues: list[str] = []
    if set(selection) != expected_fields:
        issues.append("source-selection:fields")
    if type(file_count) is not int or file_count <= 0:
        issues.append("source-selection:file-count")
    for field in expected_fields:
        value = selection.get(field)
        if type(value) is not int or value < 0:
            issues.append(f"source-selection:{field}")
    if issues:
        return sorted(set(issues))
    if selection["tracked_paths"] <= 0:
        issues.append("source-selection:tracked-paths-empty")
    if selection["public_source_paths"] != file_count:
        issues.append("source-selection:public-source-count-mismatch")
    classified = sum(
        selection[field]
        for field in (
            "public_source_paths",
            "private_only_paths",
            "generated_output_paths",
            "unclassified_paths",
        )
    )
    if classified != selection["tracked_paths"]:
        issues.append("source-selection:tracked-count-mismatch")
    if selection["unclassified_paths"] != 0:
        issues.append("source-selection:unclassified-paths")
    return sorted(set(issues))


def verification_issues(verification: dict[str, Any]) -> list[str]:
    return [
        *verification["mismatches"],
        *verification["source_provenance_issues"],
        *verification["source_selection_issues"],
    ]


def safe_relative(value: str) -> Path:
    relative = PurePosixPath(value)
    if (
        relative.is_absolute() or not relative.parts or ".." in relative.parts
        or relative.as_posix() != value or "\\" in value or ":" in value or "\0" in value
    ):
        raise SystemExit(f"unsafe public export manifest path: {value}")
    return Path(*relative.parts)


def entry_content(path: Path, kind: str) -> bytes:
    if kind == "symlink":
        if not path.is_symlink():
            raise FileNotFoundError(path)
        return os.readlink(path).encode()
    if kind != "file":
        raise SystemExit(f"unsupported public export manifest entry kind: {kind}")
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    return path.read_bytes()


def verify(root: Path, *, allow_draft_source: bool = False) -> dict[str, Any]:
    manifest_path = root / MANIFEST_NAME
    manifest = load_manifest(root)
    report = load_report(root)
    mismatches: list[str] = []
    manifest_provenance = manifest.get("source_provenance")
    report_provenance = report.get("source_provenance")
    provenance_issues = validate_source_provenance(manifest_provenance)
    provenance_issues.extend(
        f"report-{issue}" for issue in validate_source_provenance(report_provenance)
    )
    if manifest_provenance != report_provenance:
        provenance_issues.append("source-provenance:report-manifest-mismatch")
    if isinstance(report_provenance, dict) and report.get("file_count") != report_provenance.get(
        "selected_path_count"
    ):
        provenance_issues.append("source-provenance:selected-path-count-mismatch")
    selection_issues = validate_source_selection(
        report.get("source_selection"),
        report.get("file_count"),
    )
    source_publishable = (
        isinstance(manifest_provenance, dict)
        and manifest_provenance.get("publishable") is True
    )
    if not source_publishable and not allow_draft_source:
        provenance_issues.append("source-provenance:not-publishable")
    seen: set[str] = set()
    for item in manifest["files"]:
        value = str(item["path"])
        try:
            relative = safe_relative(value)
        except SystemExit:
            mismatches.append(f"unsafe:{value}")
            continue
        if value in seen:
            mismatches.append(f"duplicate:{value}")
            continue
        seen.add(value)
        path = root / relative
        try:
            content = entry_content(path, str(item["kind"]))
        except FileNotFoundError:
            mismatches.append(f"missing:{value}")
            continue
        if len(content) != int(item["size"]):
            mismatches.append(f"size:{value}")
        if sha256_bytes(content) != str(item["sha256"]):
            mismatches.append(f"hash:{value}")
        expected_mode = int(item.get("mode", -1))
        if item["kind"] == "file":
            actual_mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
            if expected_mode not in {0o644, 0o755} or (
                os.name != "nt" and actual_mode != expected_mode
            ):
                mismatches.append(f"mode:{value}")
        elif expected_mode != 0o777:
            mismatches.append(f"mode:{value}")
        if path.is_symlink():
            target = Path(os.readlink(path))
            if target.is_absolute() or ".." in target.parts:
                mismatches.append(f"unsafe-symlink:{value}")
    return {
        "schema": "hidloom.public-export-manifest-verification.v2",
        "ready": not mismatches and not provenance_issues and not selection_issues,
        "source_publishable": source_publishable,
        "source_provenance": manifest_provenance,
        "source_provenance_issues": provenance_issues,
        "source_selection_issues": selection_issues,
        "manifest": {
            "path": MANIFEST_NAME,
            "size": manifest_path.stat().st_size,
            "sha256": sha256_bytes(manifest_path.read_bytes()),
        },
        "listed_files": len(manifest["files"]),
        "mismatches": mismatches,
    }


def materialize(root: Path, destination: Path) -> dict[str, Any]:
    verification = verify(root)
    if not verification["ready"]:
        raise SystemExit(
            "public export manifest verification failed: "
            + ", ".join(verification_issues(verification))
        )
    if destination.exists() and any(destination.iterdir()):
        raise SystemExit(f"materialize destination is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(root)
    for item in manifest["files"]:
        relative = safe_relative(str(item["path"]))
        source = root / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if item["kind"] == "symlink":
            target.symlink_to(os.readlink(source))
        else:
            shutil.copy2(source, target)
    shutil.copy2(root / MANIFEST_NAME, destination / MANIFEST_NAME)
    return verification


def verify_git_commit(repository: Path, commit: str) -> dict[str, str]:
    """Verify immutable committed export bytes, exact path set and Git modes."""
    if not HEX40_RE.fullmatch(commit):
        raise SystemExit("public target must be a full commit SHA")

    def git(*arguments: str) -> bytes:
        result = subprocess.run(["git", "-C", str(repository), *arguments], capture_output=True)
        if result.returncode:
            raise SystemExit("cannot inspect public Git object: " + result.stderr.decode(errors="replace").strip())
        return result.stdout

    resolved = git("rev-parse", "--verify", commit + "^{commit}").decode().strip()
    if resolved != commit:
        raise SystemExit("public target is not a commit object")
    tree = git("rev-parse", commit + "^{tree}").decode().strip()
    entries: dict[str, tuple[str, str]] = {}
    for record in git("ls-tree", "-rz", "--full-tree", commit).split(b"\0"):
        if not record:
            continue
        header, raw_path = record.split(b"\t", 1)
        mode, kind, oid = header.decode().split()
        path = raw_path.decode("utf-8")
        safe_relative(path)
        if kind != "blob" or mode not in {"100644", "100755", "120000"}:
            raise SystemExit(f"unsupported public Git entry: {path}")
        entries[path] = (mode, oid)
    if MANIFEST_NAME not in entries or entries[MANIFEST_NAME][0] != "100644":
        raise SystemExit("public commit lacks a regular export manifest")
    manifest_bytes = git("cat-file", "blob", entries[MANIFEST_NAME][1])
    try:
        manifest = json.loads(manifest_bytes)
        files = manifest["files"]
        listed = [str(item["path"]) for item in files]
    except (KeyError, TypeError, ValueError) as error:
        raise SystemExit("invalid committed export manifest") from error
    if MANIFEST_NAME in listed or len(listed) != len(set(listed)) or set(entries) != set(listed) | {MANIFEST_NAME}:
        raise SystemExit("public Git tree differs from exact export path set")
    if REPORT_NAME not in listed:
        raise SystemExit("public Git manifest does not cover export report")
    with tempfile.TemporaryDirectory(prefix="hidloom-public-commit-") as temporary:
        stage = Path(temporary)
        (stage / MANIFEST_NAME).write_bytes(manifest_bytes)
        for item in files:
            relative = safe_relative(str(item["path"]))
            mode, oid = entries[str(item["path"])]
            expected = {("file", 0o644): "100644", ("file", 0o755): "100755", ("symlink", 0o777): "120000"}.get((item.get("kind"), item.get("mode")))
            if mode != expected:
                raise SystemExit(f"committed export mode/kind mismatch: {relative}")
            content = git("cat-file", "blob", oid)
            path = stage / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if mode == "120000":
                target = content.decode("utf-8")
                safe_relative(target)
                path.symlink_to(target)
            else:
                path.write_bytes(content)
                path.chmod(0o755 if mode == "100755" else 0o644)
        verified = verify(stage)
        if not verified["ready"]:
            raise SystemExit("committed public export failed verification: " + ", ".join(verification_issues(verified)))
    return {"commit": commit, "tree": tree, **export_source_identity(verified)}


def export_source_identity(verified: dict[str, Any]) -> dict[str, str]:
    """Identity shared by a verified archive export and committed public export."""
    provenance = verified["source_provenance"]
    return {
        "export_manifest_sha256": verified["manifest"]["sha256"],
        "source_commit": provenance["base_commit"],
        "source_tree": provenance["base_tree"],
        "source_snapshot_sha256": provenance["selected_snapshot_sha256"],
    }


def bind_release_source(mapping: dict[str, str], source: dict[str, Any]) -> None:
    for mapped, bundled in (("source_commit", "commit"), ("source_tree", "tree"),
                            ("source_snapshot_sha256", "snapshot_sha256"),
                            ("export_manifest_sha256", "export_manifest_sha256")):
        if not source.get(bundled) or mapping.get(mapped) != source[bundled]:
            raise SystemExit(f"public target does not match release source: {bundled}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("root", type=Path)
    verify_parser.add_argument("--json", action="store_true")
    verify_parser.add_argument(
        "--allow-draft-source",
        action="store_true",
        help="verify a non-publishable dirty-source draft without approving publication",
    )
    materialize_parser = subparsers.add_parser("materialize")
    materialize_parser.add_argument("root", type=Path)
    materialize_parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.command == "verify":
        payload = verify(
            args.root.resolve(), allow_draft_source=args.allow_draft_source
        )
    else:
        payload = materialize(args.root.resolve(), args.destination.resolve())
    if args.command == "materialize" or args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif not payload["ready"]:
        details = verification_issues(payload)
        print("public export manifest verification failed: " + ", ".join(details))
    else:
        print(
            f"ok: public export manifest {payload['listed_files']} files "
            f"{payload['manifest']['sha256']}"
        )
    if not payload["ready"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
