#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import tempfile

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from public_export import (  # noqa: E402
    sanitize_public_documentation,
    selected,
    validate_public_documentation_audit,
)


PRIVATE_OPERATIONAL_DOCUMENTS = frozenset(
    {
        "docs/daemon/specs/coverage-audit-2026-06-26.md",
        "docs/daemon/specs/matrixd/logicd-stability-status-2026-06-02.md",
        "docs/daemon/specs/matrixd/scan-stability-progress-2026-06-02.md",
        "docs/ops/boot-userspace-network-handoff.md",
        "docs/ops/real-device-next-start.md",
        "docs/ops/repository-layout-inventory.md",
        "docs/ops/windows-hidloom-hidd-p3-handoff.md",
        "docs/ops/workflow-runbook.md",
    }
)
TRANSIENT_DOCUMENT_RE = re.compile(
    r"(?:-handoff|-next-start|-(?:progress|status|audit)-20\d{2}-\d{2}-\d{2})\.md$",
    re.IGNORECASE,
)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def selected_private_documents(root: Path, manifest: dict[str, object]) -> list[str]:
    selected_documents = []
    for path in (root / "docs").rglob("*.md"):
        relative = path.relative_to(root).as_posix()
        if not selected(relative, manifest):
            continue
        if relative in PRIVATE_OPERATIONAL_DOCUMENTS or TRANSIENT_DOCUMENT_RE.search(relative):
            selected_documents.append(relative)
    return sorted(selected_documents)


def main() -> None:
    public_manifest = json.loads(
        (ROOT / "config/public-export.json").read_text(encoding="utf-8")
    )
    excluded = set(public_manifest["exclude_globs"])
    assert PRIVATE_OPERATIONAL_DOCUMENTS <= excluded
    assert selected_private_documents(ROOT, public_manifest) == []

    manifest = {
        "include_files": [],
        "include_prefixes": ["docs/"],
        "exclude_globs": ["docs/private/**"],
    }
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        source = workspace / "source"
        destination = workspace / "export"
        write(source / "docs/private/note.md", "private\n")
        write(source / "docs/guide.md", "guide\n")
        write(source / "docs/ops/release-next-start.md", "transient\n")
        write(source / "docs/ops/workflow-runbook.md", "internal\n")
        assert selected_private_documents(source, manifest) == [
            "docs/ops/release-next-start.md",
            "docs/ops/workflow-runbook.md",
        ]
        text = (
            "- [private navigation](private/note.md)\n"
            "[private](private/note.md) [guide](guide.md) [missing](missing.md)\n"
        )
        write(source / "README.md", "[docs](docs/)\n")
        write(source / "docs/README.md", text)
        write(destination / "README.md", "[docs](docs/)\n")
        write(destination / "docs/README.md", text)
        write(destination / "docs/guide.md", "guide\n")

        findings = sanitize_public_documentation(
            destination, manifest, source_root=source
        )
        audit = json.loads(
            (destination / "PUBLIC_DOCUMENTATION_AUDIT.json").read_text(encoding="utf-8")
        )
        assert audit["ready"] is False
        assert audit["schema"] == "hidloom.public-documentation-audit.v2"
        assert audit["summary"] == {
            "files_scanned": 3,
            "public_docs": 2,
            "reachable_public_docs": 2,
            "omitted_private_links": 2,
            "removed_private_navigation_lines": 1,
            "broken_links": 1,
            "orphaned_documents": 0,
        }
        assert validate_public_documentation_audit(audit) == []
        assert all("target" not in item for item in audit["omitted_private_links"])
        assert all("text" not in item for item in audit["removed_private_navigation_lines"])
        assert len(findings) == 1
        assert findings[0].pattern_id == "public_documentation_broken_link"
        exported = (destination / "docs/README.md").read_text(encoding="utf-8")
        assert "[private]" not in exported
        assert "private workspace reference" in exported
        assert "private/note.md" not in exported
        assert "private navigation" not in exported
        assert "[guide](guide.md)" in exported
        assert "[missing](missing.md)" in exported
        markdown = (destination / "PUBLIC_DOCUMENTATION_AUDIT.md").read_text(
            encoding="utf-8"
        )
        assert "Private-only navigation lines removed: 1" in markdown
        assert "## Removed private navigation" in markdown
        assert "docs/README.md:1" in markdown
        assert "private/note.md" not in markdown

        destination_ok = workspace / "export-ok"
        text_ok = (
            "- [private navigation](private/note.md)\n"
            "[private](private/note.md) [guide](guide.md)\n"
        )
        write(destination_ok / "README.md", "[docs](docs/)\n")
        write(destination_ok / "docs/README.md", text_ok)
        write(destination_ok / "docs/guide.md", "guide\n")
        findings = sanitize_public_documentation(
            destination_ok, manifest, source_root=source
        )
        audit = json.loads(
            (destination_ok / "PUBLIC_DOCUMENTATION_AUDIT.json").read_text(encoding="utf-8")
        )
        assert findings == []
        assert audit["ready"] is True
        assert audit["summary"]["omitted_private_links"] == 2
        assert audit["summary"]["removed_private_navigation_lines"] == 1
        assert audit["summary"]["broken_links"] == 0
        assert audit["summary"]["orphaned_documents"] == 0
        assert validate_public_documentation_audit(audit) == []

        destination_orphan = workspace / "export-orphan"
        write(destination_orphan / "README.md", "[docs](docs/)\n")
        write(destination_orphan / "docs/README.md", "[guide](guide.md)\n")
        write(destination_orphan / "docs/guide.md", "guide\n")
        write(
            destination_orphan / "docs/orphan.md",
            "```markdown\n[fake navigation](README.md)\n```\n",
        )
        findings = sanitize_public_documentation(
            destination_orphan, manifest, source_root=source
        )
        audit = json.loads(
            (destination_orphan / "PUBLIC_DOCUMENTATION_AUDIT.json").read_text(
                encoding="utf-8"
            )
        )
        assert audit["ready"] is False
        assert audit["summary"]["public_docs"] == 3
        assert audit["summary"]["reachable_public_docs"] == 2
        assert audit["summary"]["orphaned_documents"] == 1
        assert audit["orphaned_documents"] == [{"path": "docs/orphan.md"}]
        assert validate_public_documentation_audit(audit) == []
        assert len(findings) == 1
        assert findings[0].pattern_id == "public_documentation_orphan"
        assert findings[0].path == "docs/orphan.md"

    print("ok: public documentation removes private links and blocks broken or orphaned docs")


if __name__ == "__main__":
    main()
