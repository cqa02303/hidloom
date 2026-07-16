#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "script"))

from test_buildroot_compliance_bundle import make_compliance_fixture  # noqa: E402


def write_export_json(export: Path, relative: str, payload: dict[str, object]) -> None:
    content = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    write_export_content(export, relative, content)


def write_export_content(export: Path, relative: str, content: bytes) -> None:
    (export / relative).write_bytes(content)
    manifest_path = export / "PUBLIC_EXPORT_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(item for item in manifest["files"] if item["path"] == relative)
    entry["size"] = len(content)
    entry["sha256"] = hashlib.sha256(content).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        export = Path(tmp) / "export"
        subprocess.run(
            ["python3", str(ROOT / "tools/public_export.py"), str(export), "--draft"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        readiness = subprocess.run(
            ["python3", str(export / "tools/public_release_readiness.py"), "--allow-pending-pid"],
            cwd=export,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(readiness.stdout)
        assert payload["schema"] == "hidloom.public-release-readiness.v3"
        assert payload["evaluation_scope"] == "source-publication"
        assert payload["ready"] is True
        assert payload["source_publication_ready"] is True
        assert payload["blocking_count"] == 0
        assert payload["action_required_count"] == 12
        assert payload["pending_dispositions"] == ["pid_codes_migration_required"]
        assert payload["privacy_summary"]["blockers"] == 0
        assert payload["privacy_summary"]["media_files"] == 8
        assert payload["checks"]["asset_provenance_ready"] is True
        assert payload["checks"]["public_reference_audit_ready"] is True
        assert payload["checks"]["public_documentation_audit_ready"] is True
        assert payload["documentation_audit_issues"] == []
        assert payload["reference_summary"]["blockers"] == 0
        assert payload["documentation_summary"]["broken_links"] == 0
        assert payload["documentation_summary"]["orphaned_documents"] == 0
        assert payload["documentation_summary"]["reachable_public_docs"] == payload[
            "documentation_summary"
        ]["public_docs"]
        if (ROOT / "docs/CURRENT_STATUS.md").is_file():
            assert payload["documentation_summary"]["omitted_private_links"] > 0
            assert payload["documentation_summary"]["removed_private_navigation_lines"] > 0
        else:
            assert payload["documentation_summary"]["omitted_private_links"] == 0
            assert payload["documentation_summary"]["removed_private_navigation_lines"] == 0
        assert payload["asset_summary"]["assets"] == 25
        assert payload["checks"]["third_party_redistributed_complete"] is True
        assert payload["checks"]["github_actions_supply_chain_ready"] is True
        assert payload["github_actions_issues"] == []
        assert payload["checks"]["community_health_ready"] is True
        assert payload["community_health_issues"] == []
        assert payload["checks"]["public_repository_policy_ready"] is True
        assert payload["repository_policy_issues"] == []
        assert payload["checks"]["public_identity_ready"] is True
        assert payload["public_identity_issues"] == []
        assert payload["checks"]["development_residue_ready"] is True
        assert payload["development_residue_issues"] == []
        assert payload["checks"]["source_selection_ready"] is True
        assert payload["source_selection_issues"] == []
        assert payload["third_party_summary"]["total"] == 56
        assert payload["checks"]["buildroot_source_audit_ready"] is True
        assert payload["binary_distribution_ready"] is False
        assert payload["binary_distribution_status"] == "compliance-bundle-required"
        assert payload["binary_distribution_issues"] == ["compliance-bundle-required"]
        assert payload["binary_distribution"]["raw_release_blockers"] == [
            "bootlin-toolchain-compliance-not-bundled",
            "buildroot-source-not-bundled",
        ]
        documentation_path = export / "PUBLIC_DOCUMENTATION_AUDIT.json"
        original_documentation = documentation_path.read_bytes()
        documentation = json.loads(original_documentation)
        documentation["summary"]["reachable_public_docs"] -= 1
        documentation["summary"]["orphaned_documents"] = 1
        documentation["orphaned_documents"] = [{"path": "docs/not-present.md"}]
        write_export_json(export, "PUBLIC_DOCUMENTATION_AUDIT.json", documentation)
        documentation_tamper = subprocess.run(
            [
                "python3",
                str(export / "tools/public_release_readiness.py"),
                "--allow-pending-pid",
            ],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert documentation_tamper.returncode == 2
        documentation_tamper_payload = json.loads(documentation_tamper.stdout)
        assert documentation_tamper_payload["checks"][
            "public_documentation_audit_ready"
        ] is False
        assert "ready-mismatch" in documentation_tamper_payload[
            "documentation_audit_issues"
        ]
        assert "orphan-inventory-mismatch" in documentation_tamper_payload[
            "documentation_audit_issues"
        ]
        assert documentation_tamper_payload["checks"]["manifest_integrity"] is True
        write_export_content(
            export, "PUBLIC_DOCUMENTATION_AUDIT.json", original_documentation
        )
        javascript_path = export / "daemon/http/static/matrix_tester.js"
        original_javascript = javascript_path.read_bytes()
        write_export_content(
            export,
            "daemon/http/static/matrix_tester.js",
            original_javascript + b'console.log("fixture residue");\n',
        )
        residue = subprocess.run(
            [
                "python3",
                str(export / "tools/public_release_readiness.py"),
                "--allow-pending-pid",
            ],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert residue.returncode == 2
        residue_payload = json.loads(residue.stdout)
        assert residue_payload["checks"]["development_residue_ready"] is False
        assert any(
            issue.startswith(
                "javascript_debug_output:daemon/http/static/matrix_tester.js:"
            )
            for issue in residue_payload["development_residue_issues"]
        )
        assert residue_payload["checks"]["manifest_integrity"] is True
        write_export_content(
            export,
            "daemon/http/static/matrix_tester.js",
            original_javascript,
        )
        pull_request_template = export / ".github/PULL_REQUEST_TEMPLATE.md"
        original_pull_request_template = pull_request_template.read_bytes()
        pull_request_template.unlink()
        missing_community = subprocess.run(
            [
                "python3",
                str(export / "tools/public_release_readiness.py"),
                "--allow-pending-pid",
            ],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert missing_community.returncode == 2
        missing_community_payload = json.loads(missing_community.stdout)
        assert missing_community_payload["checks"]["community_health_ready"] is False
        assert "missing:.github/PULL_REQUEST_TEMPLATE.md" in missing_community_payload[
            "community_health_issues"
        ]
        assert ".github/PULL_REQUEST_TEMPLATE.md" in missing_community_payload["missing_files"]
        pull_request_template.write_bytes(original_pull_request_template)
        strict = subprocess.run(
            ["python3", str(export / "tools/public_release_readiness.py")],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert strict.returncode == 2
        plan = subprocess.run(
            [
                "python3",
                str(export / "tools/public_sync_plan.py"),
                str(export),
                "--allow-pending-pid",
            ],
            cwd=export,
            check=True,
            capture_output=True,
            text=True,
        )
        sync = json.loads(plan.stdout)
        assert sync["dry_run"] is True
        assert sync["branch"].startswith("sync/v0.1.0-")
        assert len(sync["export_manifest_sha256"]) == 64
        assert any("git -C" in command and "add -f -A" in command for command in sync["commands"])
        assert not any(command.endswith(" add -A") for command in sync["commands"])
        assert not (export / ".git").exists()

        binary_without_bundle = subprocess.run(
            [
                "python3",
                str(export / "tools/public_release_readiness.py"),
                "--allow-pending-pid",
                "--require-binary-distribution",
            ],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert binary_without_bundle.returncode == 2
        binary_without_payload = json.loads(binary_without_bundle.stdout)
        assert binary_without_payload["source_publication_ready"] is True
        assert binary_without_payload["ready"] is False
        assert binary_without_payload["evaluation_scope"] == "binary-distribution"

        compliance = make_compliance_fixture(Path(tmp) / "compliance", export)
        compliance_result = json.loads(
            subprocess.check_output(
                [
                    "python3",
                    str(export / "tools/buildroot_compliance_bundle.py"),
                    "verify",
                    str(compliance),
                    "--json",
                ],
                cwd=export,
                text=True,
            )
        )
        mismatched_binary = subprocess.run(
            [
                "python3",
                str(export / "tools/public_release_readiness.py"),
                "--allow-pending-pid",
                "--compliance-bundle",
                str(compliance),
            ],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert mismatched_binary.returncode == 2
        mismatched_payload = json.loads(mismatched_binary.stdout)
        assert "compliance-buildroot-commit-mismatch" in mismatched_payload[
            "binary_distribution_issues"
        ]
        assert "compliance-toolchain-version-mismatch" in mismatched_payload[
            "binary_distribution_issues"
        ]

        buildroot_path = export / "config/buildroot-source.json"
        buildroot = json.loads(buildroot_path.read_text(encoding="utf-8"))
        buildroot["commit"] = compliance_result["buildroot_commit"]
        write_export_json(export, "config/buildroot-source.json", buildroot)
        toolchain_path = export / "config/buildroot-toolchain-evidence.json"
        toolchain = json.loads(toolchain_path.read_text(encoding="utf-8"))
        toolchain["version"] = compliance_result["bootlin_version"]
        write_export_json(export, "config/buildroot-toolchain-evidence.json", toolchain)
        legal_path = export / "docs/ops/buildroot-m6-legal-summary.json"
        legal = json.loads(legal_path.read_text(encoding="utf-8"))
        legal["buildroot_source"]["commit"] = compliance_result["buildroot_commit"]
        legal["toolchain_evidence"]["version"] = compliance_result["bootlin_version"]
        write_export_json(export, "docs/ops/buildroot-m6-legal-summary.json", legal)

        binary_ready = subprocess.run(
            [
                "python3",
                str(export / "tools/public_release_readiness.py"),
                "--allow-pending-pid",
                "--compliance-bundle",
                str(compliance),
            ],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert binary_ready.returncode == 0, binary_ready.stdout + binary_ready.stderr
        binary_payload = json.loads(binary_ready.stdout)
        assert binary_payload["ready"] is True
        assert binary_payload["evaluation_scope"] == "binary-distribution"
        assert binary_payload["binary_distribution_ready"] is True
        assert binary_payload["binary_distribution_status"] == "verified-compliance-bundle"
        assert binary_payload["binary_distribution_issues"] == []
        assert binary_payload["binary_distribution"]["compliance_bundle_verified"] is True
        assert binary_payload["binary_distribution"]["evidence"]["archive_sha256"] == (
            compliance_result["archive_sha256"]
        )

        tampered_compliance = Path(tmp) / "tampered-compliance.tar.zst"
        shutil.copy2(compliance, tampered_compliance)
        tampered_content = bytearray(tampered_compliance.read_bytes())
        tampered_content[0] ^= 0xFF
        tampered_compliance.write_bytes(tampered_content)
        tampered_binary = subprocess.run(
            [
                "python3",
                str(export / "tools/public_release_readiness.py"),
                "--allow-pending-pid",
                "--compliance-bundle",
                str(tampered_compliance),
            ],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert tampered_binary.returncode == 2, tampered_binary.stdout + tampered_binary.stderr
        tampered_payload = json.loads(tampered_binary.stdout)
        assert tampered_payload["binary_distribution_issues"] == [
            "compliance-bundle-verification-failed"
        ]

        report_path = export / "PUBLIC_EXPORT_REPORT.json"
        manifest_path = export / "PUBLIC_EXPORT_MANIFEST.json"
        original_report_text = report_path.read_text(encoding="utf-8")
        original_manifest_text = manifest_path.read_text(encoding="utf-8")
        invalid_selection_report = json.loads(original_report_text)
        invalid_selection_report["source_selection"]["tracked_paths"] += 1
        invalid_selection_report["source_selection"]["unclassified_paths"] = 1
        write_export_json(
            export,
            "PUBLIC_EXPORT_REPORT.json",
            invalid_selection_report,
        )
        invalid_selection = subprocess.run(
            ["python3", str(export / "tools/public_release_readiness.py"), "--allow-pending-pid"],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert invalid_selection.returncode == 2
        invalid_selection_payload = json.loads(invalid_selection.stdout)
        assert invalid_selection_payload["checks"]["source_selection_ready"] is False
        assert invalid_selection_payload["checks"]["manifest_integrity"] is True
        assert invalid_selection_payload["checks"]["source_provenance_ready"] is True
        assert invalid_selection_payload["source_selection_issues"] == [
            "source-selection:unclassified-paths"
        ]
        invalid_materialize = subprocess.run(
            [
                "python3",
                str(export / "tools/public_export_manifest.py"),
                "materialize",
                str(export),
                str(Path(tmp) / "invalid-selection-materialized"),
            ],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert invalid_materialize.returncode != 0
        assert "source-selection:unclassified-paths" in invalid_materialize.stderr
        write_export_content(
            export,
            "PUBLIC_EXPORT_REPORT.json",
            original_report_text.encode(),
        )
        dirty_report = json.loads(original_report_text)
        dirty_manifest = json.loads(original_manifest_text)
        dirty_provenance = dict(dirty_report["source_provenance"])
        dirty_provenance.update({"mode": "dirty-worktree", "publishable": False})
        dirty_report["source_provenance"] = dirty_provenance
        report_content = (json.dumps(dirty_report, ensure_ascii=False, indent=2) + "\n").encode()
        report_path.write_bytes(report_content)
        dirty_manifest["source_provenance"] = dirty_provenance
        report_entry = next(
            item
            for item in dirty_manifest["files"]
            if item["path"] == "PUBLIC_EXPORT_REPORT.json"
        )
        report_entry["size"] = len(report_content)
        report_entry["sha256"] = hashlib.sha256(report_content).hexdigest()
        manifest_path.write_text(
            json.dumps(dirty_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        dirty_readiness = subprocess.run(
            ["python3", str(export / "tools/public_release_readiness.py"), "--allow-pending-pid"],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert dirty_readiness.returncode == 2
        dirty_payload = json.loads(dirty_readiness.stdout)
        assert dirty_payload["checks"]["source_provenance_ready"] is False
        assert dirty_payload["checks"]["manifest_integrity"] is True
        assert dirty_payload["source_provenance_issues"] == [
            "source-provenance:not-publishable"
        ]
        dirty_sync = subprocess.run(
            [
                "python3",
                str(export / "tools/public_sync_plan.py"),
                str(export),
                "--allow-pending-pid",
            ],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert dirty_sync.returncode != 0
        assert "source-provenance:not-publishable" in dirty_sync.stderr

        dirty_manifest["source_provenance"] = json.loads(original_manifest_text)[
            "source_provenance"
        ]
        manifest_path.write_text(
            json.dumps(dirty_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        mismatch = subprocess.run(
            ["python3", str(export / "tools/public_release_readiness.py"), "--allow-pending-pid"],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert mismatch.returncode == 2
        assert "source-provenance:report-manifest-mismatch" in json.loads(mismatch.stdout)[
            "source_provenance_issues"
        ]

        invalid_report = json.loads(original_report_text)
        invalid_manifest = json.loads(original_manifest_text)
        invalid_report["source_provenance"] = "invalid"
        invalid_content = (json.dumps(invalid_report, ensure_ascii=False, indent=2) + "\n").encode()
        report_path.write_bytes(invalid_content)
        invalid_manifest["source_provenance"] = "invalid"
        invalid_entry = next(
            item
            for item in invalid_manifest["files"]
            if item["path"] == "PUBLIC_EXPORT_REPORT.json"
        )
        invalid_entry["size"] = len(invalid_content)
        invalid_entry["sha256"] = hashlib.sha256(invalid_content).hexdigest()
        manifest_path.write_text(
            json.dumps(invalid_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        malformed = subprocess.run(
            ["python3", str(export / "tools/public_release_readiness.py"), "--allow-pending-pid"],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert malformed.returncode == 2
        malformed_payload = json.loads(malformed.stdout)
        assert malformed_payload["source_commit"] == ""
        assert malformed_payload["checks"]["source_provenance_ready"] is False
        assert "source-provenance:not-object" in malformed_payload[
            "source_provenance_issues"
        ]
        report_path.write_text(original_report_text, encoding="utf-8")
        manifest_path.write_text(original_manifest_text, encoding="utf-8")

        policy_path = export / "config/public-repository-policy.json"
        original_policy = policy_path.read_text(encoding="utf-8")
        policy_path.write_text(
            original_policy.replace(
                '"sha_pinning_required": true',
                '"sha_pinning_required": false',
            ),
            encoding="utf-8",
        )
        unsafe_policy = subprocess.run(
            [
                "python3",
                str(export / "tools/public_release_readiness.py"),
                "--allow-pending-pid",
            ],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert unsafe_policy.returncode == 2
        unsafe_payload = json.loads(unsafe_policy.stdout)
        assert unsafe_payload["checks"]["public_repository_policy_ready"] is False
        assert "unsafe-actions-permissions" in unsafe_payload["repository_policy_issues"]
        policy_path.write_text(original_policy, encoding="utf-8")

        identity_path = export / "config/project-identity.json"
        original_identity = identity_path.read_text(encoding="utf-8")
        identity_path.write_text(
            original_identity.replace('"initial_public_version": "0.1.0"', '"initial_public_version": "9.9.9"'),
            encoding="utf-8",
        )
        inconsistent_identity = subprocess.run(
            [
                "python3",
                str(export / "tools/public_release_readiness.py"),
                "--allow-pending-pid",
            ],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert inconsistent_identity.returncode == 2
        inconsistent_payload = json.loads(inconsistent_identity.stdout)
        assert inconsistent_payload["checks"]["public_identity_ready"] is False
        assert "initial-version-mismatch" in inconsistent_payload["public_identity_issues"]
        identity_path.write_text(original_identity, encoding="utf-8")

        usb_identity_path = export / "config/public-usb-identity.json"
        original_usb_identity = usb_identity_path.read_bytes()
        usb_identity = json.loads(original_usb_identity)
        usb_identity["profiles"]["public_formal"]["usb"]["product_name"] = "Unreviewed"
        write_export_json(export, "config/public-usb-identity.json", usb_identity)
        invalid_usb_identity = subprocess.run(
            [
                "python3",
                str(export / "tools/public_release_readiness.py"),
                "--allow-pending-pid",
            ],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert invalid_usb_identity.returncode == 2
        invalid_usb_payload = json.loads(invalid_usb_identity.stdout)
        assert invalid_usb_payload["checks"]["public_identity_ready"] is False
        assert "public-usb-contract:public-product-name-invalid" in invalid_usb_payload[
            "public_identity_issues"
        ]
        write_export_content(export, "config/public-usb-identity.json", original_usb_identity)

        write_export_content(export, "config/public-usb-identity.json", b"[]\n")
        non_object_usb_identity = subprocess.run(
            [
                "python3",
                str(export / "tools/public_release_readiness.py"),
                "--allow-pending-pid",
            ],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert non_object_usb_identity.returncode == 2
        non_object_usb_payload = json.loads(non_object_usb_identity.stdout)
        assert non_object_usb_payload["checks"]["public_identity_ready"] is False
        assert "public-usb-contract:contract-unreadable" in non_object_usb_payload[
            "public_identity_issues"
        ]
        write_export_content(export, "config/public-usb-identity.json", original_usb_identity)

        authors_path = export / "AUTHORS.md"
        original_authors = authors_path.read_text(encoding="utf-8")
        authors_path.unlink()
        missing_authors = subprocess.run(
            [
                "python3",
                str(export / "tools/public_release_readiness.py"),
                "--allow-pending-pid",
            ],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert missing_authors.returncode == 2
        missing_authors_payload = json.loads(missing_authors.stdout)
        assert missing_authors_payload["checks"]["public_identity_ready"] is False
        assert "authors-policy-missing" in missing_authors_payload["public_identity_issues"]
        assert "AUTHORS.md" in missing_authors_payload["missing_files"]
        authors_path.write_text(original_authors, encoding="utf-8")

        workflow = export / ".github/workflows/public-ci.yml"
        original_workflow = workflow.read_text(encoding="utf-8")
        workflow.write_text(
            original_workflow.replace(
                "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0",
                "actions/checkout@v7",
                1,
            ),
            encoding="utf-8",
        )
        mutable_action = subprocess.run(
            ["python3", str(export / "tools/public_release_readiness.py"), "--allow-pending-pid"],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert mutable_action.returncode == 2
        mutable_payload = json.loads(mutable_action.stdout)
        assert mutable_payload["checks"]["github_actions_supply_chain_ready"] is False
        assert any(
            issue.startswith("mutable-action:")
            for issue in mutable_payload["github_actions_issues"]
        )
        workflow.write_text(original_workflow, encoding="utf-8")

        readme = export / "README.md"
        readme.write_text(readme.read_text(encoding="utf-8") + "\ntampered\n", encoding="utf-8")
        tampered = subprocess.run(
            ["python3", str(export / "tools/public_release_readiness.py"), "--allow-pending-pid"],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert tampered.returncode == 2
        tampered_payload = json.loads(tampered.stdout)
        assert tampered_payload["checks"]["manifest_integrity"] is False
        assert "hash:README.md" in tampered_payload["manifest_mismatches"]

    print("ok: public release readiness and sync plan remain non-mutating")


if __name__ == "__main__":
    main()
