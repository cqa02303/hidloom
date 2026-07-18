#!/usr/bin/env python3
"""Static checks for the standalone public CI contract."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True

from public_pr_gate import TESTS as PUBLIC_PR_TESTS  # noqa: E402
from test_validation_suite import TESTS as FULL_TESTS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

APT_PACKAGES = (
    "build-essential",
    "fakeroot",
    "python3-aiohttp",
    "python3-dbus-next",
    "python3-numpy",
    "python3-pil",
    "python3-yaml",
    "rsync",
    "zstd",
)

REQUIRED_PUBLIC_PR_TESTS = {
    "script/test_hidloom_identity.py",
    "script/test_repository_hygiene.py",
    "script/test_source_syntax_hygiene.py",
    "script/test_development_residue_hygiene.py",
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
}


def job_blocks(workflow: str) -> dict[str, str]:
    lines = workflow.splitlines()
    jobs_index = lines.index("jobs:")
    starts = [
        (index, match.group(1))
        for index, line in enumerate(lines[jobs_index + 1 :], start=jobs_index + 1)
        if (match := re.fullmatch(r"  ([A-Za-z0-9_-]+):", line))
    ]
    blocks: dict[str, str] = {}
    for position, (start, name) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        blocks[name] = "\n".join(lines[start:end])
    return blocks


def main() -> None:
    workflow = (ROOT / ".github" / "workflows" / "public-ci.yml").read_text(encoding="utf-8")
    policy = json.loads(
        (ROOT / "config" / "public-repository-policy.json").read_text(encoding="utf-8")
    )
    required_contexts = policy["branch_protection"]["required_status_checks"]["contexts"]
    assert required_contexts == ["validate"]
    jobs = job_blocks(workflow)
    assert set(jobs) == {"validate", "extended", "open-sync-pr"}
    for context in required_contexts:
        assert context in jobs

    assert workflow.count("runs-on: ubuntu-24.04") == 3
    assert "ubuntu-latest" not in workflow
    assert "timeout-minutes: 15" in jobs["validate"]
    assert "timeout-minutes: 45" in workflow
    assert "release:" in workflow
    assert "- published" in workflow

    validate = jobs["validate"]
    assert "sudo apt-get install -y python3-yaml" in validate
    assert "python3 script/public_pr_gate.py" in validate
    assert "python3 script/test_validation_suite.py" not in validate
    assert "cargo " not in validate
    assert "rustup " not in validate
    assert "git diff --check" in validate

    assert len(PUBLIC_PR_TESTS) == len(set(PUBLIC_PR_TESTS))
    assert set(PUBLIC_PR_TESTS) <= set(FULL_TESTS)
    assert REQUIRED_PUBLIC_PR_TESTS <= set(PUBLIC_PR_TESTS)

    extended = jobs["extended"]
    expected_condition = (
        "if: github.event_name == 'workflow_dispatch' || github.event_name == 'release' || "
        "(github.event_name == 'push' && github.ref == 'refs/heads/main')"
    )
    assert expected_condition in extended
    for package in APT_PACKAGES:
        assert package in extended, package

    assert 'echo "/usr/bin" >> "$GITHUB_PATH"' in extended
    assert "/usr/bin/python3 - <<'PY'" in extended
    for module in ("aiohttp", "dbus_next", "numpy", "PIL", "yaml"):
        assert module in extended, module

    assert workflow.count("python3 script/test_validation_suite.py") == 1
    assert "python3 script/test_remote_fresh_install_tool.py" in extended
    assert extended.count("python3 script/test_source_syntax_hygiene.py") == 1
    assert extended.count("python3 script/test_development_residue_hygiene.py") == 1
    assert "python3 -m compileall" not in workflow
    rust_target = "rustup target add aarch64-unknown-linux-musl"
    assert workflow.count(rust_target) == 1
    assert workflow.index(rust_target) < workflow.index("python3 script/test_validation_suite.py")
    assert "cargo fetch --locked" in extended
    assert "cargo test --locked" in extended
    assert "git diff --check" in extended

    print("ok: public CI separates required PR, extended, and release validation weights")


if __name__ == "__main__":
    main()
