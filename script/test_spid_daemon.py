#!/usr/bin/env python3
"""Smoke tests for spid daemon defaults and disabled mode."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from spid.spid import DEFAULT_BACKEND, DEFAULT_ENABLED, SpidServer, main_async, parse_bool  # noqa: E402
from spid.backend import MockMouseSensorBackend, build_backend  # noqa: E402
from socket_test_helpers import assert_socket_mode  # noqa: E402


async def main_async_test() -> None:
    assert DEFAULT_ENABLED is False
    assert DEFAULT_BACKEND == "none"
    assert parse_bool(None, default=False) is False
    assert parse_bool(None, default=True) is True
    assert parse_bool("true") is True
    assert parse_bool("enabled") is True
    assert parse_bool("0") is False
    assert parse_bool("disabled") is False
    try:
        parse_bool("maybe")
    except ValueError as exc:
        assert "invalid boolean" in str(exc)
    else:
        raise AssertionError("invalid bool should fail")

    # Even with SPID_ENABLED=true, backend=none must not create a daemon socket.
    old_env = dict(os.environ)
    old_argv = sys.argv[:]
    with tempfile.TemporaryDirectory() as tmpdir:
        socket_path = os.path.join(tmpdir, "spid.sock")
        try:
            os.environ["SPID_ENABLED"] = "true"
            os.environ["SPID_BACKEND"] = "none"
            os.environ["SPID_EVENTS_SOCK"] = socket_path
            sys.argv = ["spid"]
            await main_async()
            assert not os.path.exists(socket_path)
        finally:
            os.environ.clear()
            os.environ.update(old_env)
            sys.argv = old_argv

    # Constructing a server with the default backend must not require hardware,
    # but main_async intentionally avoids this path when backend=none.
    with tempfile.TemporaryDirectory() as tmpdir:
        socket_path = os.path.join(tmpdir, "spid.sock")
        server = SpidServer(socket_path=socket_path, backend=build_backend("none"), poll_hz=10)
        await server.start()
        try:
            assert os.path.exists(socket_path)
            assert_socket_mode(Path(socket_path), 0o660)
            assert server.backend.name == "none"
        finally:
            await server.stop()
        assert not os.path.exists(socket_path)

    # Mock backend remains available for plumbing tests when explicitly enabled.
    mock = MockMouseSensorBackend(dx=2, dy=-1)
    server = SpidServer(socket_path=os.path.join(tempfile.gettempdir(), "spid-test-unused.sock"), backend=mock)
    await mock.init()
    event = await mock.read_motion()
    assert event.dx == 2
    assert event.dy == -1
    await mock.close()

    print("ok: spid daemon")


def main() -> None:
    asyncio.run(main_async_test())


if __name__ == "__main__":
    main()
