#!/usr/bin/env python3
"""Regression test for logicd sessiond client auto-start."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.sessiond_client import SessiondPtyMirrorClient  # noqa: E402


async def _run() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.chmod(tmp, 0o777)
        socket_path = Path(tmp) / "sessiond.sock"
        log_path = Path(tmp) / "sessiond.log"
        client = SessiondPtyMirrorClient(
            str(socket_path),
            auto_start=True,
            repo_root=str(ROOT),
            idle_exit_sec=0.2,
            log_path=str(log_path),
        )

        started = await client.start(command="bash --noprofile --norc", source="autostart_test")
        assert started["ok"] is True, started
        assert any(item.get("active") is True for item in started["responses"]), started
        assert socket_path.is_socket()

        stopped = await client.stop(reason="autostart_test")
        assert stopped["ok"] is True, stopped

        for _ in range(30):
            if not socket_path.exists():
                break
            await asyncio.sleep(0.1)
        assert not socket_path.exists(), log_path.read_text(encoding="utf-8", errors="replace")

    with tempfile.TemporaryDirectory() as tmp:
        os.chmod(tmp, 0o777)
        socket_path = Path(tmp) / "sessiond.sock"
        unwritable = Path(tmp) / "unwritable"
        unwritable.mkdir()
        os.chmod(unwritable, 0o500)
        client = SessiondPtyMirrorClient(
            str(socket_path),
            auto_start=True,
            repo_root=str(ROOT),
            idle_exit_sec=0.2,
            log_path=str(unwritable / "sessiond.log"),
        )
        try:
            started = await client.start(command="bash --noprofile --norc", source="autostart_no_log_test")
            assert started["ok"] is True, started
            await client.stop(reason="autostart_no_log_test")
        finally:
            os.chmod(unwritable, 0o700)


def main() -> None:
    asyncio.run(_run())
    print("ok: logicd sessiond client auto-starts sessiond and exits idle")


if __name__ == "__main__":
    main()
