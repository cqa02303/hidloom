#!/usr/bin/env python3
"""Checks for the standard keyboard HID sender helper."""
from __future__ import annotations

import importlib.util
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "script" / "send_standard_keyboard_report.py"
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from usbd.hid_report_broker import decode_hid_report_request  # noqa: E402


def _load_module():
    spec = importlib.util.spec_from_file_location("send_standard_keyboard_report", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> None:
    module = _load_module()
    press, release = module._reports_for_action("KC_HENKAN", report_id=1)
    assert press == bytes.fromhex("0100008a0000000000")
    assert release == bytes.fromhex("010000000000000000")

    press, release = module._reports_for_action("KC_HENKAN", report_id=None)
    assert press == bytes.fromhex("00008a0000000000")
    assert release == bytes(8)

    press, release = module._reports_for_action("KC_MUHENKAN", report_id=1)
    assert press == bytes.fromhex("0100008b0000000000")
    assert release == bytes.fromhex("010000000000000000")

    press, release = module._reports_for_action("KC_KANA", ["KC_LALT"], report_id=1)
    assert press == bytes.fromhex("010400880000000000")
    assert release == bytes.fromhex("010000000000000000")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "KC_KANA", "--modifier", "KC_LALT", "--dry-run"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.splitlines() == ["010400880000000000", "010000000000000000"]

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "KC_KANA", "--modifier", "KC_LALT", "--dry-run", "--no-report-id"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.splitlines() == ["0400880000000000", "0000000000000000"]

    with tempfile.NamedTemporaryFile() as tmp:
        subprocess.run(
            [sys.executable, str(SCRIPT), "KC_LANG2", "--device", tmp.name, "--hold-sec", "0"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert Path(tmp.name).read_bytes() == bytes.fromhex("010000910000000000010000000000000000")

    with tempfile.TemporaryDirectory() as tmpdir:
        socket_path = str(Path(tmpdir) / "usbd_hid_reports.sock")
        receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        receiver.settimeout(2.0)
        try:
            receiver.bind(socket_path)
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "KC_LANG2",
                    "--transport",
                    "socket",
                    "--socket",
                    socket_path,
                    "--hold-sec",
                    "0",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            frames = [receiver.recv(64), receiver.recv(64)]
        finally:
            receiver.close()
        requests = [decode_hid_report_request(frame) for frame in frames]
        assert [request.payload for request in requests] == [
            bytes.fromhex("0000910000000000"),
            bytes(8),
        ]
        assert "canonical_reports=['0000910000000000', '0000000000000000']" in result.stdout

    print("ok: standard keyboard HID sender helper")


if __name__ == "__main__":
    main()
