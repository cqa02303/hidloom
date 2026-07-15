#!/usr/bin/env python3
"""Vial protocol daemon."""
from __future__ import annotations

import asyncio
import logging
import os
import sys

from .protocol import VialProtocol

log = logging.getLogger("viald")

SOCKET_PATH = os.environ.get("VIALD_EVENTS_SOCK", "/tmp/viald_events.sock")
REPORT_SIZE = int(os.environ.get("VIALD_REPORT_SIZE", "32"))
PROTOCOL = VialProtocol()

_HELP = """usage: python3 -m viald.viald

Vial Raw HID protocol daemon.

Options:
  -h, --help    show this help and exit

Environment:
  LOG_LEVEL
  VIALD_EVENTS_SOCK
  VIALD_REPORT_SIZE
"""


async def _handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    peer = writer.get_extra_info("peername") or "<unix>"
    log.info("client connected: %s", peer)
    try:
        while True:
            packet = await reader.readexactly(REPORT_SIZE)
            writer.write(PROTOCOL.dispatch(packet))
            await writer.drain()
    except asyncio.IncompleteReadError:
        pass
    except ConnectionResetError:
        pass
    finally:
        log.info("client disconnected: %s", peer)
        try:
            writer.close()
            await writer.wait_closed()
        except OSError:
            pass


async def _run() -> None:
    try:
        os.unlink(SOCKET_PATH)
    except FileNotFoundError:
        pass

    server = await asyncio.start_unix_server(_handle_client, path=SOCKET_PATH)
    os.chmod(SOCKET_PATH, 0o666)
    log.info("listening on %s report_size=%d", SOCKET_PATH, REPORT_SIZE)
    async with server:
        await server.serve_forever()


def main() -> None:
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        print(_HELP.rstrip())
        return

    logging.basicConfig(
        level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO"), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(_run())


if __name__ == "__main__":
    main()
