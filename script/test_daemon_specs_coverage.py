#!/usr/bin/env python3
"""Check daemon detailed specs cover runtime daemons and native service helpers."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "docs" / "daemon" / "specs"

REQUIRED_SPEC_DIRS = {
    "btd",
    "hidd",
    "httpd",
    "i2cd",
    "ledd",
    "logicd",
    "logicd-core-rs",
    "matrixd",
    "outputd",
    "service-helpers",
    "sessiond",
    "spid",
    "uidd",
    "usb-gadget-fast",
    "usbd",
    "viald",
}

DAEMON_DIR_TO_SPEC = {
    "btd": "btd",
    "http": "httpd",
    "i2cd": "i2cd",
    "ledd": "ledd",
    "logicd": "logicd",
    "matrixd": "matrixd",
    "sessiond": "sessiond",
    "spid": "spid",
    "usbd": "usbd",
    "viald": "viald",
}

SYSTEMD_UNIT_TO_SPEC = {
    "btd.service": "btd",
    "hidloom-bluetooth-unblock.service": "service-helpers",
    "hidloom-hidd.service": "hidd",
    "hidloom-late-services.service": "service-helpers",
    "hidloom-logicd-core.service": "logicd-core-rs",
    "hidloom-network-late.service": "service-helpers",
    "hidloom-outputd.service": "outputd",
    "hidloom-power-shed.service": "service-helpers",
    "hidloom-touch-panel-profile.service": "service-helpers",
    "hidloom-uidd.service": "uidd",
    "hidloom-usb-gadget.service": "usb-gadget-fast",
    "httpd.service": "httpd",
    "i2cd.service": "i2cd",
    "ledd-shutdown.service": "service-helpers",
    "ledd.service": "ledd",
    "logicd-companion.service": "logicd",
    "logicd.service": "logicd",
    "matrixd.service": "matrixd",
    "spid.service": "spid",
    "usbd.service": "usbd",
    "viald.service": "viald",
}

TOOL_PATH_TO_SPEC = {
    "tools/hidloom_hidd": "hidd",
    "tools/hidloom_outputd": "outputd",
    "tools/hidloom_uidd": "uidd",
    "tools/hidloom_usb_gadget_fast": "usb-gadget-fast",
    "tools/hidloom_logicd_core": "logicd-core-rs",
}


def assert_spec_linked(readme: str, spec_name: str) -> None:
    link = f"[{spec_name}/README.md]({spec_name}/README.md)"
    assert link in readme, f"docs/daemon/specs/README.md should link {spec_name}/README.md"


def main() -> None:
    assert SPECS.exists(), "docs/daemon/specs should exist"
    specs_readme = (SPECS / "README.md").read_text(encoding="utf-8")
    audit_path = SPECS / "coverage-audit-2026-06-26.md"
    audit = audit_path.read_text(encoding="utf-8") if audit_path.is_file() else None
    risk_notes = (SPECS / "implementation-risk-notes.md").read_text(encoding="utf-8")
    daemon_readme = (ROOT / "docs" / "daemon" / "README.md").read_text(encoding="utf-8")
    validation_suite = (ROOT / "script" / "test_validation_suite.py").read_text(encoding="utf-8")
    inventory = (ROOT / "docs" / "ops" / "test-script-inventory.md").read_text(encoding="utf-8")

    actual_spec_dirs = {path.name for path in SPECS.iterdir() if path.is_dir()}
    assert REQUIRED_SPEC_DIRS <= actual_spec_dirs, (
        f"missing specs: {sorted(REQUIRED_SPEC_DIRS - actual_spec_dirs)}"
    )
    assert actual_spec_dirs <= REQUIRED_SPEC_DIRS, (
        f"unexpected specs: {sorted(actual_spec_dirs - REQUIRED_SPEC_DIRS)}"
    )

    for spec_name in sorted(REQUIRED_SPEC_DIRS):
        spec_readme = SPECS / spec_name / "README.md"
        assert spec_readme.exists(), f"{spec_name}/README.md should exist"
        assert_spec_linked(specs_readme, spec_name)
        if audit is not None:
            assert f"[{spec_name}/README.md]({spec_name}/README.md)" in audit, (
                f"coverage audit should link {spec_name}/README.md"
            )

    daemon_dirs = {
        path.name
        for path in (ROOT / "daemon").iterdir()
        if path.is_dir() and path.name != "__pycache__"
    }
    assert set(DAEMON_DIR_TO_SPEC) == daemon_dirs, (
        "daemon directory coverage mapping should be updated when daemons are added: "
        f"extra={sorted(set(DAEMON_DIR_TO_SPEC) - daemon_dirs)}, "
        f"missing={sorted(daemon_dirs - set(DAEMON_DIR_TO_SPEC))}"
    )
    for daemon_name, spec_name in DAEMON_DIR_TO_SPEC.items():
        assert (SPECS / spec_name / "README.md").exists(), daemon_name
        if audit is not None:
            assert f"`daemon/{daemon_name}`" in audit, (
                f"audit should mention daemon/{daemon_name}"
            )

    systemd_units = {
        path.name
        for path in (ROOT / "system" / "systemd").glob("*.service")
    }
    assert set(SYSTEMD_UNIT_TO_SPEC) == systemd_units, (
        "systemd unit coverage mapping should be updated when services are added: "
        f"extra={sorted(set(SYSTEMD_UNIT_TO_SPEC) - systemd_units)}, "
        f"missing={sorted(systemd_units - set(SYSTEMD_UNIT_TO_SPEC))}"
    )
    for unit_name, spec_name in SYSTEMD_UNIT_TO_SPEC.items():
        assert (SPECS / spec_name / "README.md").exists(), unit_name
        if audit is not None:
            assert f"`{unit_name}`" in audit, f"audit should mention {unit_name}"

    for tool_path, spec_name in TOOL_PATH_TO_SPEC.items():
        assert (ROOT / tool_path).exists(), tool_path
        assert (SPECS / spec_name / "README.md").exists(), tool_path
        if audit is not None:
            assert f"`{tool_path}`" in audit, f"audit should mention {tool_path}"

    for expected_phrase in [
        "hidloom-outputd",
        "Boot helper service",
        "legacy flag",
        "runtime keymap",
        "Raw HID / Vial",
    ]:
        assert expected_phrase in risk_notes, expected_phrase

    assert "specs/README.md" in daemon_readme
    assert "specs/implementation-risk-notes.md" in daemon_readme
    assert "script/test_daemon_specs_coverage.py" in validation_suite
    assert "script/test_daemon_specs_coverage.py" in inventory

    print("ok: daemon detailed specs cover daemons, native tools, and systemd services")


if __name__ == "__main__":
    main()
