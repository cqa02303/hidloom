#!/usr/bin/env python3
"""Run the bounded validation gate required for public pull requests."""
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True

from suite_runner import rerun_in_clean_snapshot, run_suite  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


TESTS = [
    "script/test_hidloom_identity.py",
    "script/test_pid_codes_allocation.py",
    "script/test_public_usb_identity.py",
    "script/test_hidloom_runtime_environment.py",
    "script/test_hidloom_name_audit.py",
    "script/test_repository_hygiene.py",
    "script/test_source_syntax_hygiene.py",
    "script/test_development_residue_hygiene.py",
    "script/test_generated_binary_hygiene.py",
    "script/test_rust_lockfile_policy.py",
    "script/test_public_export.py",
    "script/test_public_privacy_audit.py",
    "script/test_public_asset_inventory.py",
    "script/test_public_documentation_audit.py",
    "script/test_public_community_health.py",
    "script/test_public_reference_audit.py",
    "script/test_public_ci_workflow.py",
    "script/test_github_workflow_security.py",
    "script/test_public_repository_policy.py",
    "script/test_license_evidence_tools.py",
    "script/test_third_party_inventory.py",
    "script/test_basic_hid_keycode_runtime.py",
    "script/test_vial_protocol_local.py",
    "script/test_usbd_validation.py",
    "script/test_usb_gadget_descriptor.py",
    "script/test_jis_zenkaku_hankaku_routing.py",
    "script/test_oled_alert_ascii.py",
    "script/test_fresh_install_docs.py",
]


def main() -> None:
    rerun_in_clean_snapshot(
        ROOT,
        "script/public_pr_gate.py",
        "HIDLOOM_PUBLIC_PR_GATE_SNAPSHOT",
    )
    duplicates = sorted({test for test in TESTS if TESTS.count(test) > 1})
    if duplicates:
        raise SystemExit(f"duplicate public PR gate entries: {duplicates}")
    run_suite("public PR gate passed", TESTS, stop_on_failure=True)


if __name__ == "__main__":
    main()
