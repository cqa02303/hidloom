#!/usr/bin/env python3
"""Regression tests for SessiondPtyMirrorClient text profile planning."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.pty_terminal_text import WINDOWS_TERMINAL_WSL_CAT_PROFILE  # noqa: E402
import logicd.sessiond_client as sessiond_client  # noqa: E402
from logicd.sessiond_client import SessiondPtyMirrorClient  # noqa: E402


def main() -> None:
    editor_client = SessiondPtyMirrorClient("/tmp/not-used.sock")
    first_editor = editor_client.build_text_plans_for_stream("\x1b[2J\x1b[HPWD\r\n")
    second_editor = editor_client.build_text_plans_for_stream("NEXT\r\n")
    assert sum(1 for plan in first_editor if plan.get("receiver") is True) == 0, first_editor
    assert sum(1 for plan in second_editor if plan.get("receiver") is True) == 0, second_editor
    assert first_editor[0]["wrapper"] == "text_editor_startup_ime_off", first_editor
    assert first_editor[0]["taps"][0]["key"] == "KC_LANG2", first_editor
    assert any(plan.get("wrapper") == "text_editor_direct_input" for plan in first_editor), first_editor
    assert any("csi_sequence_stripped" in plan.get("stripped_reasons", []) for plan in first_editor), first_editor
    assert all(plan.get("wrapper") != "text_editor_startup_ime_off" for plan in second_editor), second_editor

    cat_client = SessiondPtyMirrorClient(
        "/tmp/not-used.sock",
        host_profile=WINDOWS_TERMINAL_WSL_CAT_PROFILE,
    )
    first_cat = cat_client.build_text_plans_for_stream("\x1b[2J\x1b[HPWD\r\n")
    second_cat = cat_client.build_text_plans_for_stream("NEXT\r\n")
    assert sum(1 for plan in first_cat if plan.get("receiver") is True) == 1, first_cat
    assert sum(1 for plan in second_cat if plan.get("receiver") is True) == 0, second_cat
    assert any(plan.get("wrapper") == "direct_hid_ansi" for plan in first_cat), first_cat

    async def never_connect(_socket_path: str):
        await asyncio.Event().wait()

    async def check_connect_timeout() -> None:
        original_connect = sessiond_client.asyncio.open_unix_connection
        sessiond_client.asyncio.open_unix_connection = never_connect
        try:
            client = SessiondPtyMirrorClient("/tmp/hanging-sessiond.sock", read_timeout=0.01)
            result = await client.status()
        finally:
            sessiond_client.asyncio.open_unix_connection = original_connect
        assert result["ok"] is False
        assert result["responses"] == []
        assert result["text_plans"] == []
        assert "connect timeout" in result["error"]

    asyncio.run(check_connect_timeout())

    print("ok: sessiond client text profiles plan editor output by default and cat receiver on opt-in")


if __name__ == "__main__":
    main()
