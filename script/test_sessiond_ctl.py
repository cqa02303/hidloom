#!/usr/bin/env python3
"""CLI smoke test for tools/sessiond_ctl.py."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from sessiond.sessiond import SessiondService  # noqa: E402


def _run_tool(socket_path: str, *args: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "sessiond_ctl.py"), "--socket", socket_path, *args],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


def _run_tool_failed(socket_path: str, *args: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "sessiond_ctl.py"), "--socket", socket_path, *args],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode != 0, result.stdout
    return json.loads(result.stdout)


async def _run() -> None:
    with tempfile.TemporaryDirectory(prefix="sessiond-ctl-test-") as tmpdir:
        socket_path = str(Path(tmpdir) / "sessiond.sock")
        service = SessiondService(socket_path)
        await service.start()
        try:
            started = await asyncio.to_thread(
                _run_tool,
                socket_path,
                "start",
                "--shell",
                "/bin/sh",
                "--columns",
                "120",
                "--rows",
                "35",
            )
            assert started["ok"] is True
            assert started["responses"][0]["active"] is True
            assert started["responses"][0]["columns"] == 120
            assert started["responses"][0]["rows"] == 35

            status = await asyncio.to_thread(_run_tool, socket_path, "status")
            assert status["responses"][0]["active"] is True

            written = await asyncio.to_thread(_run_tool, socket_path, "write", "pwd", "--enter")
            assert written["ok"] is True
            assert any(item.get("type") == "pty_text_stream" for item in written["responses"]), written

            symbol = await asyncio.to_thread(_run_tool, socket_path, "write", "echo !", "--enter")
            assert symbol["ok"] is True
            assert any("!" in str(item.get("text", "")) for item in symbol["responses"]), symbol

            await asyncio.to_thread(_run_tool, socket_path, "write", "sleep 2", "--enter")
            interrupted = await asyncio.to_thread(
                _run_tool,
                socket_path,
                "key",
                "KC_C",
                "--modifier",
                "KC_LCTL",
            )
            assert interrupted["ok"] is True
            interrupt_status = next(item for item in interrupted["responses"] if item.get("type") == "pty_status")
            assert interrupt_status["reason"] == "interrupt"
            assert interrupt_status["clear_output_queue"] is True
            assert interrupt_status["output_discarded"] is True

            resumed = await asyncio.to_thread(_run_tool, socket_path, "write", "echo ok", "--enter")
            assert resumed["ok"] is True
            assert any("ok" in str(item.get("text", "")) for item in resumed["responses"]), resumed

            await asyncio.to_thread(_run_tool, socket_path, "stop", "--reason", "restart_for_line_edit_smoke")
            restarted = await asyncio.to_thread(
                _run_tool,
                socket_path,
                "start",
                "--shell",
                "bash --noprofile --norc",
                "--columns",
                "120",
                "--rows",
                "35",
            )
            assert restarted["ok"] is True

            await asyncio.to_thread(_run_tool, socket_path, "write", "echo k")
            await asyncio.to_thread(_run_tool, socket_path, "key", "KC_LEFT")
            inserted = await asyncio.to_thread(_run_tool, socket_path, "write", "o", "--enter")
            assert inserted["ok"] is True
            assert any("ok" in str(item.get("text", "")) for item in inserted["responses"]), inserted

            await asyncio.to_thread(_run_tool, socket_path, "write", "echo okk")
            await asyncio.to_thread(_run_tool, socket_path, "key", "KC_LEFT")
            await asyncio.to_thread(_run_tool, socket_path, "key", "KC_DEL")
            deleted = await asyncio.to_thread(_run_tool, socket_path, "key", "KC_ENTER")
            assert deleted["ok"] is True
            assert any("ok" in str(item.get("text", "")) for item in deleted["responses"]), deleted

            rejected = await asyncio.to_thread(_run_tool_failed, socket_path, "write", "あ", "--enter")
            assert rejected["ok"] is False
            assert "ASCII" in rejected["error"]

            too_long = await asyncio.to_thread(_run_tool_failed, socket_path, "write", "x" * 4097)
            assert too_long["ok"] is False
            assert "4096" in too_long["error"]

            bad_key = await asyncio.to_thread(_run_tool_failed, socket_path, "key", "KC_あ")
            assert bad_key["ok"] is False
            assert "ASCII" in bad_key["error"]

            long_key = await asyncio.to_thread(_run_tool_failed, socket_path, "key", "KC_" + "X" * 80)
            assert long_key["ok"] is False
            assert "64" in long_key["error"]

            many_modifiers_args = ["key", "KC_A"]
            for index in range(9):
                many_modifiers_args.extend(["--modifier", f"KC_LSFT_{index}"])
            many_modifiers = await asyncio.to_thread(_run_tool_failed, socket_path, *many_modifiers_args)
            assert many_modifiers["ok"] is False
            assert "8" in many_modifiers["error"]

            stopped = await asyncio.to_thread(_run_tool, socket_path, "stop", "--reason", "test_stop")
            assert stopped["responses"][0]["active"] is False
            assert stopped["responses"][0]["reason"] == "test_stop"
        finally:
            await service.close()


def main() -> None:
    if sys.platform == "cygwin":
        print("skip: asyncio Unix socket client hangs on this Cygwin/MSYS runtime")
        return
    asyncio.run(_run())
    print("ok: sessiond_ctl can start, query, and stop a PTY mirror session")


if __name__ == "__main__":
    main()
