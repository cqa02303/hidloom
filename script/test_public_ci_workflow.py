#!/usr/bin/env python3
"""Static checks for the standalone public CI contract."""
from __future__ import annotations

import json
from pathlib import Path

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


def main() -> None:
    workflow = (ROOT / ".github" / "workflows" / "public-ci.yml").read_text(encoding="utf-8")
    policy = json.loads(
        (ROOT / "config" / "public-repository-policy.json").read_text(encoding="utf-8")
    )
    required_contexts = policy["branch_protection"]["required_status_checks"]["contexts"]
    assert required_contexts == ["validate"]
    for context in required_contexts:
        assert f"  {context}:\n" in workflow

    assert workflow.count("runs-on: ubuntu-24.04") == 2
    assert "ubuntu-latest" not in workflow
    assert "timeout-minutes: 45" in workflow
    for package in APT_PACKAGES:
        assert package in workflow, package

    assert 'echo "/usr/bin" >> "$GITHUB_PATH"' in workflow
    assert "/usr/bin/python3 - <<'PY'" in workflow
    for module in ("aiohttp", "dbus_next", "numpy", "PIL", "yaml"):
        assert module in workflow, module

    assert workflow.count("python3 script/test_validation_suite.py") == 1
    assert "python3 script/test_remote_fresh_install_tool.py" in workflow
    assert workflow.count("python3 script/test_source_syntax_hygiene.py") == 1
    assert workflow.count("python3 script/test_development_residue_hygiene.py") == 1
    assert "python3 -m compileall" not in workflow
    rust_target = "rustup target add aarch64-unknown-linux-musl"
    assert workflow.count(rust_target) == 1
    assert workflow.index(rust_target) < workflow.index("python3 script/test_validation_suite.py")
    assert "cargo fetch --locked" in workflow
    assert "cargo test --locked" in workflow
    assert "git diff --check" in workflow

    print("ok: public CI installs dependencies and runs canonical full validation")


if __name__ == "__main__":
    main()
