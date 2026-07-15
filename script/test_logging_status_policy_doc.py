#!/usr/bin/env python3
"""Regression checks for logging/status policy documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_STATUS_FIELDS = [
    "output.logicd_outputs_env",
    "output.runtime_mode",
    "output.output_target",
    "output.display_label",
    "output.runtime_mode_label",
    "output.output_target_label",
    "btd.runtime.host_connected",
    "btd.runtime.service_registered",
    "btd.runtime.advertising_registered",
    "btd.runtime.stuck_reconnect_recoveries",
    "ledd_direct_frame.accepted_frames",
    "ledd_direct_frame.applied_frames",
    "ledd_direct_frame.ignored_frames",
    "ledd_direct_frame.direct_frame_active",
    "ledd_direct_frame.rejected_frames",
    "ledd_direct_frame.producer_connects",
    "ledd_direct_frame.producer_disconnects",
]


def main() -> None:
    policy = (ROOT / "docs" / "policy" / "logging-status-policy.md").read_text(encoding="utf-8")
    status_api = (ROOT / "daemon" / "http" / "system_api.py").read_text(encoding="utf-8")
    status_js = (ROOT / "daemon" / "http" / "static" / "status_panel.js").read_text(encoding="utf-8")
    httpd_py = (ROOT / "daemon" / "http" / "httpd.py").read_text(encoding="utf-8")
    logicd_sockets = (ROOT / "daemon" / "logicd" / "sockets.py").read_text(encoding="utf-8")
    logicd_ctrl_keymap = (ROOT / "daemon" / "logicd" / "ctrl_keymap.py").read_text(encoding="utf-8")

    for field in REQUIRED_STATUS_FIELDS:
        assert f"`{field}`" in policy, field

    assert "success log" not in policy.lower()
    assert "status_panel.js" in policy
    assert "system_api.py" in policy
    assert "_HttpAccessLogger" in policy
    assert "`/api/keymap/active` / `/api/matrix`" in policy
    assert "output.display_label" in policy
    assert "USB" in status_js and "BT" in status_js and "Pi" in status_js
    assert "display_label" in status_api
    assert "accepted_frames" in status_api
    assert "applied_frames" in status_api
    assert '_QUIET_POLLING_PATHS = {"/api/status", "/api/keymap/active", "/api/matrix"}' in httpd_py
    assert "_TRACE_LEVEL = 5" in logicd_sockets
    assert 'log.log(_TRACE_LEVEL, "Ctrl client connected: %s", peer)' in logicd_sockets
    assert 'log.log(_TRACE_LEVEL, "Ctrl client disconnected: %s", peer)' in logicd_sockets
    assert 'log.log(_TRACE_LEVEL, "ctrl G: keymap sent (%d layers)", len(layers))' in logicd_ctrl_keymap
    assert 'log.log(_TRACE_LEVEL, "ctrl ACTIVE: active layers sent")' in logicd_ctrl_keymap
    assert 'log.log(_TRACE_LEVEL, "ctrl K: matrix pressed state sent (%d keys)", len(ctx.pressed_matrix))' in logicd_ctrl_keymap
    print("ok: logging/status policy document is current")


if __name__ == "__main__":
    main()
