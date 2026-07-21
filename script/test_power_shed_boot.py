#!/usr/bin/env python3
"""Static checks for boot-time power shedding."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    service = (ROOT / "system" / "systemd" / "hidloom-power-shed.service").read_text(encoding="utf-8")
    setup = (ROOT / "system" / "install" / "setup_fresh_rpi.sh").read_text(encoding="utf-8")
    setup_wrapper = (ROOT / "setup_fresh_rpi.sh").read_text(encoding="utf-8")
    power_script = (ROOT / "script" / "apply_power_shed.sh").read_text(encoding="utf-8")
    browser = (ROOT / "script" / "start_touch_panel_browser.sh").read_text(encoding="utf-8")
    logicd = (ROOT / "system" / "systemd" / "logicd.service").read_text(encoding="utf-8")
    companion = (ROOT / "system" / "systemd" / "logicd-companion.service").read_text(encoding="utf-8")
    core = (ROOT / "system" / "systemd" / "hidloom-logicd-core.service").read_text(encoding="utf-8")
    matrixd = (ROOT / "system" / "systemd" / "matrixd.service").read_text(encoding="utf-8")
    httpd = (ROOT / "system" / "systemd" / "httpd.service").read_text(encoding="utf-8")
    usbd = (ROOT / "system" / "systemd" / "usbd.service").read_text(encoding="utf-8")
    hidd = (ROOT / "system" / "systemd" / "hidloom-hidd.service").read_text(encoding="utf-8")
    viald = (ROOT / "system" / "systemd" / "viald.service").read_text(encoding="utf-8")
    late_service = (ROOT / "system" / "systemd" / "hidloom-late-services.service").read_text(encoding="utf-8")
    late_timer = (ROOT / "system" / "systemd" / "hidloom-late-services.timer").read_text(encoding="utf-8")
    network_late_service = (ROOT / "system" / "systemd" / "hidloom-network-late.service").read_text(encoding="utf-8")
    network_late_timer = (ROOT / "system" / "systemd" / "hidloom-network-late.timer").read_text(encoding="utf-8")

    assert "DefaultDependencies=no" in service
    assert "Before=multi-user.target" in service
    assert "Before=multi-user.target lightdm.service" in service
    assert "Before=multi-user.target hidloom-usb-gadget.service" not in service
    assert "logicd.service" not in service
    assert "usbd.service" not in service
    assert "Environment=HIDLOOM_POWER_CPU_MAX_KHZ=1000000" in service
    assert "script/apply_power_shed.sh" in service
    assert 'install_unit_from_repo "$REPO_ROOT/system/systemd/hidloom-power-shed.service"' in setup
    assert "hidloom-power-shed.service" in setup
    assert "system/install/setup_fresh_rpi.sh" in setup_wrapper
    assert "cloud-init-local.service" in setup
    assert "NetworkManager-wait-online.service" in setup
    assert "/etc/systemd/system.conf.d/90-hidloom-disable-watchdog.conf" in setup
    assert "/etc/systemd/journald.conf.d/90-hidloom-persistent.conf" in setup
    retired_owner = "c" + "qa" + "02303"
    assert f"90-{retired_owner}-" not in setup
    assert "find /etc/netplan /lib/netplan" in setup
    assert "chmod 600" in setup
    assert 'set_prefixed_line "$BOOT_CONFIG" "dtparam=audio=" "dtparam=audio=off"' in setup
    assert 'set_prefixed_line "$BOOT_CONFIG" "dtoverlay=vc4-kms-v3d" "dtoverlay=vc4-kms-v3d,noaudio"' in setup
    assert 'set_prefixed_line "$BOOT_CONFIG" "camera_auto_detect=" "camera_auto_detect=0"' in setup
    assert 'set_prefixed_line "$BOOT_CONFIG" "display_auto_detect=" "display_auto_detect=0"' in setup
    assert 'set_prefixed_line "$BOOT_CONFIG" "disable_splash=" "disable_splash=1"' in setup
    assert "detect_boot_cmdline" in setup
    assert "ensure_cmdline_csv_values" in setup
    assert "remove_cmdline_token" in setup
    assert 'ensure_cmdline_csv_values "$BOOT_CMDLINE" "module_blacklist" "snd_bcm2835,snd_soc_hdmi_codec"' in setup
    assert 'remove_cmdline_token "$BOOT_CMDLINE" "modules-load=dwc2,libcomposite"' in setup
    assert "hidloom-no-audio.conf" in setup
    assert "blacklist snd_bcm2835" in setup
    assert "blacklist snd_soc_hdmi_codec" in setup
    assert "alsa-restore.service" in setup
    assert "alsa-state.service" in setup
    assert "sound.target" in setup
    assert "plymouth-start.service" in setup
    assert "plymouth-quit-wait.service" in setup
    assert "After=network.target" not in logicd
    assert "DefaultDependencies=no" in logicd
    assert "After=local-fs.target systemd-journald.socket" in logicd
    assert "Before=basic.target multi-user.target" in logicd
    assert "ExecStart=/usr/bin/python3 -S -m logicd.logicd" in logicd
    assert "WantedBy=sysinit.target" in logicd
    assert "Wants=matrixd.service ledd.service" not in logicd
    assert "Environment=LOGICD_MATRIX_SOCKET=none" in companion
    assert "Environment=LOGICD_OUTPUTS=debug" in companion
    assert "Environment=LOGICD_USBD_HID_REPORT_BROKER=0" in companion
    assert "Environment=LOGICD_OUTPUTS=auto" not in companion
    assert "/tmp/matrix_events.sock" not in companion
    assert "LOGICD_CORE_MATRIX_SOCKET=/tmp/matrix_events.sock" in core
    assert "After=hidloom-outputd.service" in core
    assert "Wants=hidloom-outputd.service" in core
    assert "LOGICD_CORE_HID_REPORT_SOCKET=/tmp/hidloom_output_reports.sock" in core
    assert "LOGICD_CORE_OUTPUT_ENABLED=1" in core
    assert "Before=matrixd.service" in core
    assert "After=hidloom-logicd-core.service" in matrixd
    assert "Requires=hidloom-logicd-core.service" in matrixd
    assert "After=logicd.service" not in matrixd
    assert "After=network.target" not in httpd
    assert "After=logicd-companion.service" in httpd
    assert "Wants=logicd-companion.service" in httpd
    assert "Requires=viald.service" not in usbd
    assert "After=hidloom-usb-gadget.service viald.service" not in usbd
    assert "Environment=USBD_RAW_HID_BRIDGE_ENABLED=0" in usbd
    assert "Environment=USBD_HID_REPORT_SOCKET_ENABLED=1" in usbd
    assert "Before=usbd.service" not in viald
    assert "HIDLOOM_LATE_LEDD" not in late_service
    assert "HIDLOOM_LATE_BLUETOOTH=1" in late_service
    assert "systemctl start ledd.service" not in late_service
    assert "systemctl --no-block start hidloom-bluetooth-unblock.service btd.service" in late_service
    assert "systemctl --no-block start viald.service httpd.service" in late_service
    assert "systemctl start viald.service httpd.service" not in late_service
    assert "WantedBy=multi-user.target" not in late_service
    assert "OnBootSec=45s" in late_timer
    assert "Unit=hidloom-late-services.service" in late_timer
    assert 'install_unit_from_repo "$REPO_ROOT/system/systemd/hidloom-late-services.service"' in setup
    assert 'install_unit_from_repo "$REPO_ROOT/system/systemd/hidloom-late-services.timer"' in setup
    assert 'install_unit_from_repo "$REPO_ROOT/system/systemd/hidloom-network-late.service"' in setup
    assert 'install_unit_from_repo "$REPO_ROOT/system/systemd/hidloom-network-late.timer"' in setup
    assert "hidloom-late-services.timer" in setup
    assert "hidloom-network-late.timer" in setup
    assert "systemctl disable NetworkManager.service" not in setup
    assert "systemctl disable wpa_supplicant.service" not in setup
    assert "NetworkManager available for Wi-Fi recovery" in setup
    assert "hidloom-late-services.service.d/setup-options.conf" in setup
    assert "/usr/lib/systemd/system/ssh.service" in setup
    assert "/etc/systemd/system/ssh.service" in setup
    assert "After=nss-user-lookup.target auditd.service" in setup
    assert "s/^After=network.target nss-user-lookup.target auditd.service$/After=nss-user-lookup.target auditd.service/" in setup
    assert "/usr/lib/systemd/system/systemd-user-sessions.service" in setup
    assert "/etc/systemd/system/systemd-user-sessions.service" in setup
    assert "s/^After=remote-fs.target nss-user-lookup.target network.target home.mount$/After=remote-fs.target nss-user-lookup.target home.mount/" in setup
    assert "HIDLOOM_LATE_LEDD=" not in setup
    assert "HIDLOOM_LATE_BLUETOOTH=" in setup
    assert "i2cd.service ledd.service ledd-shutdown.service" in setup
    assert "compile_python_bytecode()" in setup
    assert "python3 -m compileall -q" in setup
    assert "$REPO_ROOT/daemon" in setup
    assert "$REPO_ROOT/__pycache__" in setup
    assert "$REPO_ROOT/tools/hidloom_usb_gadget_fast/build.sh" in setup
    assert "$REPO_ROOT/tools/hidloom_usb_gadget_fast/.build" in setup
    assert "systemctl --no-block start NetworkManager.service" in network_late_service
    assert "WantedBy=multi-user.target" not in network_late_service
    assert "OnBootSec=25s" in network_late_timer
    assert "WantedBy=timers.target" in network_late_timer
    assert "$REPO_ROOT/tools/hidloom_hidd/build.sh" in setup
    assert "$REPO_ROOT/tools/hidloom_hidd/target" in setup
    assert "$REPO_ROOT/tools/hidloom_uidd/build.sh" in setup
    assert "$REPO_ROOT/tools/hidloom_uidd/target" in setup
    assert "$REPO_ROOT/tools/hidloom_outputd/build.sh" in setup
    assert "$REPO_ROOT/tools/hidloom_outputd/target" in setup
    assert 'install_unit_from_repo "$REPO_ROOT/system/systemd/hidloom-hidd.service"' in setup
    assert 'install_unit_from_repo "$REPO_ROOT/system/systemd/hidloom-uidd.service"' in setup
    assert 'install_unit_from_repo "$REPO_ROOT/system/systemd/hidloom-outputd.service"' in setup
    assert "logicd.service.d/runtime-dependents.conf" in setup
    assert "dev-hidg0.device matrixd.service" in setup
    assert "systemctl_disable_now matrixd.service hidloom-outputd.service hidloom-uidd.service hidloom-logicd-core.service logicd-companion.service hidloom-touch-panel-profile.service hidloom-late-services.service httpd.service viald.service" in setup
    assert "systemctl_disable_now logicd.service hidloom-touch-panel-profile.service hidloom-late-services.service httpd.service viald.service" in setup

    assert "scaling_max_freq" in power_script
    assert "scaling_governor" in power_script
    assert "HIDLOOM_POWER_CPU_MAX_KHZ" in power_script
    assert "HIDLOOM_POWER_CPU_GOVERNOR" in power_script

    assert "HIDLOOM_TOUCH_PANEL_BROWSER_START_DELAY_SEC" in browser
    assert 'sleep "$start_delay"' in browser
    assert "HIDLOOM_TOUCH_PANEL_OUTPUT_TRANSFORM" in browser
    assert 'export XDG_RUNTIME_DIR="$runtime_dir"' in browser
    assert 'export WAYLAND_DISPLAY="$wayland_display"' in browser
    assert 'wlr-randr --output "$output_name" --transform "$output_transform"' in browser
    assert "HIDLOOM_TOUCH_PANEL_WINDOW_SIZE" in browser
    assert "HIDLOOM_TOUCH_PANEL_REMOTE_DEBUGGING_PORT" in browser
    assert "HIDLOOM_TOUCH_PANEL_REMOTE_DEBUGGING_ADDRESS" in browser
    assert 'remote_debugging_address="${HIDLOOM_TOUCH_PANEL_REMOTE_DEBUGGING_ADDRESS:-127.0.0.1}"' in browser
    assert "--remote-debugging-address=" in browser
    assert "--remote-debugging-port=" in browser
    assert "repair_kiosk_navigation" in browser
    assert "HIDLOOM_TOUCH_PANEL_REPAIR_ADDRESS" in browser
    assert "json_url = f\"http://{address}:{port}/json/list\"" in browser
    assert "HIDLOOM_TOUCH_PANEL_BROWSER_REPAIR_DELAY_SEC" in browser
    assert "HIDLOOM_TOUCH_PANEL_BROWSER_REPAIR_ATTEMPTS" in browser
    assert "HIDLOOM_TOUCH_PANEL_BROWSER_REPAIR_INTERVAL_SEC" in browser
    assert "Runtime.evaluate" in browser
    assert "bodyLength" in browser
    assert "actual_url == target_url and body_length > 0" in browser
    assert "Page.navigate" in browser
    assert "time.sleep(interval)" in browser
    assert "continue" in browser
    assert '"about:blank"' in browser
    assert '"chrome-error://"' in browser
    assert "--window-size=" in browser
    assert 'active_transform" == "90"' in browser
    assert 'window_size="${height},${width}"' in browser

    usb_gadget = (ROOT / "system" / "systemd" / "hidloom-usb-gadget.service").read_text(encoding="utf-8")
    assert "DefaultDependencies=no" in usb_gadget
    assert "After=tmp.mount systemd-remount-fs.service systemd-modules-load.service" in usb_gadget
    assert "WantedBy=sysinit.target" in usb_gadget
    assert "Environment=HIDLOOM_USB_GADGET_START_DELAY_SEC=0" in usb_gadget
    assert "Environment=HIDLOOM_USB_GADGET_SETUP_BACKEND=native" in usb_gadget
    assert "HIDLOOM_USB_GADGET_START_DELAY_SEC" in usb_gadget
    assert 'sleep "${HIDLOOM_USB_GADGET_START_DELAY_SEC:-1}"' in usb_gadget
    assert "modprobe libcomposite" in usb_gadget
    assert "ExecStart=@HIDLOOM_REPO_ROOT@/bin/hidloom-hidd" in hidd
    assert "DefaultDependencies=no" in hidd
    assert "Conflicts=usbd.service" in hidd
    assert "After=tmp.mount" in hidd
    assert "Before=shutdown.target" in hidd
    assert "Conflicts=shutdown.target" in hidd
    assert "Before=basic.target multi-user.target" in hidd
    assert "Before=logicd.service" not in hidd
    assert "WantedBy=sysinit.target" in hidd

    for early_runtime in (logicd, hidd, usb_gadget):
        assert "DefaultDependencies=no" in early_runtime
        assert "Before=shutdown.target" in early_runtime
        assert "Conflicts=shutdown.target" in early_runtime

    print("ok: boot power shedding service and kiosk delay are wired")


if __name__ == "__main__":
    main()
