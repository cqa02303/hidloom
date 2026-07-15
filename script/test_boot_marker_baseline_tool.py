#!/usr/bin/env python3
"""Regression checks for the boot marker baseline helper."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import boot_marker_baseline as boot  # noqa: E402


def main() -> None:
    assert "hidloom-usb-gadget.service" in boot.DEFAULT_UNITS
    assert "logicd.service" in boot.DEFAULT_UNITS
    assert "logicd-companion.service" in boot.DEFAULT_UNITS
    assert "matrixd.service" in boot.DEFAULT_UNITS
    assert "usbd.service" in boot.DEFAULT_UNITS
    assert "hidloom-hidd.service" in boot.DEFAULT_UNITS
    assert "hidloom-uidd.service" in boot.DEFAULT_UNITS
    assert "hidloom-outputd.service" in boot.DEFAULT_UNITS
    assert "hidloom-logicd-core.service" in boot.DEFAULT_UNITS
    assert "NetworkManager.service" in boot.DEFAULT_UNITS
    assert "ssh.service" in boot.DEFAULT_UNITS
    assert "hidloom-network-late.service" in boot.DEFAULT_UNITS
    assert "/tmp/usbd_hid_reports.sock" in boot.DEFAULT_SOCKET_PATHS
    assert "/tmp/uidd_reports.sock" in boot.DEFAULT_SOCKET_PATHS
    assert "/tmp/hidloom_output_reports.sock" in boot.DEFAULT_SOCKET_PATHS
    assert "/tmp/hidloom_output_ctrl.sock" in boot.DEFAULT_SOCKET_PATHS
    assert "/tmp/matrix_events_shadow.sock" in boot.DEFAULT_SOCKET_PATHS
    assert "/run/hidloom/outputd-status.json" in boot.DEFAULT_STATUS_PATHS
    assert "/run/hidloom/uidd-status.json" in boot.DEFAULT_STATUS_PATHS
    assert "/run/hidloom/logicd-core-status.json" in boot.DEFAULT_STATUS_PATHS

    marker = boot.parse_systemctl_show(
        "logicd.service",
        "\n".join(
            [
                "ActiveState=active",
                "SubState=running",
                "ExecMainStartTimestampMonotonic=1234000",
                "ActiveEnterTimestampMonotonic=2345000",
            ]
        ),
    )
    assert marker.unit == "logicd.service"
    assert marker.active_state == "active"
    assert marker.sub_state == "running"
    assert marker.exec_start_sec == 1.234
    assert marker.active_enter_sec == 2.345

    known = boot.classify_journal_marker(
        "[   15.621301] <keyboard-host> matrixd[611]: logicd に接続しました: /tmp/matrix_events.sock"
    )
    assert known is not None
    assert known.kind == "input-ready"
    assert known.label == "matrixd connected to logic owner"
    assert known.confidence == "known"

    hidd_known = boot.classify_journal_marker(
        "[   13.205073] <keyboard-host> systemd[1]: Started hidloom-hidd.service - CQA02303v5 native HID report broker (hidloom-hidd)."
    )
    assert hidd_known is not None
    assert hidd_known.kind == "hid-broker"
    assert hidd_known.label == "hidd broker active"

    outputd_known = boot.classify_journal_marker(
        "[   14.181437] <keyboard-host> systemd[1]: Started hidloom-outputd.service - CQA02303v5 native HID report output router (hidloom-outputd)."
    )
    assert outputd_known is not None
    assert outputd_known.kind == "output-router"

    uidd_known = boot.classify_journal_marker(
        "[   14.164758] <keyboard-host> systemd[1]: Started hidloom-uidd.service - CQA02303v5 native uinput report sink (hidloom-uidd)."
    )
    assert uidd_known is not None
    assert uidd_known.kind == "uinput-sink"

    discovered = boot.classify_journal_marker(
        "[   21.000000] <keyboard-host> customd[777]: widget bus ready for boot probe"
    )
    assert discovered is not None
    assert discovered.kind == "journal-discovered"
    assert discovered.confidence == "discovered"

    result = boot.CommandResult(
        title="boot journal marker candidates",
        command=["journalctl", "-b"],
        returncode=0,
        stdout="\n".join(
            [
                "[   15.621301] <keyboard-host> matrixd[611]: logicd に接続しました: /tmp/matrix_events.sock",
                "[   21.000000] <keyboard-host> customd[777]: widget bus ready for boot probe",
            ]
        ),
        stderr="",
        elapsed_sec=0.0,
    )
    hidg_result = boot.CommandResult(
        title="hidg devices",
        command=["python", "glob:/dev/hidg*"],
        returncode=0,
        stdout="/dev/hidg0 mode=660 uid=0 gid=999\n",
        stderr="",
        elapsed_sec=0.0,
    )
    socket_snapshot = boot.SocketSnapshot(
        path="/tmp/logicd_core_ctrl.sock",
        exists=True,
        is_socket=True,
        mode="660",
        uid=0,
        gid=0,
        error="",
    )
    status_snapshot = boot.StatusSnapshot(
        path="/run/hidloom/logicd-core-status.json",
        exists=True,
        valid_json=True,
        schema="logicd-core.status.v1",
        summary="schema=logicd-core.status.v1, process=False, output_enabled=False, state.pressed_matrix=0",
        raw='{"schema":"logicd-core.status.v1","output_enabled":false}',
        error="",
    )
    report = boot.render_report(
        [marker],
        [result, hidg_result],
        include_http_status=False,
        sockets=[socket_snapshot],
        statuses=[status_snapshot],
    )
    assert "# Boot Marker Baseline" in report
    assert "http_status: `skipped`" in report
    assert "## Readiness Timeline" in report
    assert "matrixd connected to logic owner" in report
    assert "discovered journal candidate" in report
    assert "| logicd.service | active | running | 1.234 | 2.345 |" in report
    assert "## Boot-Critical Socket Snapshots" in report
    assert "| `/tmp/logicd_core_ctrl.sock` | true | true | 660 | 0 | 0 |  |" in report
    assert "## Status Snapshots" in report
    assert "logicd-core.status.v1" in report
    assert "## Raw Command Results" in report
    assert "### hidg devices" in report
    assert "/dev/hidg0" in report
    assert "USB HID gadget configured" in boot.JOURNAL_GREP_PATTERN
    assert "Started hidloom-hidd" in boot.JOURNAL_GREP_PATTERN
    assert "Started hidloom-outputd" in boot.JOURNAL_GREP_PATTERN
    assert "logicd boot marker" in boot.JOURNAL_GREP_PATTERN
    assert "接続" in boot.JOURNAL_GREP_PATTERN

    readme = (ROOT / "tools" / "README.md").read_text(encoding="utf-8")
    assert "boot_marker_baseline.py" in readme
    assert "usable keyboard" in readme

    plan = (ROOT / "docs" / "ops" / "buildroot-fast-boot-experiment.md").read_text(encoding="utf-8")
    assert "tools/boot_marker_baseline.py" in plan
    assert "hidg ready" in plan
    assert "usable keyboard" in plan

    print("ok: boot marker baseline helper")


if __name__ == "__main__":
    main()
