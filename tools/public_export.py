#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import deque
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "config" / "public-export.json"
DEFAULT_PATTERNS = ROOT / "config" / "public-export-deny-patterns.json"
ACTION_REQUIRED_SUFFIX = "_required"
EXPORT_CONTRACT_SCHEMA = "hidloom.public-export.v2"
DOCUMENTATION_AUDIT_SCHEMA = "hidloom.public-documentation-audit.v2"
CANONICAL_GENERATED_OUTPUT_FILES = frozenset(
    {
        "PUBLIC_ASSET_PROVENANCE.json",
        "PUBLIC_ASSET_PROVENANCE.md",
        "PUBLIC_DOCUMENTATION_AUDIT.json",
        "PUBLIC_DOCUMENTATION_AUDIT.md",
        "PUBLIC_EXPORT_MANIFEST.json",
        "PUBLIC_EXPORT_REPORT.json",
        "PUBLIC_EXPORT_REPORT.md",
        "PUBLIC_PRIVACY_AUDIT.json",
        "PUBLIC_PRIVACY_AUDIT.md",
        "PUBLIC_REFERENCE_AUDIT.json",
        "PUBLIC_REFERENCE_AUDIT.md",
        "SBOM.cdx.json",
    }
)
MARKDOWN_LINK_RE = re.compile(
    r"(?<!!)\[([^\]\n]+)\]\(([^)#\s][^)\s#]*)(?:#[^)]+)?\)"
)
MARKDOWN_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")


@dataclass(frozen=True)
class Finding:
    severity: str
    pattern_id: str
    path: str
    line: int
    excerpt: str
    disposition: str = "untriaged"
    reason: str = ""


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def tracked_files(*, root: Path = ROOT) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
    )
    return [item.decode() for item in result.stdout.split(b"\0") if item]


def worktree_files(*, root: Path = ROOT) -> list[str]:
    """Return current non-ignored source paths, excluding deleted index entries."""

    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    candidates = {
        *tracked_files(root=root),
        *(item.decode() for item in untracked.split(b"\0") if item),
    }
    return sorted(
        relative
        for relative in candidates
        if (root / relative).is_file() or (root / relative).is_symlink()
    )


def source_provenance(paths: list[str], *, root: Path = ROOT) -> dict[str, Any]:
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    tree = subprocess.check_output(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=root, text=True
    ).strip()
    revision_count = int(
        subprocess.check_output(["git", "rev-list", "--count", "HEAD"], cwd=root, text=True)
    )
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=normal"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    digest = hashlib.sha256()
    for relative in paths:
        path = root / relative
        if path.is_symlink():
            content = os.readlink(path).encode()
            kind = "symlink"
            mode = 0o777
        elif path.is_file():
            content = path.read_bytes()
            kind = "file"
            mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
        else:
            raise SystemExit(f"selected source path is missing: {relative}")
        header = f"{relative}\0{kind}\0{mode:o}\0{len(content)}\0".encode()
        digest.update(header)
        digest.update(content)
        digest.update(b"\0")
    clean = not status
    return {
        "schema": "hidloom.source-provenance.v1",
        "mode": "clean-head" if clean else "dirty-worktree",
        "publishable": clean,
        "base_commit": commit,
        "base_tree": tree,
        "base_revision_count": revision_count,
        "selected_path_count": len(paths),
        "selected_snapshot_sha256": digest.hexdigest(),
    }


def selected(path: str, manifest: dict[str, Any]) -> bool:
    include_files = manifest.get("include_files", ())
    include_prefixes = manifest.get("include_prefixes", ())
    included = path in include_files or any(
        path.startswith(prefix) for prefix in include_prefixes
    )
    if not included:
        return False
    excluded = any(fnmatch.fnmatch(path, pattern) for pattern in manifest["exclude_globs"])
    generated = path in manifest.get("generated_output_files", ())
    return not excluded and not generated


def explicitly_excluded(path: str, manifest: dict[str, Any]) -> bool:
    patterns = manifest.get("exclude_globs", ())
    if not isinstance(patterns, list):
        return False
    return any(
        isinstance(pattern, str) and fnmatch.fnmatch(path, pattern)
        for pattern in patterns
    )


def source_selection_summary(tracked: list[str], manifest: dict[str, Any]) -> dict[str, int]:
    generated = set(manifest["generated_output_files"])
    public_source = sum(selected(path, manifest) for path in tracked)
    private_only = sum(explicitly_excluded(path, manifest) for path in tracked)
    generated_output = sum(path in generated for path in tracked)
    return {
        "tracked_paths": len(tracked),
        "public_source_paths": public_source,
        "private_only_paths": private_only,
        "generated_output_paths": generated_output,
        "unclassified_paths": len(tracked) - public_source - private_only - generated_output,
    }


def _safe_manifest_path(value: str, *, prefix: bool = False) -> bool:
    if not value or "\0" in value or ":" in value or "\\" in value or value.startswith("/"):
        return False
    parts = value.rstrip("/").split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return False
    return not prefix or value.endswith("/")


def _safe_manifest_glob(value: str) -> bool:
    if not value or "\0" in value or ":" in value or "\\" in value or value.startswith("/"):
        return False
    return not any(part in {"", ".", ".."} for part in value.split("/"))


def validate_export_contract(manifest: Any, tracked: list[str]) -> list[str]:
    if not isinstance(manifest, dict):
        return ["manifest-not-object"]
    issues: list[str] = []
    if manifest.get("schema") != EXPORT_CONTRACT_SCHEMA:
        issues.append("unsupported-schema")

    fields = (
        "include_prefixes",
        "include_files",
        "generated_output_files",
        "exclude_globs",
    )
    values_by_field: dict[str, list[str]] = {}
    for field in fields:
        values = manifest.get(field)
        if not isinstance(values, list) or not all(
            isinstance(value, str) and value for value in values
        ):
            issues.append(f"invalid-field:{field}")
            values_by_field[field] = []
            continue
        values_by_field[field] = values
        if len(values) != len(set(values)):
            issues.append(f"duplicate-entry:{field}")

    for value in values_by_field["include_prefixes"]:
        if not _safe_manifest_path(value, prefix=True):
            issues.append(f"unsafe-include-prefix:{value}")
    for field in ("include_files", "generated_output_files"):
        for value in values_by_field[field]:
            if not _safe_manifest_path(value):
                issues.append(f"unsafe-{field.replace('_', '-')}:{value}")
    for value in values_by_field["exclude_globs"]:
        if not _safe_manifest_glob(value):
            issues.append(f"unsafe-exclude-glob:{value}")

    warning_triage = manifest.get("warning_triage")
    if not isinstance(warning_triage, list):
        issues.append("invalid-field:warning_triage")
    else:
        triage_pairs: set[tuple[str, str]] = set()
        for index, rule in enumerate(warning_triage):
            if not isinstance(rule, dict):
                issues.append(f"invalid-warning-triage-rule:{index}")
                continue
            pattern_id = rule.get("pattern_id")
            disposition = rule.get("disposition")
            reason = rule.get("reason")
            if not isinstance(pattern_id, str) or not pattern_id:
                issues.append(f"invalid-warning-triage-pattern:{index}")
            if not isinstance(disposition, str) or not disposition:
                issues.append(f"invalid-warning-triage-disposition:{index}")
            if not isinstance(reason, str) or not reason.strip():
                issues.append(f"invalid-warning-triage-reason:{index}")
            has_single_glob = "path_glob" in rule
            has_multiple_globs = "path_globs" in rule
            raw_globs: Any
            if has_single_glob == has_multiple_globs:
                raw_globs = None
            elif has_single_glob:
                raw_globs = [rule.get("path_glob")]
            else:
                raw_globs = rule.get("path_globs")
            if not isinstance(raw_globs, list) or not raw_globs or not all(
                isinstance(value, str) and value for value in raw_globs
            ):
                issues.append(f"invalid-warning-triage-globs:{index}")
                continue
            if len(raw_globs) != len(set(raw_globs)):
                issues.append(f"duplicate-warning-triage-glob:{index}")
            for path_glob in raw_globs:
                if not _safe_manifest_glob(path_glob):
                    issues.append(f"unsafe-warning-triage-glob:{index}:{path_glob}")
                if isinstance(pattern_id, str) and pattern_id:
                    pair = (pattern_id, path_glob)
                    if pair in triage_pairs:
                        issues.append(f"duplicate-warning-triage:{pattern_id}:{path_glob}")
                    triage_pairs.add(pair)
            if (
                "*" in raw_globs
                and isinstance(pattern_id, str)
                and pattern_id
                and isinstance(disposition, str)
                and not disposition.endswith(ACTION_REQUIRED_SUFFIX)
            ):
                issues.append(f"permissive-warning-triage-catch-all:{pattern_id}")

    generated = set(values_by_field["generated_output_files"])
    if generated != CANONICAL_GENERATED_OUTPUT_FILES:
        issues.append("generated-output-set-mismatch")
    tracked_set = set(tracked)
    for value in values_by_field["include_files"]:
        if value not in tracked_set:
            issues.append(f"include-file-not-tracked:{value}")
        elif explicitly_excluded(value, manifest):
            issues.append(f"include-file-excluded:{value}")
    for value in generated:
        included = value in values_by_field["include_files"] or any(
            value.startswith(prefix) for prefix in values_by_field["include_prefixes"]
        )
        if included:
            issues.append(f"generated-output-included:{value}")
        if explicitly_excluded(value, manifest):
            issues.append(f"generated-output-excluded:{value}")

    if not any(issue.startswith("invalid-field:") for issue in issues):
        for path in tracked:
            classifications = (
                selected(path, manifest),
                explicitly_excluded(path, manifest),
                path in generated,
            )
            if not any(classifications):
                issues.append(f"unclassified-tracked-path:{path}")
            elif sum(classifications) != 1:
                issues.append(f"ambiguous-tracked-path:{path}")
    return sorted(set(issues))


def validate_export_tree(
    destination: Path,
    selected_paths: list[str],
    manifest: dict[str, Any],
    *,
    include_manifest: bool,
) -> list[str]:
    generated = set(manifest["generated_output_files"])
    if not include_manifest:
        generated.discard("PUBLIC_EXPORT_MANIFEST.json")
    expected = set(selected_paths) | generated
    actual = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    expected_directories = {
        parent.as_posix()
        for relative in expected
        for parent in Path(relative).parents
        if parent != Path(".")
    }
    actual_directories = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_dir() and not path.is_symlink()
    }
    return [
        *(f"missing-output:{path}" for path in sorted(expected - actual)),
        *(f"unexpected-output:{path}" for path in sorted(actual - expected)),
        *(
            f"unexpected-output-directory:{path}"
            for path in sorted(actual_directories - expected_directories)
        ),
    ]


def copy_tree(paths: list[str], destination: Path, replacements: list[dict[str, str]]) -> None:
    for relative in paths:
        source = ROOT / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink():
            target.symlink_to(os.readlink(source))
        else:
            shutil.copy2(source, target)
            target.chmod(0o755 if source.stat().st_mode & 0o111 else 0o644)
            try:
                text = target.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            updated = text
            updated = updated.replace(str(ROOT), "/home/USERNAME/src/hidloom")
            for replacement in replacements:
                updated = updated.replace(replacement["from"], replacement["to"])
            if updated != text:
                target.write_text(updated, encoding="utf-8")


def _source_target_is_selected(
    source_target: Path,
    relative: str,
    manifest: dict[str, Any],
    source_root: Path,
) -> bool:
    if source_target.is_dir():
        return any(
            selected(path.relative_to(source_root).as_posix(), manifest)
            for path in source_target.rglob("*")
            if path.is_file() or path.is_symlink()
        )
    return selected(relative, manifest)


def _markdown_navigation_targets(text: str) -> list[str]:
    targets: list[str] = []
    active_fence = ""
    for line in text.splitlines():
        fence = MARKDOWN_FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            if not active_fence:
                active_fence = marker
            elif marker[0] == active_fence[0] and len(marker) >= len(active_fence):
                active_fence = ""
            continue
        if active_fence:
            continue
        targets.extend(match.group(2) for match in MARKDOWN_LINK_RE.finditer(line))
    return targets


def _resolve_markdown_document(
    document: Path,
    target: str,
    destination: Path,
    documents: set[Path],
) -> Path | None:
    target_path = (document.parent / target).resolve()
    try:
        target_path.relative_to(destination)
    except ValueError:
        return None
    if target_path.is_dir():
        target_path = target_path / "README.md"
    if target_path.suffix.lower() != ".md" or target_path not in documents:
        return None
    return target_path


def orphaned_public_documents(
    destination: Path,
    documents: list[Path] | None = None,
) -> list[str]:
    destination = destination.resolve()
    markdown_documents = sorted(
        documents if documents is not None else destination.rglob("*.md")
    )
    document_set = {path.resolve() for path in markdown_documents}
    root = destination / "README.md"
    reachable: set[Path] = set()
    pending: deque[Path] = deque()
    if root in document_set:
        reachable.add(root)
        pending.append(root)
    while pending:
        document = pending.popleft()
        text = document.read_text(encoding="utf-8")
        for target in _markdown_navigation_targets(text):
            resolved = _resolve_markdown_document(
                document, target, destination, document_set
            )
            if resolved is not None and resolved not in reachable:
                reachable.add(resolved)
                pending.append(resolved)
    return sorted(
        path.relative_to(destination).as_posix()
        for path in document_set - reachable
        if path.relative_to(destination).parts[0] == "docs"
    )


def validate_public_documentation_audit(
    payload: dict[str, Any],
    *,
    root: Path | None = None,
) -> list[str]:
    issues: list[str] = []
    if payload.get("schema") != DOCUMENTATION_AUDIT_SCHEMA:
        issues.append("unsupported-schema")
    summary = payload.get("summary")
    expected_summary_fields = {
        "files_scanned",
        "public_docs",
        "reachable_public_docs",
        "omitted_private_links",
        "removed_private_navigation_lines",
        "broken_links",
        "orphaned_documents",
    }
    if not isinstance(summary, dict):
        return [*issues, "summary-not-object"]
    if set(summary) != expected_summary_fields:
        issues.append("summary-fields-mismatch")
    counts: dict[str, int] = {}
    for field in expected_summary_fields:
        value = summary.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            issues.append(f"invalid-summary-count:{field}")
        else:
            counts[field] = value
    list_fields = {
        "omitted_private_links": "omitted_private_links",
        "removed_private_navigation_lines": "removed_private_navigation_lines",
        "broken_links": "broken_links",
        "orphaned_documents": "orphaned_documents",
    }
    for summary_field, payload_field in list_fields.items():
        items = payload.get(payload_field)
        if not isinstance(items, list):
            issues.append(f"{payload_field}-not-list")
        elif counts.get(summary_field) != len(items):
            issues.append(f"{payload_field}-count-mismatch")
    public_docs = counts.get("public_docs")
    reachable_docs = counts.get("reachable_public_docs")
    orphaned_count = counts.get("orphaned_documents")
    files_scanned = counts.get("files_scanned")
    if (
        public_docs is not None
        and files_scanned is not None
        and public_docs > files_scanned
    ):
        issues.append("public-doc-count-exceeds-scanned")
    if (
        public_docs is not None
        and reachable_docs is not None
        and orphaned_count is not None
        and reachable_docs != public_docs - orphaned_count
    ):
        issues.append("reachable-document-count-mismatch")
    orphaned_items = payload.get("orphaned_documents")
    orphaned_paths: list[str] = []
    if isinstance(orphaned_items, list):
        for index, item in enumerate(orphaned_items):
            if not isinstance(item, dict) or set(item) != {"path"}:
                issues.append(f"invalid-orphan-entry:{index}")
                continue
            path = item.get("path")
            if (
                not isinstance(path, str)
                or not path.startswith("docs/")
                or not path.endswith(".md")
                or Path(path).is_absolute()
                or ".." in Path(path).parts
            ):
                issues.append(f"invalid-orphan-path:{index}")
                continue
            orphaned_paths.append(path)
        if orphaned_paths != sorted(set(orphaned_paths)):
            issues.append("orphan-paths-not-sorted-unique")
    ready = payload.get("ready")
    if not isinstance(ready, bool):
        issues.append("ready-not-boolean")
    elif counts.get("broken_links") is not None and orphaned_count is not None:
        if ready != (counts["broken_links"] == 0 and orphaned_count == 0):
            issues.append("ready-mismatch")
    if root is not None:
        resolved_root = root.resolve()
        manifest_path = resolved_root / "PUBLIC_EXPORT_MANIFEST.json"
        try:
            manifest = load_json(manifest_path)
        except (OSError, json.JSONDecodeError):
            issues.append("manifest-unreadable-for-documentation-recompute")
            return issues
        manifest_paths = []
        for item in manifest.get("files", []):
            relative = item.get("path") if isinstance(item, dict) else None
            if not isinstance(relative, str) or not relative.endswith(".md"):
                continue
            document = (resolved_root / relative).resolve()
            try:
                document.relative_to(resolved_root)
            except ValueError:
                issues.append("manifest-document-outside-root")
                continue
            if document.is_file():
                manifest_paths.append(document)
        actual_documents = sorted(set(manifest_paths))
        actual_public_docs = sum(
            path.relative_to(resolved_root).parts[0] == "docs"
            for path in actual_documents
        )
        source_markdown_count = sum(
            path.relative_to(resolved_root).as_posix()
            not in CANONICAL_GENERATED_OUTPUT_FILES
            for path in actual_documents
        )
        actual_orphans = orphaned_public_documents(resolved_root, actual_documents)
        if files_scanned is not None and files_scanned != source_markdown_count:
            issues.append("scanned-document-inventory-mismatch")
        if public_docs is not None and public_docs != actual_public_docs:
            issues.append("public-doc-inventory-mismatch")
        if orphaned_paths != actual_orphans:
            issues.append("orphan-inventory-mismatch")
    return issues


def sanitize_public_documentation(
    destination: Path,
    manifest: dict[str, Any],
    *,
    source_root: Path = ROOT,
) -> list[Finding]:
    omitted: list[dict[str, Any]] = []
    broken: list[dict[str, Any]] = []
    removed_navigation: list[dict[str, Any]] = []
    documents = sorted(destination.rglob("*.md"))
    for document in documents:
        relative_document = document.relative_to(destination).as_posix()
        text = document.read_text(encoding="utf-8")

        def replace(match: re.Match[str]) -> str:
            _, target = match.group(1), match.group(2)
            if "://" in target or target.startswith(("mailto:", "data:")):
                return match.group(0)
            target_path = (document.parent / target).resolve()
            line = text.count("\n", 0, match.start()) + 1
            try:
                relative_target = target_path.relative_to(destination).as_posix()
            except ValueError:
                broken.append(
                    {
                        "path": relative_document,
                        "line": line,
                        "target": target,
                        "reason": "outside-export",
                    }
                )
                return match.group(0)
            if target_path.exists():
                return match.group(0)

            source_target = source_root / relative_target
            if source_target.exists() and not _source_target_is_selected(
                source_target, relative_target, manifest, source_root
            ):
                omitted.append(
                    {
                        "path": relative_document,
                        "line": line,
                        "target_type": "directory" if source_target.is_dir() else "file",
                    }
                )
                return "private workspace reference *(omitted from public export)*"

            reason = (
                "selected-target-missing"
                if source_target.exists()
                else "source-target-missing"
            )
            broken.append(
                {"path": relative_document, "line": line, "target": target, "reason": reason}
            )
            return match.group(0)

        updated = MARKDOWN_LINK_RE.sub(replace, text)
        omitted_lines = {
            item["line"] for item in omitted if item["path"] == relative_document
        }
        output_lines = []
        original_lines = text.splitlines(keepends=True)
        updated_lines = updated.splitlines(keepends=True)
        for line_number, (original_line, updated_line) in enumerate(
            zip(original_lines, updated_lines, strict=True), 1
        ):
            stripped = original_line.lstrip()
            navigation = stripped.startswith(("- ", "* ", "+ ", "|")) or re.match(
                r"\d+\.\s", stripped
            )
            if (
                line_number in omitted_lines
                and navigation
                and not MARKDOWN_LINK_RE.search(updated_line)
            ):
                removed_navigation.append(
                    {
                        "path": relative_document,
                        "line": line_number,
                    }
                )
                continue
            output_lines.append(updated_line)
        updated = "".join(output_lines)
        if updated != text:
            document.write_text(updated, encoding="utf-8")

    orphaned = [
        {"path": path}
        for path in orphaned_public_documents(destination, documents)
    ]
    public_docs = sum(
        document.relative_to(destination).parts[0] == "docs" for document in documents
    )
    payload = {
        "schema": DOCUMENTATION_AUDIT_SCHEMA,
        "ready": not broken and not orphaned,
        "summary": {
            "files_scanned": len(documents),
            "public_docs": public_docs,
            "reachable_public_docs": public_docs - len(orphaned),
            "omitted_private_links": len(omitted),
            "removed_private_navigation_lines": len(removed_navigation),
            "broken_links": len(broken),
            "orphaned_documents": len(orphaned),
        },
        "omitted_private_links": omitted,
        "removed_private_navigation_lines": removed_navigation,
        "broken_links": broken,
        "orphaned_documents": orphaned,
    }
    (destination / "PUBLIC_DOCUMENTATION_AUDIT.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# HIDloom Public Documentation Audit",
        "",
        f"- Ready: `{str(payload['ready']).lower()}`",
        f"- Markdown files scanned: {len(documents)}",
        f"- Public docs: {public_docs}",
        f"- Reachable public docs: {public_docs - len(orphaned)}",
        f"- Private links converted to text: {len(omitted)}",
        f"- Private-only navigation lines removed: {len(removed_navigation)}",
        f"- Broken links: {len(broken)}",
        f"- Orphaned documents: {len(orphaned)}",
        "",
        "## Broken links",
        "",
    ]
    if broken:
        lines.extend(
            f"- `{item['path']}:{item['line']}` -> `{item['target']}` ({item['reason']})"
            for item in broken
        )
    else:
        lines.append("- None")
    lines.extend(["", "## Orphaned documents", ""])
    if orphaned:
        lines.extend(f"- `{item['path']}`" for item in orphaned)
    else:
        lines.append("- None")
    lines.extend(["", "## Removed private navigation", ""])
    if removed_navigation:
        lines.extend(
            f"- `{item['path']}:{item['line']}` (private-only navigation removed)"
            for item in removed_navigation
        )
    else:
        lines.append("- None")
    lines.extend(["", "## Omitted private links", ""])
    if omitted:
        lines.extend(
            f"- `{item['path']}:{item['line']}` ({item['target_type']} target omitted)"
            for item in omitted
        )
    else:
        lines.append("- None")
    (destination / "PUBLIC_DOCUMENTATION_AUDIT.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    findings = [
        Finding(
            "block",
            "public_documentation_broken_link",
            item["path"],
            item["line"],
            f"{item['target']} ({item['reason']})",
        )
        for item in broken
    ]
    findings.extend(
        Finding(
            "block",
            "public_documentation_orphan",
            item["path"],
            1,
            "not reachable from README.md",
        )
        for item in orphaned
    )
    return findings


def scan_text_files(destination: Path, patterns: dict[str, Any]) -> list[Finding]:
    compiled = {
        severity: [
            (
                item["id"],
                re.compile(item["pattern"]),
                tuple(item.get("exclude_path_globs", ())),
            )
            for item in patterns[severity]
        ]
        for severity in ("block", "warn")
    }
    findings: list[Finding] = []
    for path in sorted(item for item in destination.rglob("*") if item.is_file()):
        relative = path.relative_to(destination).as_posix()
        for pattern_id, pattern, excluded_globs in compiled["block"]:
            if any(fnmatch.fnmatch(relative, glob) for glob in excluded_globs):
                continue
            if pattern.search(relative):
                findings.append(Finding("block", pattern_id, relative, 0, relative))
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            for severity, entries in compiled.items():
                for pattern_id, pattern, excluded_globs in entries:
                    if any(fnmatch.fnmatch(relative, glob) for glob in excluded_globs):
                        continue
                    if pattern.search(line):
                        findings.append(
                            Finding(severity, pattern_id, relative, line_number, line.strip()[:200])
                        )
    return findings


def license_policy_findings(destination: Path, manifest: dict[str, Any]) -> list[Finding]:
    license_path = destination / "LICENSE"
    text = license_path.read_text(encoding="utf-8", errors="replace") if license_path.exists() else ""
    expected = manifest["expected_license"]
    if "GNU GENERAL PUBLIC LICENSE" in text and "Version 3" in text:
        return []
    return [Finding("block", "license_policy_pending", "LICENSE", 1, f"expected {expected}")]


def apply_warning_triage(findings: list[Finding], manifest: dict[str, Any]) -> list[Finding]:
    rules = manifest.get("warning_triage", [])
    result: list[Finding] = []
    for finding in findings:
        updated = finding
        if finding.severity == "warn":
            for rule in rules:
                path_globs = rule.get("path_globs", [rule.get("path_glob", "")])
                if finding.pattern_id == rule["pattern_id"] and any(
                    fnmatch.fnmatch(finding.path, path_glob) for path_glob in path_globs
                ):
                    updated = Finding(
                        finding.severity,
                        finding.pattern_id,
                        finding.path,
                        finding.line,
                        finding.excerpt,
                        rule["disposition"],
                        rule["reason"],
                    )
                    break
        result.append(updated)
    return result


def write_report(
    destination: Path,
    manifest: dict[str, Any],
    paths: list[str],
    findings: list[Finding],
    provenance: dict[str, Any],
    selection_summary: dict[str, int],
) -> None:
    summary: dict[str, dict[str, int]] = {}
    for finding in findings:
        key = f"{finding.severity}:{finding.pattern_id}"
        bucket = summary.setdefault(key, {})
        bucket[finding.disposition] = bucket.get(finding.disposition, 0) + 1
    payload = {
        "schema": "hidloom.public-export-report.v2",
        "source_provenance": provenance,
        "public_repository": manifest["public_repository"],
        "initial_version": manifest["initial_version"],
        "expected_license": manifest["expected_license"],
        "file_count": len(paths),
        "source_selection": selection_summary,
        "finding_summary": summary,
        "findings": [finding.__dict__ for finding in findings],
    }
    (destination / "PUBLIC_EXPORT_REPORT.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# HIDloom Public Export Report",
        "",
        f"- Source base commit: `{provenance['base_commit']}`",
        f"- Source mode: `{provenance['mode']}`",
        f"- Publishable source: `{str(provenance['publishable']).lower()}`",
        f"- Selected source snapshot: `{provenance['selected_snapshot_sha256']}`",
        f"- Files: {len(paths)}",
        f"- Tracked source paths: {selection_summary['tracked_paths']}",
        f"- Private-only paths: {selection_summary['private_only_paths']}",
        f"- Tracked generated outputs: {selection_summary['generated_output_paths']}",
        f"- Unclassified paths: {selection_summary['unclassified_paths']}",
        f"- Blocking findings: {sum(item.severity == 'block' for item in findings)}",
        f"- Warnings: {sum(item.severity == 'warn' for item in findings)}",
        f"- Untriaged warnings: {sum(item.severity == 'warn' and item.disposition == 'untriaged' for item in findings)}",
        f"- Action-required warnings: {sum(item.severity == 'warn' and item.disposition.endswith(ACTION_REQUIRED_SUFFIX) for item in findings)}",
        "",
        "## Findings",
        "",
    ]
    if findings:
        for finding in findings:
            lines.append(
                f"- `{finding.severity}` `{finding.pattern_id}` "
                f"`{finding.path}:{finding.line}` `{finding.disposition}` — `{finding.excerpt}`"
            )
    else:
        lines.append("- None")
    (destination / "PUBLIC_EXPORT_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_file_manifest(destination: Path, provenance: dict[str, Any]) -> None:
    entries = []
    for path in sorted(item for item in destination.rglob("*") if item.is_file() or item.is_symlink()):
        relative = path.relative_to(destination).as_posix()
        if relative == "PUBLIC_EXPORT_MANIFEST.json":
            continue
        if path.is_symlink():
            content = os.readlink(path).encode()
            kind = "symlink"
            mode = 0o777
        else:
            path.chmod(0o755 if path.stat().st_mode & 0o111 else 0o644)
            content = path.read_bytes()
            kind = "file"
            mode = path.stat().st_mode & 0o777
        entries.append(
            {
                "path": relative,
                "kind": kind,
                "mode": mode,
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    payload = {
        "schema": "hidloom.public-export-manifest.v2",
        "source_provenance": provenance,
        "files": entries,
    }
    manifest_path = destination / "PUBLIC_EXPORT_MANIFEST.json"
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest_path.chmod(0o644)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and audit the HIDloom clean public export")
    parser.add_argument("destination", type=Path)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--patterns", type=Path, default=DEFAULT_PATTERNS)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--draft", action="store_true", help="allow policy blockers while preparing export")
    parser.add_argument(
        "--allow-dirty-source",
        action="store_true",
        help="allow a non-publishable dirty-worktree export for local draft validation",
    )
    args = parser.parse_args()

    destination = args.destination.resolve()
    if destination == ROOT or ROOT in destination.parents:
        raise SystemExit("destination must be outside the private repository")
    if args.allow_dirty_source and not args.draft:
        parser.error("--allow-dirty-source requires --draft")

    manifest = load_json(args.manifest)
    patterns = load_json(args.patterns)
    source_paths = worktree_files() if args.allow_dirty_source else tracked_files()
    contract_issues = validate_export_contract(manifest, source_paths)
    if contract_issues:
        raise SystemExit(
            "public export contract validation failed:\n- " + "\n- ".join(contract_issues)
        )
    paths = [path for path in source_paths if selected(path, manifest)]
    selection_summary = source_selection_summary(source_paths, manifest)
    provenance = source_provenance(paths)
    if not provenance["publishable"] and not args.allow_dirty_source:
        raise SystemExit(
            "source worktree is dirty; commit or clean all tracked and untracked changes, "
            "or use --draft --allow-dirty-source for non-publishable local validation"
        )

    if destination.exists():
        if not args.force:
            raise SystemExit(f"destination exists: {destination}")
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    copy_tree(paths, destination, manifest.get("text_replacements", []))
    documentation_findings = sanitize_public_documentation(destination, manifest)
    findings = scan_text_files(destination, patterns)
    findings.extend(documentation_findings)
    findings.extend(license_policy_findings(destination, manifest))
    findings = apply_warning_triage(findings, manifest)
    findings.sort(key=lambda item: (item.severity, item.path, item.line, item.pattern_id))
    write_report(
        destination,
        manifest,
        paths,
        findings,
        provenance,
        selection_summary,
    )
    subprocess.run(
        ["python3", str(destination / "tools/generate_cyclonedx_sbom.py"), str(destination)],
        cwd=destination,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["python3", str(destination / "tools/public_privacy_audit.py"), str(destination)],
        cwd=destination,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["python3", str(destination / "tools/public_asset_inventory.py"), str(destination)],
        cwd=destination,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["python3", str(destination / "tools/public_reference_audit.py"), str(destination)],
        cwd=destination,
        check=True,
        capture_output=True,
        text=True,
    )
    tree_issues = validate_export_tree(
        destination,
        paths,
        manifest,
        include_manifest=False,
    )
    if tree_issues:
        raise SystemExit("public export output validation failed:\n- " + "\n- ".join(tree_issues))
    write_file_manifest(destination, provenance)
    tree_issues = validate_export_tree(
        destination,
        paths,
        manifest,
        include_manifest=True,
    )
    if tree_issues:
        raise SystemExit("public export output validation failed:\n- " + "\n- ".join(tree_issues))

    blockers = [item for item in findings if item.severity == "block"]
    action_required = [
        item
        for item in findings
        if item.severity == "warn" and item.disposition.endswith(ACTION_REQUIRED_SUFFIX)
    ]
    print(f"exported {len(paths)} files to {destination}")
    print(
        f"blocking={len(blockers)} warnings={len(findings) - len(blockers)} "
        f"action_required={len(action_required)}"
    )
    if (blockers or action_required) and not args.draft:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
