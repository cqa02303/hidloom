"""Reusable connection helpers for logicd peer sockets."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)


async def reconnecting_unix_writer_loop(
    sock_path: str,
    *,
    get_writer: Any,
    set_writer: Any,
    on_connected: Any,
    label: str,
    retry_sec: float = 3.0,
) -> None:
    """Keep a Unix socket writer connected and call on_connected after reconnects."""
    while True:
        writer = get_writer()
        if writer is None:
            try:
                _, writer = await asyncio.open_unix_connection(sock_path)
                set_writer(writer)
                log.info("%s に接続: %s", label, sock_path)
                on_connected()
            except Exception as exc:
                log.debug("%s 接続失敗 (%.1f 秒後に再試行): %s", label, retry_sec, exc)
                await asyncio.sleep(retry_sec)
                continue
        elif writer.transport.is_closing():
            log.warning("%s との接続が切断されました", label)
            set_writer(None)
            continue
        else:
            try:
                writer.write(b'{"t":"ping"}\n')
                await asyncio.wait_for(writer.drain(), timeout=1.0)
            except Exception as exc:
                log.warning("%s との接続が切断されました: %s", label, exc)
                try:
                    writer.close()
                    await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
                except Exception:
                    pass
                set_writer(None)
                continue
        await asyncio.sleep(retry_sec)
