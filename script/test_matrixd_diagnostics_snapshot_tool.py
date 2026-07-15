#!/usr/bin/env python3
"""Static checks for the matrixd diagnostics snapshot helper."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import matrixd_diagnostics_snapshot as diag  # noqa: E402


def main() -> None:
    assert "matrixd" in diag.DEFAULT_SERVICES
    assert "logicd" in diag.DEFAULT_SERVICES
    assert diag.DEFAULT_KEY_SOCKET == "/tmp/key_events.sock"
    assert diag.DEFAULT_LEDD_SOCKET == "/tmp/ledd_events.sock"

    ps_cmd = diag.ps_command()
    assert ps_cmd[:3] == ["ps", "-o", "pid,ni,pri,rtprio,pcpu,pmem,rss,comm,args"]
    assert "matrixd" in ps_cmd

    hang_cmd = diag.journal_filter_command(diag.HANG_HINT_PATTERN, since="10 minutes ago")
    assert "blocked for more than" in hang_cmd[-1]
    assert "--since" in hang_cmd[-1]

    args = argparse.Namespace(
        duration=1.0,
        key_socket="/tmp/key_events.sock",
        ledd_socket="/tmp/ledd_events.sock",
    )
    report = diag.render_report(
        args=args,
        commands=[
            diag.CommandResult(
                title="matrixd priority",
                command=["systemctl", "show", "matrixd"],
                returncode=0,
                stdout="CPUSchedulingPriority=99\n",
                stderr="",
                elapsed_sec=0.01,
            ),
            diag.CommandResult(
                title="previous boot shutdown/restart hints",
                command=diag.journal_hint_command(boot="-1"),
                returncode=0,
                stdout="2026-06-02T23:31:58+09:00 logicd[1]: シャットダウン要求を受信しました (SW90)\n",
                stderr="",
                elapsed_sec=0.02,
            ),
            diag.CommandResult(
                title="thread wait snapshot",
                command=diag.process_filter_command("ps -eLo pid,tid,wchan:32,comm,args", "matrixd|logicd"),
                returncode=0,
                stdout="123 124 ep_poll logicd python3 daemon/logicd/logicd.py\n",
                stderr="",
                elapsed_sec=0.02,
            )
        ],
        key_result=diag.KeyMonitorResult(packets=2, valid_packets=2, samples=["50070000", "52070000"]),
        ledd_result=diag.LineMonitorResult(messages=1, key_messages=0, samples=['{"t":"mode","mode":"gadget"}']),
        ctrl_snapshots={
            "led_state": {"result": "ok", "mode": 40, "v": 160},
            "active_layers": {"t": "ACTIVE", "layers": [0]},
            "pressed_matrix": {"t": "K", "pressed": []},
        },
        files=[
            {"path": "config/default/matrixd.json", "exists": True, "size": 2, "sha256": "abc", "text": "{}"},
            {"path": "/etc/systemd/system/logicd.service", "exists": True, "size": 3, "sha256": "def", "text": "[Service]"},
            {"path": "/mnt/p3/keymap.json", "exists": True, "error": "permission denied"},
        ],
    )
    assert "# matrixd Diagnostics Snapshot" in report
    assert "key_event_count: `2`" in report
    assert "CPUSchedulingPriority=99" in report
    assert "previous boot shutdown/restart hints" in report
    assert "SW90" in report
    assert "thread wait snapshot" in report
    assert "pressed_matrix" in report
    assert "config/default/matrixd.json" in report
    assert "/etc/systemd/system/logicd.service" in report
    assert "/mnt/p3/keymap.json" in report
    assert "permission denied" in report

    readme = (ROOT / "tools" / "README.md").read_text(encoding="utf-8")
    assert "matrixd_diagnostics_snapshot.py" in readme
    assert "/mnt/p3/matrixd-diagnostics" in readme
    print("ok: matrixd diagnostics snapshot helper is documented")


if __name__ == "__main__":
    main()
