#!/usr/bin/env python3
"""SPI mouse sensor daemon.

The implementation is hardware-safe by default:
- default is disabled / backend=none, so boards without SPI mouse sensors do not need spid
- even if SPID_ENABLED=true is set accidentally, backend=none exits before opening a socket
- mock backend works without SPI hardware when explicitly requested
- PAW3805EK is implemented as an explicit Linux spidev polling backend
- output is JSON Lines over a Unix socket for easy inspection
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
from pathlib import Path

from .backend import MouseSensorBackend, build_backend, is_backend_disabled
from .protocol import StatusEvent, encode_event

DEFAULT_SOCKET = "/tmp/spi_events.sock"
DEFAULT_BACKEND = "none"
DEFAULT_ENABLED = False
DEFAULT_POLL_HZ = 125.0

log = logging.getLogger("spid")


def parse_bool(value: str | bool | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled", ""}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


class SpidServer:
    """Broadcast motion events from one mouse sensor backend to Unix socket clients."""

    def __init__(
        self,
        *,
        socket_path: str = DEFAULT_SOCKET,
        socket_mode: int = 0o660,
        backend: MouseSensorBackend | None = None,
        poll_hz: float = DEFAULT_POLL_HZ,
        drop_zero_motion: bool = True,
    ) -> None:
        self.socket_path = socket_path
        self.socket_mode = socket_mode
        self.backend = backend or build_backend(DEFAULT_BACKEND)
        self.poll_hz = max(1.0, float(poll_hz))
        self.drop_zero_motion = bool(drop_zero_motion)
        self._server: asyncio.AbstractServer | None = None
        self._clients: set[asyncio.StreamWriter] = set()
        self._poll_task: asyncio.Task | None = None

    async def start(self) -> None:
        path = Path(self.socket_path)
        if path.exists():
            path.unlink()
        await self.backend.init()
        self._server = await asyncio.start_unix_server(self._handle_client, path=self.socket_path)
        os.chmod(self.socket_path, self.socket_mode)
        self._poll_task = asyncio.create_task(self._poll_loop())
        log.info("spid listening on %s backend=%s poll_hz=%.1f", self.socket_path, self.backend.name, self.poll_hz)

    async def serve_forever(self) -> None:
        if self._server is None:
            await self.start()
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        for writer in list(self._clients):
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
        self._clients.clear()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        try:
            await self.backend.close()
        finally:
            try:
                os.unlink(self.socket_path)
            except FileNotFoundError:
                pass

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._clients.add(writer)
        log.info("client connected")
        try:
            await self._send(writer, StatusEvent(sensor=self.backend.name, ok=True, msg="connected"))
            while await reader.read(1):
                pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.debug("client error: %s", exc)
        finally:
            self._clients.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            log.info("client disconnected")

    async def _poll_loop(self) -> None:
        interval = 1.0 / self.poll_hz
        while True:
            try:
                event = await self.backend.read_motion()
                if not (self.drop_zero_motion and event.is_zero()):
                    await self._broadcast(event)
            except Exception as exc:
                log.warning("sensor read failed: %s", exc)
                await self._broadcast(StatusEvent(sensor=self.backend.name, ok=False, msg=str(exc)))
                await asyncio.sleep(1.0)
            await asyncio.sleep(interval)

    async def _broadcast(self, event) -> None:
        for writer in list(self._clients):
            await self._send(writer, event)

    async def _send(self, writer: asyncio.StreamWriter, event) -> None:
        try:
            writer.write(encode_event(event))
            if writer.transport.get_write_buffer_size() > 4096:
                await writer.drain()
        except OSError:
            self._clients.discard(writer)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SPI mouse sensor daemon")
    parser.add_argument("--enabled", default=os.environ.get("SPID_ENABLED", str(DEFAULT_ENABLED).lower()), help="Enable spid runtime. Default is false for boards without SPI mouse sensors.")
    parser.add_argument("--socket", default=os.environ.get("SPID_EVENTS_SOCK", DEFAULT_SOCKET))
    parser.add_argument("--socket-mode", default=os.environ.get("SPID_SOCKET_MODE", "660"))
    parser.add_argument("--backend", default=os.environ.get("SPID_BACKEND", DEFAULT_BACKEND), choices=("none", "mock", "PAW3805EK"))
    parser.add_argument("--poll-hz", type=float, default=float(os.environ.get("SPID_POLL_HZ", str(DEFAULT_POLL_HZ))))
    parser.add_argument("--log-level", default=os.environ.get("SPID_LOG_LEVEL", "INFO"))
    return parser.parse_args()


async def main_async() -> None:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        enabled = parse_bool(args.enabled, default=DEFAULT_ENABLED)
    except ValueError as exc:
        raise SystemExit(str(exc))
    if not enabled:
        log.info("spid disabled; exiting without opening SPI or socket")
        return
    if is_backend_disabled(args.backend):
        log.info("spid backend is not defined; exiting without opening SPI or socket")
        return
    try:
        socket_mode = int(str(args.socket_mode), 8)
    except ValueError:
        raise SystemExit(f"invalid socket mode: {args.socket_mode!r}")
    server = SpidServer(
        socket_path=args.socket,
        socket_mode=socket_mode,
        backend=build_backend(args.backend),
        poll_hz=args.poll_hz,
    )

    loop = asyncio.get_running_loop()

    def stop() -> None:
        for task in asyncio.all_tasks(loop):
            task.cancel()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop)
        except NotImplementedError:
            pass

    try:
        await server.serve_forever()
    except asyncio.CancelledError:
        pass
    finally:
        await server.stop()
        log.info("spid stopped")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
