#!/usr/bin/env python3
"""Smoke-test install artifacts do not depend on the development account path."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD_REPO_ROOT = "/home/USERNAME/hidloom"
OLD_PI_REPO_ROOT = "/home/pi/hidloom"
NEW_REPO_ROOT = "/home/example/hidloom"

SERVICE_FILES = [
    "system/systemd/hidloom-bluetooth-unblock.service",
    "system/systemd/hidloom-touch-panel-profile.service",
    "system/systemd/hidloom-usb-gadget.service",
    "system/systemd/i2cd.service",
    "system/systemd/logicd.service",
    "system/systemd/logicd-companion.service",
    "system/systemd/matrixd.service",
    "system/systemd/ledd.service",
    "system/systemd/ledd-shutdown.service",
    "system/systemd/httpd.service",
    "system/systemd/viald.service",
    "system/systemd/usbd.service",
    "system/systemd/hidloom-hidd.service",
    "system/systemd/hidloom-logicd-core.service",
    "system/systemd/hidloom-late-services.service",
    "system/systemd/hidloom-late-services.timer",
    "system/systemd/hidloom-network-late.service",
    "system/systemd/hidloom-network-late.timer",
    "system/systemd/btd.service",
]

SCRIPT_FILES = [
    "config/default/script/KC_SH2.sh",
    "config/default/script/KC_SH4.sh",
    "config/default/script/KC_SH7.sh",
    "config/default/script/KC_SH8.sh",
]

TLS_HELPER = "script/ensure_httpd_tls_cert.sh"


def render_unit(text: str) -> str:
    return text.replace("@HIDLOOM_REPO_ROOT@", NEW_REPO_ROOT).replace(OLD_REPO_ROOT, NEW_REPO_ROOT)


def main() -> None:
    setup = (ROOT / "system" / "install" / "setup_fresh_rpi.sh").read_text(encoding="utf-8")
    setup_wrapper = (ROOT / "setup_fresh_rpi.sh").read_text(encoding="utf-8")
    selector = (ROOT / "script" / "select_touch_panel_profile.py").read_text(encoding="utf-8")
    assert "system/install/setup_fresh_rpi.sh" in setup_wrapper
    assert "install_bluetooth_hid_dropins" in setup
    assert "--no-bluetooth" in setup
    assert "--no-matrixd" in setup
    assert "--no-peripherals" in setup
    assert "--touch-panel-only" in setup
    assert "--touch-panel-profile" in setup
    assert "NO_BLUETOOTH=0" in setup
    assert "NO_MATRIXD=0" in setup
    assert "NO_PERIPHERALS=0" in setup
    assert "dtoverlay=disable-bt" in setup
    assert "rfkill block bluetooth" in setup
    assert "install_touch_panel_profile" in setup
    assert "select_touch_panel_profile.py" in setup
    assert "hidloom-touch-panel-profile.service" in setup
    assert "osoyoo-4.3" in selector
    assert "waveshare-8.8" in selector
    assert "LOGICD_MATRIX_ROWS=16" in setup
    assert "LOGICD_MATRIX_COLS=16" in setup
    assert "i2cd.service ledd.service ledd-shutdown.service" in setup
    assert "Environment=BTD_BACKEND=bluez" in setup
    assert "Environment=BTD_GATT_SECURITY=encrypt" in setup
    assert "Environment=BTD_ADVERTISING_MODE=pairing" in setup
    assert "Environment=BTD_PAIRING_AGENT=DisplayYesNo" in setup
    assert "Environment=BT_PAIRING_DISCOVERABLE=0" in setup
    assert "Environment=BTD_DISCONNECT_MONITOR_INTERVAL=2" in setup
    assert "Environment=BTD_STUCK_RECONNECT_POLLS=3" in setup
    assert "Environment=LOGICD_OUTPUTS=auto" in setup
    assert "configure_systemd_watchdog" in setup
    assert "RuntimeWatchdogSec=off" in setup
    assert "configure_system_logging" in setup
    assert "Storage=persistent" in setup
    assert "sysstat-collect.timer" in setup
    assert "sysstat-summary.timer" in setup
    assert "sysstat-rotate.timer" in setup
    assert 'systemctl enable "${units[@]}"' in setup
    enable_block = setup.split('systemctl enable "${units[@]}"', 1)[0].split("local units=", 1)[1]
    assert "hidloom-touch-panel-profile.service" not in enable_block
    assert "hidloom-late-services.timer" in enable_block
    assert "hidloom-network-late.timer" in enable_block
    assert "httpd.service" not in enable_block
    assert "viald.service" not in enable_block
    assert "hidloom-late-services.timer" in setup
    assert "hidloom-network-late.timer" in setup
    assert "systemctl_disable_now matrixd.service hidloom-outputd.service hidloom-uidd.service hidloom-logicd-core.service logicd-companion.service hidloom-touch-panel-profile.service hidloom-late-services.service httpd.service viald.service" in setup
    assert "hidloom-bluetooth-unblock.service" in setup
    assert "btd.service" in setup
    assert "spid.service" not in setup.split("systemctl enable", 1)[1].split("install_bluetooth_hid_dropins", 1)[0]
    assert "python3-aiohttp" in setup
    assert "python3-dbus-next" in setup
    assert "python3-numpy" in setup
    assert "python3-opencv" in setup
    assert "Skipping matrixd build" in setup
    assert "build_c_helpers" in setup
    assert "tools/hidloom_send/build.sh" in setup
    assert "tools/hidloom_hidd/build.sh" in setup
    assert "apply_board_profile_if_requested" in setup
    assert "script/apply_board_profile.py" in setup
    assert "restore_repo_user_ownership" in setup
    assert '"$REPO_ROOT/tools/hidloom_send/.build"' in setup
    assert '"$REPO_ROOT/tools/hidloom_hidd/target"' in setup
    assert '"$REPO_ROOT/daemon/matrixd/matrixd"' in setup

    hidd_unit = (ROOT / "system/systemd/hidloom-hidd.service").read_text(encoding="utf-8")
    assert "ExecStart=@HIDLOOM_REPO_ROOT@/bin/hidloom-hidd" in hidd_unit
    assert "Conflicts=usbd.service" in hidd_unit
    assert "Environment=USBD_HID_REPORT_SOCKET=/tmp/usbd_hid_reports.sock" in hidd_unit

    httpd_unit = (ROOT / "system/systemd/httpd.service").read_text(encoding="utf-8")
    assert "ExecStartPre=@HIDLOOM_REPO_ROOT@/script/ensure_httpd_tls_cert.sh" in httpd_unit
    assert "Environment=HTTPD_PORT=443" in httpd_unit
    assert "Environment=HTTPD_TLS_CERT=/mnt/p3/httpd.crt" in httpd_unit
    assert "Environment=HTTPD_TLS_KEY=/mnt/p3/httpd.key" in httpd_unit
    assert "Environment=HTTPD_PRIVATE_ONLY=1" in httpd_unit
    assert "Environment=HTTPD_SHUTDOWN_TIMEOUT_SECONDS=0.75" in httpd_unit
    assert "Environment=HTTPD_WS_CLOSE_TIMEOUT_SECONDS=0.25" in httpd_unit
    assert "TimeoutStopSec=4" in httpd_unit
    assert "SendSIGKILL=yes" in httpd_unit

    tls_helper = (ROOT / TLS_HELPER).read_text(encoding="utf-8")
    assert "openssl req" in tls_helper
    assert "subjectAltName=$alt_names" in tls_helper
    assert "chmod 0600" in tls_helper
    assert "HTTPD_TLS_ALT_NAMES" in tls_helper

    release_checklist = (ROOT / "RELEASE_CHECKLIST.md").read_text(encoding="utf-8")
    fresh_install = (ROOT / "FRESH_INSTALL.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "hidloom-usb-gadget" in release_checklist
    assert "hidloom-logicd-core" in release_checklist
    assert "logicd-companion" in release_checklist
    assert "<user>@<keyboard-ip>" in fresh_install
    assert "<user>@<keyboard-ip>" in readme
    assert "spid.service` は PAW sensor 搭載前提ではない" in release_checklist
    for name, text in {
        "FRESH_INSTALL.md": fresh_install,
        "RELEASE_CHECKLIST.md": release_checklist,
        "README.md": readme,
    }.items():
        assert OLD_REPO_ROOT not in text, name
        assert OLD_PI_REPO_ROOT not in text, name

    for rel_path in SERVICE_FILES:
        path = ROOT / rel_path
        raw = path.read_text(encoding="utf-8")
        rendered = render_unit(raw)
        assert OLD_REPO_ROOT not in rendered, rel_path
        assert "@HIDLOOM_REPO_ROOT@" not in rendered, rel_path
        if Path(rel_path).name not in {"hidloom-bluetooth-unblock.service", "hidloom-late-services.timer", "hidloom-network-late.timer"}:
            assert NEW_REPO_ROOT in rendered, rel_path
    bt_unblock_unit = (ROOT / "system" / "systemd" / "hidloom-bluetooth-unblock.service").read_text(encoding="utf-8")
    assert "Before=bluetooth.service btd.service" in bt_unblock_unit
    assert "/usr/sbin/rfkill unblock bluetooth" in bt_unblock_unit
    assert "RemainAfterExit=yes" in bt_unblock_unit

    for rel_path in SCRIPT_FILES:
        text = (ROOT / rel_path).read_text(encoding="utf-8")
        assert OLD_REPO_ROOT not in text, rel_path
        assert OLD_PI_REPO_ROOT not in text, rel_path
        assert "HIDLOOM_REPO_ROOT" in text, rel_path
    assert "/usr/lib/hidloom/tools/sessiond_ctl.py" in (
        ROOT / "config/default/script/KC_SH7.sh"
    ).read_text(encoding="utf-8")
    assert "/usr/lib/hidloom/tools/matrixd_diagnostics_snapshot.py" in (
        ROOT / "config/default/script/KC_SH8.sh"
    ).read_text(encoding="utf-8")

    print("ok: install artifacts are portable across repository owner accounts")


if __name__ == "__main__":
    main()
