#!/usr/bin/env python3
"""Regression checks for logicd socket environment overrides."""
from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))

from logicd import logicd  # noqa: E402


def main() -> None:
    old_matrix = os.environ.get("LOGICD_MATRIX_SOCKET")
    old_ctrl = os.environ.get("LOGICD_CTRL_SOCKET")
    old_delegate = os.environ.get("LOGICD_DELEGATE_SOCKET")
    old_matrix_tap = os.environ.get("LOGICD_MATRIX_TAP_SOCKET")
    try:
        os.environ["LOGICD_MATRIX_SOCKET"] = "none"
        assert logicd._socket_from_settings({"socket": "/tmp/original.sock"}, "socket", "/tmp/default.sock", "LOGICD_MATRIX_SOCKET") is None

        os.environ["LOGICD_MATRIX_SOCKET"] = "/tmp/override.sock"
        assert (
            logicd._socket_from_settings({"socket": "/tmp/original.sock"}, "socket", "/tmp/default.sock", "LOGICD_MATRIX_SOCKET")
            == "/tmp/override.sock"
        )

        os.environ.pop("LOGICD_MATRIX_SOCKET", None)
        assert (
            logicd._socket_from_settings({"socket": "/tmp/original.sock"}, "socket", "/tmp/default.sock", "LOGICD_MATRIX_SOCKET")
            == "/tmp/original.sock"
        )

        os.environ["LOGICD_CTRL_SOCKET"] = "disabled"
        assert logicd._socket_from_settings({}, "ctrl_socket", "/tmp/ctrl.sock", "LOGICD_CTRL_SOCKET") is None

        os.environ["LOGICD_DELEGATE_SOCKET"] = "/tmp/delegate.sock"
        assert (
            logicd._socket_from_settings({}, "delegate_socket", "/tmp/default-delegate.sock", "LOGICD_DELEGATE_SOCKET")
            == "/tmp/delegate.sock"
        )

        os.environ["LOGICD_MATRIX_TAP_SOCKET"] = "off"
        assert (
            logicd._socket_from_settings(
                {},
                "matrix_tap_socket",
                "/tmp/matrix_tap_events.sock",
                "LOGICD_MATRIX_TAP_SOCKET",
            )
            is None
        )

        os.environ.pop("LOGICD_MATRIX_TAP_SOCKET", None)
        assert (
            logicd._socket_from_settings(
                {},
                "matrix_tap_socket",
                "/tmp/matrix_tap_events.sock",
                "LOGICD_MATRIX_TAP_SOCKET",
            )
            == "/tmp/matrix_tap_events.sock"
        )
    finally:
        if old_matrix is None:
            os.environ.pop("LOGICD_MATRIX_SOCKET", None)
        else:
            os.environ["LOGICD_MATRIX_SOCKET"] = old_matrix
        if old_ctrl is None:
            os.environ.pop("LOGICD_CTRL_SOCKET", None)
        else:
            os.environ["LOGICD_CTRL_SOCKET"] = old_ctrl
        if old_delegate is None:
            os.environ.pop("LOGICD_DELEGATE_SOCKET", None)
        else:
            os.environ["LOGICD_DELEGATE_SOCKET"] = old_delegate
        if old_matrix_tap is None:
            os.environ.pop("LOGICD_MATRIX_TAP_SOCKET", None)
        else:
            os.environ["LOGICD_MATRIX_TAP_SOCKET"] = old_matrix_tap

    print("ok: logicd socket environment overrides")


if __name__ == "__main__":
    main()
