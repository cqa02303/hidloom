#!/usr/bin/env python3
"""Regression checks for the test inventory document."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _literal_string_sequence(path: Path, name: str) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        value = ast.literal_eval(node.value)
        assert isinstance(value, (list, tuple)), f"{path.relative_to(ROOT)} {name} is not a list/tuple"
        assert all(isinstance(item, str) for item in value), f"{path.relative_to(ROOT)} {name} has non-string item"
        return list(value)
    raise AssertionError(f"{path.relative_to(ROOT)} does not define {name}")


def main() -> None:
    inventory = (ROOT / "docs" / "ops" / "test-script-inventory.md").read_text(encoding="utf-8")
    script_tests = sorted((ROOT / "script").glob("test_*.py"))
    assert f"`script/test_*.py` は {len(script_tests)} 本程度" in inventory
    canonical_tests = _literal_string_sequence(ROOT / "script/test_validation_suite.py", "TESTS")
    assert f"標準 canonical suite は {len(canonical_tests)} entrypoints" in inventory

    root_shell_helpers = sorted(path for path in ROOT.glob("*.sh") if path.is_file())
    assert root_shell_helpers, "no root shell helper inventory candidates found"
    for path in root_shell_helpers:
        rel = path.relative_to(ROOT).as_posix()
        assert rel in inventory, rel

    assert "script/test_validation_suite.py" in inventory
    assert "script/test_tools_readme.py" in inventory
    assert "script/suite_runner.py" in inventory
    assert "HIDLOOM_TOUCH_PANEL_REMOTE_DEBUGGING_PORT" in inventory
    assert "HIDLOOM_TOUCH_PANEL_BROWSER_REPAIR_DELAY_SEC" in inventory
    assert "HIDLOOM_TOUCH_PANEL_BROWSER_REPAIR_ATTEMPTS" in inventory
    assert "HIDLOOM_TOUCH_PANEL_BROWSER_REPAIR_INTERVAL_SEC" in inventory
    assert "tools/touch_kiosk_health_probe.py" in inventory

    helper_scripts = sorted(
        path
        for path in (ROOT / "script").iterdir()
        if path.is_file()
        and path.name != "README.md"
        and not path.name.startswith("test_")
        and path.suffix in {".py", ".sh"}
    )
    assert helper_scripts, "no script helper inventory candidates found"
    for path in helper_scripts:
        rel = path.relative_to(ROOT).as_posix()
        assert rel in inventory, rel

    suite_constants = {
        "script/test_validation_suite.py": "TESTS",
        "script/test_development_suite.py": "SUITES",
        "script/test_action_validation_suite.py": "TESTS",
        "script/test_btd_suite.py": "TESTS",
        "script/test_spid_suite.py": "SUITES",
        "script/test_pty_mirror_remote_suite.py": "TESTS",
    }
    for rel, constant in suite_constants.items():
        assert rel in inventory, rel
        assert (ROOT / rel).exists(), rel
        entries = _literal_string_sequence(ROOT / rel, constant)
        assert entries, f"{rel} {constant} is empty"
        for entry in entries:
            assert (ROOT / entry).exists(), f"{rel} points at missing test: {entry}"

    suite_reachable = set(suite_constants)
    for rel, constant in suite_constants.items():
        suite_reachable.update(_literal_string_sequence(ROOT / rel, constant))
    inventory_mentioned = {
        path.relative_to(ROOT).as_posix()
        for path in script_tests
        if path.relative_to(ROOT).as_posix() in inventory or path.name in inventory
    }
    orphan_tests = sorted(path.relative_to(ROOT).as_posix() for path in script_tests)
    orphan_tests = [rel for rel in orphan_tests if rel not in suite_reachable and rel not in inventory_mentioned]
    assert not orphan_tests, "test files are neither suite-reachable nor documented: " + ", ".join(orphan_tests)

    for live_test in [
        "script/test_lighting_key_runtime.py",
        "script/test_vial_protocol.py",
        "script/test_vialrgb_protocol.py",
        "script/test_vialrgb_persistence.py",
        "script/test_vial_unlock_runtime.py",
    ]:
        assert live_test in inventory, live_test

    print("ok: test inventory document is current")


if __name__ == "__main__":
    main()
