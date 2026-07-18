#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from public_export import (  # noqa: E402
    CANONICAL_GENERATED_OUTPUT_FILES,
    apply_warning_triage,
    explicitly_excluded,
    scan_text_files,
    selected,
    source_selection_summary,
    source_provenance,
    tracked_files,
    validate_export_contract,
    validate_export_tree,
    worktree_files,
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


def main() -> None:
    manifest = json.loads((ROOT / "config" / "public-export.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "hidloom.public-export.v2"
    assert manifest["expected_license"] == "GPL-3.0-or-later"
    assert manifest["initial_version"] == "0.1.0"
    assert ".env.example" in manifest["include_files"]
    assert "AUTHORS.md" in manifest["include_files"]
    assert "codex_tasks/**" in manifest["exclude_globs"]
    assert "docs/ops/real-device-test-checklist.md" in manifest["exclude_globs"]
    assert "docs/CURRENT_STATUS.md" in manifest["exclude_globs"]
    assert "docs/review/**" in manifest["exclude_globs"]
    assert "docs/ops/hidloom-public-*.md" in manifest["exclude_globs"]
    assert "AGENTS.md" in manifest["exclude_globs"]
    assert ".github/copilot-instructions.md" in manifest["exclude_globs"]
    assert ".github/workflows/public-export-check.yml" in manifest["exclude_globs"]
    assert ".github/workflows/public-sync.yml" in manifest["exclude_globs"]
    assert ".github/workflows/repository-hygiene.yml" in manifest["exclude_globs"]
    assert "kicad/OLD/**" not in manifest["exclude_globs"]
    assert set(manifest["generated_output_files"]) == CANONICAL_GENERATED_OUTPUT_FILES
    root_tracked_paths = tracked_files()
    tracked_generated_outputs = sum(
        path in CANONICAL_GENERATED_OUTPUT_FILES for path in root_tracked_paths
    )
    tracked_private_only = sum(
        explicitly_excluded(path, manifest) for path in root_tracked_paths
    )
    assert validate_export_contract(manifest, root_tracked_paths) == []
    assert source_selection_summary(root_tracked_paths, manifest) == {
        "tracked_paths": len(root_tracked_paths),
        "public_source_paths": sum(
            selected(path, manifest) for path in root_tracked_paths
        ),
        "private_only_paths": tracked_private_only,
        "generated_output_paths": tracked_generated_outputs,
        "unclassified_paths": 0,
    }
    assert validate_export_contract(
        manifest,
        [*root_tracked_paths, *sorted(CANONICAL_GENERATED_OUTPUT_FILES)],
    ) == []
    assert all(
        selected(path, manifest)
        or explicitly_excluded(path, manifest)
        or path in CANONICAL_GENERATED_OUTPUT_FILES
        for path in root_tracked_paths
    )
    unclassified = copy.deepcopy(manifest)
    assert "unclassified-tracked-path:UNCLASSIFIED.txt" in validate_export_contract(
        unclassified,
        [*root_tracked_paths, "UNCLASSIFIED.txt"],
    )
    unclassified["exclude_globs"].append("UNCLASSIFIED.txt")
    assert validate_export_contract(
        unclassified,
        [*root_tracked_paths, "UNCLASSIFIED.txt"],
    ) == []
    missing_include = copy.deepcopy(manifest)
    missing_include["include_files"].append("MISSING_PUBLIC_SOURCE.txt")
    assert "include-file-not-tracked:MISSING_PUBLIC_SOURCE.txt" in validate_export_contract(
        missing_include,
        root_tracked_paths,
    )
    generated_drift = copy.deepcopy(manifest)
    generated_drift["generated_output_files"].append("UNREVIEWED_REPORT.json")
    assert "generated-output-set-mismatch" in validate_export_contract(
        generated_drift,
        root_tracked_paths,
    )
    generated_included = copy.deepcopy(manifest)
    generated_included["include_files"].append("PUBLIC_EXPORT_REPORT.json")
    assert "generated-output-included:PUBLIC_EXPORT_REPORT.json" in validate_export_contract(
        generated_included,
        [*root_tracked_paths, "PUBLIC_EXPORT_REPORT.json"],
    )
    invalid_field = copy.deepcopy(manifest)
    invalid_field["exclude_globs"] = "docs/private/**"
    assert "invalid-field:exclude_globs" in validate_export_contract(
        invalid_field,
        root_tracked_paths,
    )
    invalid_triage = copy.deepcopy(manifest)
    invalid_triage["warning_triage"] = "credential_word"
    assert "invalid-field:warning_triage" in validate_export_contract(
        invalid_triage,
        root_tracked_paths,
    )
    malformed_triage = copy.deepcopy(manifest)
    malformed_triage["warning_triage"].append(
        {"pattern_id": "", "path_glob": "../outside", "path_globs": ["docs/**"], "disposition": "", "reason": ""}
    )
    malformed_issues = validate_export_contract(malformed_triage, root_tracked_paths)
    malformed_index = len(malformed_triage["warning_triage"]) - 1
    assert f"invalid-warning-triage-pattern:{malformed_index}" in malformed_issues
    assert f"invalid-warning-triage-disposition:{malformed_index}" in malformed_issues
    assert f"invalid-warning-triage-reason:{malformed_index}" in malformed_issues
    assert f"invalid-warning-triage-globs:{malformed_index}" in malformed_issues
    duplicate_triage = copy.deepcopy(manifest)
    duplicate_triage["warning_triage"].append(copy.deepcopy(duplicate_triage["warning_triage"][0]))
    duplicate_rule = duplicate_triage["warning_triage"][0]
    duplicate_glob = duplicate_rule.get("path_glob")
    if duplicate_glob is None:
        duplicate_glob = duplicate_rule["path_globs"][0]
    assert (
        f"duplicate-warning-triage:{duplicate_rule['pattern_id']}:{duplicate_glob}"
        in validate_export_contract(duplicate_triage, root_tracked_paths)
    )
    unsafe_triage = copy.deepcopy(manifest)
    unsafe_triage["warning_triage"].append(
        {
            "pattern_id": "credential_word",
            "path_glob": "../outside",
            "disposition": "credential_classification_required",
            "reason": "fixture",
        }
    )
    unsafe_index = len(unsafe_triage["warning_triage"]) - 1
    assert f"unsafe-warning-triage-glob:{unsafe_index}:../outside" in validate_export_contract(
        unsafe_triage,
        root_tracked_paths,
    )
    permissive_triage = copy.deepcopy(manifest)
    credential_fallback = next(
        item
        for item in permissive_triage["warning_triage"]
        if item["pattern_id"] == "credential_word" and item.get("path_glob") == "*"
    )
    credential_fallback["disposition"] = "implementation_security_keyword"
    assert "permissive-warning-triage-catch-all:credential_word" in validate_export_contract(
        permissive_triage,
        root_tracked_paths,
    )
    assert validate_export_contract([], root_tracked_paths) == ["manifest-not-object"]
    unsafe_manifest = copy.deepcopy(manifest)
    unsafe_manifest["include_files"].append("../outside")
    assert "unsafe-include-files:../outside" in validate_export_contract(
        unsafe_manifest,
        root_tracked_paths,
    )
    with tempfile.TemporaryDirectory() as tmp:
        output_fixture = Path(tmp)
        (output_fixture / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
        (output_fixture / "empty-cache").mkdir()
        assert validate_export_tree(
            output_fixture,
            [],
            {"generated_output_files": []},
            include_manifest=False,
        ) == [
            "unexpected-output:unexpected.txt",
            "unexpected-output-directory:empty-cache",
        ]
    hygiene = json.loads((ROOT / "config" / "repository-hygiene.json").read_text(encoding="utf-8"))
    deny_patterns = json.loads(
        (ROOT / "config" / "public-export-deny-patterns.json").read_text(encoding="utf-8")
    )
    assert hygiene["schema"] == "hidloom.repository-hygiene.v5"
    assert hygiene["duplicate_file_threshold_bytes"] == 1
    assert all(item["reason"].strip() for item in hygiene["duplicate_file_allow_groups"])
    assert hygiene["portable_path_policy"] == {
        "unicode_normalization": "NFC",
        "casefold_collisions": True,
        "max_relative_path_utf16_units": 180,
        "max_component_utf16_units": 255,
    }
    assert hygiene["tracked_content_policy"] == {
        "encoding": "UTF-8",
        "line_endings": "LF",
        "reject_bom": True,
        "require_final_newline": True,
        "reject_trailing_whitespace": True,
        "executable_requires_shebang": True,
        "shell_requires_executable": True,
        "shell_path_globs": ["**/*.sh"],
        "binary_path_globs": [
            "**/*.f3d",
            "**/*.ico",
            "**/*.jpg",
            "**/*.jpeg",
            "**/*.png",
        ],
        "empty_file_allow_globs": [
            "daemon/i2cd/__init__.py",
            "daemon/logicd/__init__.py",
        ],
    }
    assert any(item["id"] == "private_machine_hostname" for item in deny_patterns["block"])
    assert any(item["id"] == "private_personal_username" for item in deny_patterns["block"])
    assert any(item["id"] == "retired_software_owner_namespace" for item in deny_patterns["block"])
    assert any(item["id"] == "retired_dbus_namespace" for item in deny_patterns["block"])
    assert any(item["id"] == "private_documentation_path" for item in deny_patterns["block"])
    with tempfile.TemporaryDirectory() as tmp:
        fixture_root = Path(tmp)
        unknown = fixture_root / "daemon" / "new-auth.py"
        unknown.parent.mkdir()
        unknown.write_text("password\n", encoding="utf-8")
        reviewed = fixture_root / "config" / "default" / "config.json"
        reviewed.parent.mkdir(parents=True)
        reviewed.write_text("password\n", encoding="utf-8")
        reviewed_scanner = fixture_root / "tools" / "development_residue_hygiene.py"
        reviewed_scanner.parent.mkdir()
        reviewed_scanner.write_text("token\n", encoding="utf-8")
        credential_findings = apply_warning_triage(
            [
                item
                for item in scan_text_files(fixture_root, deny_patterns)
                if item.pattern_id == "credential_word"
            ],
            manifest,
        )
        dispositions = {item.path: item.disposition for item in credential_findings}
        assert dispositions == {
            "config/default/config.json": "implementation_security_keyword",
            "daemon/new-auth.py": "credential_classification_required",
            "tools/development_residue_hygiene.py": "implementation_security_keyword",
        }
    private_username = "fuji" + "kawa"
    assert any(
        item["from"] in {private_username, "operator"} and item["to"] == "operator"
        for item in manifest["text_replacements"]
    )
    assert any(item["to"] == "/home/USERNAME/hidloom" for item in manifest["text_replacements"])
    assert manifest["public_repository"] == "hidloom"
    assert sum(item["to"] == "<keyboard-ip>" for item in manifest["text_replacements"]) >= 8
    assert sum(item["to"] == "<keyboard-host>" for item in manifest["text_replacements"]) == 4
    assert any(item["disposition"] == "allowed_device_profile" for item in manifest["warning_triage"])
    assert not any(item["disposition"].startswith("legacy_") for item in manifest["warning_triage"])
    assert not any(
        item.get("path_glob") == "*" and not item["disposition"].endswith("_required")
        for item in manifest["warning_triage"]
    )
    validation_suite = (ROOT / "script/test_validation_suite.py").read_text(encoding="utf-8")
    public_pr_gate = (ROOT / "script/public_pr_gate.py").read_text(encoding="utf-8")
    suite_runner = (ROOT / "script/suite_runner.py").read_text(encoding="utf-8")
    assert "HIDLOOM_VALIDATION_SNAPSHOT" in validation_suite
    assert "HIDLOOM_PUBLIC_PR_GATE_SNAPSHOT" in public_pr_gate
    assert "rerun_in_clean_snapshot" in validation_suite
    assert "rerun_in_clean_snapshot" in public_pr_gate
    assert '["git", "ls-files", "--others", "--exclude-standard", "-z"]' in suite_runner
    assert '["git", "commit", "-qm", "Validation snapshot"]' in suite_runner

    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "source"
        source.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=source, check=True)
        subprocess.run(["git", "config", "user.name", "Provenance Fixture"], cwd=source, check=True)
        subprocess.run(
            ["git", "config", "user.email", "provenance@example.invalid"],
            cwd=source,
            check=True,
        )
        tracked = source / "tracked.txt"
        tracked.write_text("clean\n", encoding="utf-8")
        subprocess.run(["git", "add", "tracked.txt"], cwd=source, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=source, check=True)
        assert tracked_files(root=source) == ["tracked.txt"]
        assert worktree_files(root=source) == ["tracked.txt"]
        clean_provenance = source_provenance(["tracked.txt"], root=source)
        assert clean_provenance["mode"] == "clean-head"
        assert clean_provenance["publishable"] is True
        tracked.write_text("dirty\n", encoding="utf-8")
        dirty_provenance = source_provenance(["tracked.txt"], root=source)
        assert dirty_provenance["mode"] == "dirty-worktree"
        assert dirty_provenance["publishable"] is False
        assert (
            dirty_provenance["selected_snapshot_sha256"]
            != clean_provenance["selected_snapshot_sha256"]
        )
        tracked.write_text("clean\n", encoding="utf-8")
        (source / "untracked.txt").write_text("untracked\n", encoding="utf-8")
        assert source_provenance(["tracked.txt"], root=source)["publishable"] is False
        assert worktree_files(root=source) == ["tracked.txt", "untracked.txt"]
        replacement = source / "replacement.txt"
        tracked.rename(replacement)
        assert tracked_files(root=source) == ["tracked.txt"]
        assert worktree_files(root=source) == ["replacement.txt", "untracked.txt"]

    with tempfile.TemporaryDirectory() as tmp:
        machine_fixture = Path(tmp) / ("build-" + "codex" + "001" + ".txt")
        machine_fixture.write_text("接続先=" + "LI" + "01" + "の記録\n", encoding="utf-8")
        machine_findings = [
            item
            for item in scan_text_files(Path(tmp), deny_patterns)
            if item.pattern_id == "private_machine_hostname"
        ]
        assert {item.line for item in machine_findings} == {0, 1}
        username_fixture = Path(tmp) / ("owner-" + "fuji" + "kawa" + ".txt")
        username_fixture.write_text(
            "担当=" + "fuji" + "kawa" + "の記録\n", encoding="utf-8"
        )
        username_findings = [
            item
            for item in scan_text_files(Path(tmp), deny_patterns)
            if item.pattern_id == "private_personal_username"
        ]
        assert {item.line for item in username_findings} == {0, 1}
        retired_owner = "c" + "qa" + "02303"
        namespace_fixture = Path(tmp) / "retired-namespace.txt"
        namespace_fixture.write_text(
            f"server={retired_owner}-keyboard\npath=/com/{retired_owner}/btd\n",
            encoding="utf-8",
        )
        namespace_findings = [
            item
            for item in scan_text_files(Path(tmp), deny_patterns)
            if item.path == namespace_fixture.name
        ]
        assert {(item.pattern_id, item.line) for item in namespace_findings} == {
            ("retired_software_owner_namespace", 1),
            ("retired_dbus_namespace", 2),
        }
        allowed_hardware = Path(tmp) / "kicad" / "hardware.txt"
        allowed_hardware.parent.mkdir()
        allowed_hardware.write_text(f"project={retired_owner}_simple_v4\n", encoding="utf-8")
        allowed_policy = Path(tmp) / "config" / "publication-policy.json"
        allowed_policy.parent.mkdir()
        allowed_policy.write_text(
            json.dumps({"owner": retired_owner}) + "\n",
            encoding="utf-8",
        )
        excluded_findings = [
            item
            for item in scan_text_files(Path(tmp), deny_patterns)
            if item.path in {
                "kicad/hardware.txt",
                "config/publication-policy.json",
            }
            and item.pattern_id == "retired_software_owner_namespace"
        ]
        assert excluded_findings == []
        private_documentation_fixture = Path(tmp) / "docs/ops/release-next-start.md"
        private_documentation_fixture.parent.mkdir(parents=True)
        private_documentation_fixture.write_text("internal handoff\n", encoding="utf-8")
        private_documentation_findings = [
            item
            for item in scan_text_files(Path(tmp), deny_patterns)
            if item.pattern_id == "private_documentation_path"
        ]
        assert [(item.path, item.line) for item in private_documentation_findings] == [
            ("docs/ops/release-next-start.md", 0)
        ]

        destination = Path(tmp) / "public"
        export_command = [
            "python3",
            str(ROOT / "tools" / "public_export.py"),
            str(destination),
            "--draft",
        ]
        source_is_clean = not subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=normal"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        if not source_is_clean:
            export_command.append("--allow-dirty-source")
        result = subprocess.run(
            export_command,
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        assert "exported" in result.stdout
        assert (destination / ".env.example").exists()
        assert (destination / "README.md").exists()
        assert (destination / "INSTALL.md").exists()
        assert (destination / "AUTHORS.md").exists()
        assert (destination / "THIRD_PARTY_NOTICES.md").exists()
        assert (destination / "PUBLIC_EXPORT_MANIFEST.json").exists()
        assert (destination / "SBOM.cdx.json").exists()
        assert (destination / "PUBLIC_PRIVACY_AUDIT.json").exists()
        assert (destination / "PUBLIC_PRIVACY_AUDIT.md").exists()
        assert (destination / "PUBLIC_ASSET_PROVENANCE.json").exists()
        assert (destination / "PUBLIC_ASSET_PROVENANCE.md").exists()
        assert (destination / "PUBLIC_REFERENCE_AUDIT.json").exists()
        assert (destination / "PUBLIC_REFERENCE_AUDIT.md").exists()
        assert (destination / "PUBLIC_DOCUMENTATION_AUDIT.json").exists()
        assert (destination / "PUBLIC_DOCUMENTATION_AUDIT.md").exists()
        assert (destination / "SECURITY.md").exists()
        assert (destination / "CONTRIBUTING.md").exists()
        assert (destination / "SUPPORT.md").exists()
        assert (destination / "CODE_OF_CONDUCT.md").exists()
        assert (destination / "config/github-actions-lock.json").exists()
        assert (destination / "config/public-usb-identity.json").exists()
        assert (destination / "config/public-repository-policy.json").exists()
        assert (destination / ".github/dependabot.yml").exists()
        assert (destination / ".github/ISSUE_TEMPLATE/bug.yml").exists()
        assert (destination / ".github/ISSUE_TEMPLATE/feature.yml").exists()
        assert (destination / ".github/ISSUE_TEMPLATE/config.yml").exists()
        assert (destination / ".github/PULL_REQUEST_TEMPLATE.md").exists()
        assert (destination / ".github/workflows/public-ci.yml").exists()
        assert not (destination / ".github/workflows/public-export-check.yml").exists()
        assert not (destination / ".github/workflows/public-sync.yml").exists()
        assert not (destination / ".github/workflows/repository-hygiene.yml").exists()
        assert (destination / "docs/ops/third-party-inventory.json").exists()
        assert (destination / "docs/ops/buildroot-m6-legal-summary.json").exists()
        assert (destination / "docs/ops/public-documentation-boundary.md").exists()
        assert (destination / "tools/public_source_archive.py").exists()
        assert (destination / "tools/public_repository_create.py").exists()
        assert (destination / "tools/public_repository_bootstrap.py").exists()
        assert (destination / "tools/public_repository_policy.py").exists()
        assert (destination / "tools/pid_codes_application.py").exists()
        assert (destination / "tools/public_usb_identity.py").exists()
        assert (destination / "script/test_pid_codes_application.py").exists()
        assert (destination / "script/test_public_usb_identity.py").exists()
        assert (destination / "script/test_public_repository_create.py").exists()
        assert (destination / "script/test_public_repository_bootstrap.py").exists()
        assert (destination / "script/test_public_repository_policy.py").exists()
        assert (destination / "daemon").is_dir()
        assert (destination / "build" / "buildroot").is_dir()
        assert (destination / "kicad").is_dir()
        assert not (destination / "codex_tasks").exists()
        assert not (destination / "kicad" / "OLD").exists()
        assert not (destination / "docs/CURRENT_STATUS.md").exists()
        assert not (destination / "docs/TODO_PRIORITY.md").exists()
        assert not (destination / "docs/WISHLIST.md").exists()
        assert not (destination / "docs/review").exists()
        assert not (destination / "docs/ops/hidloom-public-release-todo.md").exists()
        assert not (destination / "docs/ops/public-sync-credentials-runbook.md").exists()
        assert not any(
            (destination / relative).exists()
            for relative in PRIVATE_OPERATIONAL_DOCUMENTS
        )
        for public_index in (destination / "README.md", destination / "docs/README.md"):
            assert "private workspace reference" not in public_index.read_text(encoding="utf-8")
        report = json.loads((destination / "PUBLIC_EXPORT_REPORT.json").read_text(encoding="utf-8"))
        export_manifest = json.loads(
            (destination / "PUBLIC_EXPORT_MANIFEST.json").read_text(encoding="utf-8")
        )
        sbom_path = destination / "SBOM.cdx.json"
        sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
        privacy = json.loads((destination / "PUBLIC_PRIVACY_AUDIT.json").read_text(encoding="utf-8"))
        assets = json.loads(
            (destination / "PUBLIC_ASSET_PROVENANCE.json").read_text(encoding="utf-8")
        )
        references = json.loads(
            (destination / "PUBLIC_REFERENCE_AUDIT.json").read_text(encoding="utf-8")
        )
        documentation = json.loads(
            (destination / "PUBLIC_DOCUMENTATION_AUDIT.json").read_text(encoding="utf-8")
        )
        assert report["schema"] == "hidloom.public-export-report.v2"
        assert export_manifest["schema"] == "hidloom.public-export-manifest.v2"
        provenance = report["source_provenance"]
        assert provenance == export_manifest["source_provenance"]
        assert provenance["schema"] == "hidloom.source-provenance.v1"
        assert provenance["publishable"] is source_is_clean
        assert provenance["mode"] == ("clean-head" if source_is_clean else "dirty-worktree")
        assert len(provenance["base_commit"]) == 40
        assert len(provenance["base_tree"]) == 40
        assert provenance["base_revision_count"] > 0
        assert provenance["selected_path_count"] == report["file_count"]
        export_source_paths = tracked_files() if source_is_clean else worktree_files()
        assert report["source_selection"] == source_selection_summary(
            export_source_paths,
            manifest,
        )
        assert report["source_selection"]["public_source_paths"] == report["file_count"]
        assert len(provenance["selected_snapshot_sha256"]) == 64
        assert all(item["mode"] in {0o644, 0o755, 0o777} for item in export_manifest["files"])
        assert sbom["bomFormat"] == "CycloneDX"
        assert sbom["specVersion"] == "1.7"
        assert len(sbom["components"]) == 56
        assert privacy["ready"] is True
        assert privacy["summary"]["blockers"] == 0
        assert privacy["summary"]["media_files"] == 32
        assert assets["ready"] is True
        assert assets["summary"]["assets"] == 49
        assert references["ready"] is True
        assert references["summary"]["blockers"] == 0
        assert references["public_repository"]["slug"] == "cqa02303/hidloom"
        assert documentation["schema"] == "hidloom.public-documentation-audit.v2"
        assert documentation["ready"] is True
        assert documentation["summary"]["public_docs"] > 0
        assert documentation["summary"]["reachable_public_docs"] == documentation[
            "summary"
        ]["public_docs"]
        if (ROOT / "docs/CURRENT_STATUS.md").is_file():
            assert documentation["summary"]["omitted_private_links"] > 0
            assert documentation["summary"]["removed_private_navigation_lines"] > 0
        else:
            assert documentation["summary"]["omitted_private_links"] == 0
            assert documentation["summary"]["removed_private_navigation_lines"] == 0
        assert documentation["summary"]["broken_links"] == 0
        assert documentation["summary"]["orphaned_documents"] == 0
        assert documentation["orphaned_documents"] == []
        assert "block:license_policy_pending" not in report["finding_summary"]
        assert not any(item["severity"] == "block" for item in report["findings"])
        assert not any(
            item["pattern_id"] == "private_machine_hostname" for item in report["findings"]
        )
        assert not any(
            item["pattern_id"] == "private_personal_username" for item in report["findings"]
        )
        assert not any(
            item["pattern_id"] in {
                "retired_software_owner_namespace",
                "retired_dbus_namespace",
            }
            for item in report["findings"]
        )
        assert not any(item["pattern_id"] == "personal_home_path" for item in report["findings"])
        assert not any(
            item["pattern_id"] == "private_ipv4"
            and item["disposition"].endswith("_required")
            for item in report["findings"]
        )
        assert any(
            item["pattern_id"] == "legacy_project_name"
            and item["path"].startswith("kicad/")
            and item["disposition"] == "allowed_device_profile"
            for item in report["findings"]
        )
        assert not any(
            item["severity"] == "warn" and item["disposition"] == "untriaged"
            for item in report["findings"]
        )
        assert any(
            item["disposition"] == "pid_codes_migration_required"
            for item in report["findings"]
        )
        assert not any(
            item["disposition"] == "documentation_migration_required"
            for item in report["findings"]
        )
        assert not any(item["disposition"].startswith("legacy_") for item in report["findings"])
        assert not any(
            item["disposition"] == "namespace_migration_required"
            for item in report["findings"]
        )
        readme = (destination / "README.md").read_text(encoding="utf-8")
        assert "/home/" + "operator/" not in readme
        assert "<user>@<keyboard-ip>:/tmp/" in readme
        assert "github.com/cqa02303/hidloom" not in readme
        security = (destination / "SECURITY.md").read_text(encoding="utf-8")
        contributing = (destination / "CONTRIBUTING.md").read_text(encoding="utf-8")
        authors = (destination / "AUTHORS.md").read_text(encoding="utf-8")
        support = (destination / "SUPPORT.md").read_text(encoding="utf-8")
        conduct = (destination / "CODE_OF_CONDUCT.md").read_text(encoding="utf-8")
        assert "private vulnerability reporting" in security
        assert "Do not open a public issue" in security
        assert "GPL-3.0-or-later" in contributing
        assert "HIDloom contributors" in authors
        assert "does not require copyright assignment" in authors
        assert "There is no guaranteed response time" in support
        assert "Contributor Covenant, version 2.1" in conduct
        assert "Do not publish incident details" in conduct

        regenerated_sbom = destination / "SBOM.regenerated.json"
        subprocess.run(
            [
                "python3",
                str(destination / "tools/generate_cyclonedx_sbom.py"),
                str(destination),
                "--output",
                str(regenerated_sbom),
            ],
            cwd=destination,
            check=True,
            capture_output=True,
            text=True,
        )
        assert regenerated_sbom.read_bytes() == sbom_path.read_bytes()
        regenerated_sbom.unlink()

        exported_checks = (
            ["python3", "script/test_docs_links.py"],
            ["python3", "script/test_hidloom_identity.py"],
            ["python3", "script/test_hidloom_paths.py"],
            ["python3", "script/test_third_party_inventory.py"],
            ["python3", "script/test_public_repository_create.py"],
            ["python3", "script/test_public_repository_policy.py"],
            ["python3", "script/test_public_source_archive.py"],
            ["python3", "script/test_public_privacy_audit.py"],
            ["python3", "script/test_public_asset_inventory.py"],
            ["python3", "script/test_public_documentation_audit.py"],
            ["python3", "script/test_public_community_health.py"],
            ["python3", "script/test_daemon_specs_coverage.py"],
            ["python3", "script/test_fresh_install_docs.py"],
            ["python3", "script/test_kicad_generation.py"],
            ["python3", "tools/public_reference_audit.py", ".", "--check-only"],
            ["python3", "script/test_repository_hygiene.py"],
            ["python3", "script/test_source_syntax_hygiene.py"],
            ["python3", "script/test_development_residue_hygiene.py"],
            ["python3", "script/test_generated_binary_hygiene.py"],
            ["python3", "script/test_workspace_debris_hygiene.py"],
            ["python3", "script/test_local_environment_hygiene.py"],
            ["python3", "script/test_license_evidence_tools.py"],
            ["python3", "script/test_buildroot_legal_summary.py"],
            ["python3", "tools/buildroot_source_prepare.py", "--help"],
            ["tools/public_build_rehearsal.sh", "--help"],
            [
                "python3",
                "tools/public_export_manifest.py",
                "verify",
                ".",
                "--allow-draft-source",
            ],
            ["python3", "tools/public_build_provenance.py", "--help"],
            ["python3", "tools/public_release_bundle.py", "--help"],
            ["python3", "tools/public_sync_branch.py", "--help"],
            ["python3", "tools/public_repository_bootstrap.py", "--help"],
            ["python3", "tools/public_repository_policy.py", "plan"],
        )
        exported_environment = os.environ.copy()
        exported_environment["PYTHONDONTWRITEBYTECODE"] = "1"
        exported_environment["PYTHONPYCACHEPREFIX"] = str(
            Path(tmp) / "exported-bytecode-cache"
        )
        bytecode_safe_importers = {
            "tools/public_repository_create.py": "from public_repository_policy import",
            "script/test_public_documentation_audit.py": "sys.path.insert",
            "script/test_public_release_bundle.py": "sys.path.insert",
            "script/test_public_release_readiness.py": "sys.path.insert",
            "script/test_public_repository_create.py": "sys.path.insert",
            "script/test_public_repository_policy.py": "sys.path.insert",
            "script/test_remote_fresh_install_tool.py": "sys.path.insert",
        }
        for relative, import_marker in bytecode_safe_importers.items():
            source = (destination / relative).read_text(encoding="utf-8")
            assert source.index("sys.dont_write_bytecode = True") < source.index(
                import_marker
            ), relative
        direct_import_environment = exported_environment.copy()
        direct_import_environment["PYTHONDONTWRITEBYTECODE"] = "0"
        direct_import_environment.pop("PYTHONPYCACHEPREFIX")
        for direct_command in (
            ["python3", "tools/public_repository_create.py", "plan"],
            ["python3", "script/test_public_repository_create.py"],
            ["python3", "script/test_public_repository_policy.py"],
            ["python3", "script/test_remote_fresh_install_tool.py"],
        ):
            direct_import = subprocess.run(
                direct_command,
                cwd=destination,
                env=direct_import_environment,
                capture_output=True,
                text=True,
            )
            assert direct_import.returncode == 0, (
                f"direct importing check failed: {direct_command}\n"
                f"stdout:\n{direct_import.stdout}\nstderr:\n{direct_import.stderr}"
            )
        assert not any(destination.rglob("__pycache__"))
        for command in exported_checks:
            checked = subprocess.run(
                command,
                cwd=destination,
                env=exported_environment,
                capture_output=True,
                text=True,
            )
            assert checked.returncode == 0, (
                f"exported check failed: {command}\nstdout:\n{checked.stdout}\nstderr:\n{checked.stderr}"
            )
        expected_paths = {
            "PUBLIC_EXPORT_MANIFEST.json",
            *(item["path"] for item in export_manifest["files"]),
        }
        actual_paths = {
            path.relative_to(destination).as_posix()
            for path in destination.rglob("*")
            if path.is_file() or path.is_symlink()
        }
        assert actual_paths == expected_paths
        public_source_paths = [path for path in export_source_paths if selected(path, manifest)]
        assert validate_export_tree(
            destination,
            public_source_paths,
            manifest,
            include_manifest=True,
        ) == []
        assert not any(destination.rglob("__pycache__"))

    print("ok: HIDloom public export is deterministic and audited")


if __name__ == "__main__":
    main()
