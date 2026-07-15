#!/usr/bin/env python3
"""Regression checks for logicd-core active-owner systemd split."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    logicd_py = (ROOT / "daemon" / "logicd" / "logicd.py").read_text(encoding="utf-8")
    core_unit = (ROOT / "system" / "systemd" / "hidloom-logicd-core.service").read_text(encoding="utf-8")
    matrixd_unit = (ROOT / "system" / "systemd" / "matrixd.service").read_text(encoding="utf-8")
    companion_unit = (ROOT / "system" / "systemd" / "logicd-companion.service").read_text(encoding="utf-8")
    logicd_unit = (ROOT / "system" / "systemd" / "logicd.service").read_text(encoding="utf-8")
    ledd_unit = (ROOT / "system" / "systemd" / "ledd.service").read_text(encoding="utf-8")
    httpd_unit = (ROOT / "system" / "systemd" / "httpd.service").read_text(encoding="utf-8")
    late_unit = (ROOT / "system" / "systemd" / "hidloom-late-services.service").read_text(encoding="utf-8")
    touch_profile_unit = (ROOT / "system" / "systemd" / "hidloom-touch-panel-profile.service").read_text(encoding="utf-8")
    setup = (ROOT / "system" / "install" / "setup_fresh_rpi.sh").read_text(encoding="utf-8")

    assert "LOGICD_MATRIX_SOCKET" in logicd_py
    assert 'value.lower() in {"", "0", "false", "no", "none", "off", "disabled"}' in logicd_py
    assert "Matrix events socket disabled" in logicd_py
    assert "AsyncExitStack" in logicd_py

    assert "LOGICD_CORE_MATRIX_SOCKET=/tmp/matrix_events.sock" in core_unit
    assert "LOGICD_CORE_DELEGATE_SOCKET=/tmp/logicd_delegate_events.sock" in core_unit
    assert "LOGICD_CORE_OUTPUT_ENABLED=1" in core_unit
    assert "LOGICD_CORE_PREVIEW_LOG_PATH=" in core_unit
    assert "Before=matrixd.service" in core_unit
    assert "Before=logicd.service" not in core_unit
    assert "After=hidloom-hidd.service matrixd.service" not in core_unit

    assert "After=hidloom-logicd-core.service" in matrixd_unit
    assert "Requires=hidloom-logicd-core.service" in matrixd_unit
    assert "After=logicd.service" not in matrixd_unit
    assert "Requires=logicd.service" not in matrixd_unit

    assert "Environment=LOGICD_MATRIX_SOCKET=none" in companion_unit
    assert "Environment=LOGICD_DELEGATE_SOCKET=/tmp/logicd_delegate_events.sock" in companion_unit
    assert "Environment=LOGICD_CORE_KEY_EVENT_CTRL_SOCKET=/tmp/logicd_core_ctrl.sock" in companion_unit
    assert "Environment=LOGICD_OUTPUTS=debug" in companion_unit
    assert "Environment=LOGICD_USBD_HID_REPORT_BROKER=0" in companion_unit
    assert "Environment=LOGICD_OUTPUTS=auto" not in companion_unit
    assert "Environment=LOGICD_USBD_HID_REPORT_BROKER=1" not in companion_unit
    assert "ExecStartPre=/bin/rm -f /tmp/logicd_delegate_events.sock /tmp/ctrl_events.sock /tmp/ledd_events.sock /tmp/key_events.sock" in companion_unit
    assert "/tmp/matrix_events.sock" not in companion_unit
    assert "After=matrixd.service hidloom-logicd-core.service" in companion_unit

    assert "ExecStartPre=/bin/rm -f /tmp/matrix_events.sock" in logicd_unit
    assert "After=local-fs.target" in ledd_unit
    assert "logicd-companion.service" not in ledd_unit
    assert "After=logicd-companion.service" in httpd_unit
    assert "Wants=logicd-companion.service" in httpd_unit
    assert "After=logicd-companion.service hidloom-usb-gadget.service" in late_unit
    assert "Before=logicd.service logicd-companion.service httpd.service viald.service" in touch_profile_unit
    assert 'install_unit_from_repo "$REPO_ROOT/system/systemd/logicd-companion.service"' in setup
    assert "hidloom-logicd-core.service" in setup
    assert "logicd-companion.service" in setup
    assert "systemctl_disable_now logicd.service" in setup

    print("ok: logicd-core active-owner systemd split")


if __name__ == "__main__":
    main()
