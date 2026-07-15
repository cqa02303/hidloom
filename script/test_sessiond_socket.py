#!/usr/bin/env python3
"""Socket-level smoke test for the minimal sessiond server."""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from sessiond.protocol import (  # noqa: E402
    TYPE_PTY_KEY_INPUT,
    TYPE_POLL_PTY_OUTPUT,
    TYPE_PTY_STATUS,
    TYPE_START_PTY_MIRROR,
    TYPE_STOP_PTY_MIRROR,
    encode_message,
    make_message,
    start_pty_mirror_message,
)
from sessiond.sessiond import SessiondService, _interrupt_prompt_tail  # noqa: E402


async def _read_until(
    reader: asyncio.StreamReader,
    message_type: str,
    *,
    timeout: float = 2.0,
    contains: str = "",
    active: bool | None = None,
) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        line = await asyncio.wait_for(reader.readline(), timeout=deadline - asyncio.get_running_loop().time())
        if not line:
            break
        payload = json.loads(line.decode())
        if payload.get("type") != message_type:
            continue
        if contains and contains not in str(payload.get("text", "")):
            continue
        if active is not None and payload.get("active") is not active:
            continue
        if payload.get("type") == message_type:
            return payload
    raise AssertionError(f"sessiond response {message_type!r} not received")


async def _poll_until(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    message_type: str,
    *,
    contains: str | None = None,
    active: bool | None = None,
    attempts: int = 40,
) -> dict:
    last: dict = {}
    for _ in range(attempts):
        writer.write(encode_message(make_message(TYPE_POLL_PTY_OUTPUT)))
        await writer.drain()
        try:
            last = await _read_until(reader, message_type, contains=contains, active=active, timeout=0.5)
        except TimeoutError:
            await asyncio.sleep(0.025)
            continue
        if contains is None or contains in str(last.get("text", "")):
            return last
        await asyncio.sleep(0.025)
    raise AssertionError(f"sessiond poll response {message_type!r} not received: {last!r}")


async def _read_status_reason(reader: asyncio.StreamReader, reason: str) -> dict:
    deadline = asyncio.get_running_loop().time() + 2.0
    while asyncio.get_running_loop().time() < deadline:
        status = await _read_until(reader, "pty_status", timeout=deadline - asyncio.get_running_loop().time())
        if status.get("reason") == reason:
            return status
    raise AssertionError(f"sessiond status reason {reason!r} not received")


async def _run() -> None:
    assert _interrupt_prompt_tail("old output\npi@host:~/repo $ ") == "\r\npi@host:~/repo $ "
    assert _interrupt_prompt_tail("old output\nroot@host:/repo# ") == "\r\nroot@host:/repo# "
    assert _interrupt_prompt_tail("old output\npi@host:~/repo $ \n") == "\r\npi@host:~/repo $ "
    assert (
        _interrupt_prompt_tail("old output\n\x1b[01;32mpi@host\x1b[00m:\x1b[01;34m~ $\x1b[00m \n")
        == "\r\n\x1b[01;32mpi@host\x1b[00m:\x1b[01;34m~ $\x1b[00m "
    )
    assert _interrupt_prompt_tail("old output\nnot a prompt") == ""

    with tempfile.TemporaryDirectory(prefix="sessiond-test-") as tmpdir:
        socket_path = str(Path(tmpdir) / "sessiond.sock")
        service = SessiondService(socket_path)
        await service.start()
        writer = None
        try:
            reader, writer = await asyncio.open_unix_connection(socket_path)
            start = start_pty_mirror_message(command="/bin/sh")
            assert start["type"] == TYPE_START_PTY_MIRROR
            writer.write(encode_message(start))
            await writer.drain()

            status = await _read_until(reader, "pty_status")
            assert status["active"] is True
            assert status["reason"] == "started"
            assert status["rows"] == 35
            assert status["columns"] == 120
            assert isinstance(status["pid"], int)

            writer.write(encode_message({"type": TYPE_PTY_KEY_INPUT, "bytes_hex": b"printf SOCK_OK\\n\n".hex()}))
            await writer.drain()
            text = await _poll_until(reader, writer, "pty_text_stream", contains="SOCK_OK")
            assert "SOCK_OK" in text["text"], text

            writer.write(encode_message({"type": TYPE_PTY_KEY_INPUT, "bytes_hex": "not-hex"}))
            await writer.drain()
            error = await _read_status_reason(reader, "error")
            assert error["active"] is True
            assert error["reason"] == "error"
            assert "hex" in error["error"].lower(), error

            writer.write(encode_message({"type": TYPE_PTY_KEY_INPUT, "bytes_hex": b"printf STILL_OK\\n\n".hex()}))
            await writer.drain()
            recovered = await _poll_until(reader, writer, "pty_text_stream", contains="STILL_OK")
            assert "STILL_OK" in recovered["text"], recovered

            writer.write(
                encode_message(
                    {
                        "type": TYPE_PTY_KEY_INPUT,
                        "bytes_hex": b"sleep 0.35; echo LATE_PROMPT\n".hex(),
                    }
                )
            )
            await writer.drain()
            delayed = await _poll_until(reader, writer, "pty_text_stream", contains="LATE_PROMPT")
            assert "LATE_PROMPT" in delayed["text"], delayed

            writer.write(encode_message({"type": TYPE_PTY_KEY_INPUT, "bytes_hex": b"exit\n".hex()}))
            await writer.drain()
            final = await _poll_until(reader, writer, "pty_status", active=False)
            assert final["active"] is False
            assert final["reason"] == "exit:0"
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            await service.close()

    with tempfile.TemporaryDirectory(prefix="sessiond-test-") as tmpdir:
        socket_path = str(Path(tmpdir) / "sessiond.sock")
        service = SessiondService(socket_path)
        await service.start()
        writer = None
        try:
            reader, writer = await asyncio.open_unix_connection(socket_path)
            writer.write(encode_message(start_pty_mirror_message(command="/bin/sh")))
            await writer.drain()
            await _read_until(reader, "pty_status", active=True)

            raw_reason = "manual\nstop:" + "x" * 120
            writer.write(encode_message(make_message(TYPE_STOP_PTY_MIRROR, reason=raw_reason)))
            await writer.drain()
            stopped = await _read_until(reader, "pty_status", active=False)
            assert "\n" not in stopped["reason"], stopped
            assert stopped["reason"].startswith("manual stop:")
            assert len(stopped["reason"]) == 80
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            await service.close()

    with tempfile.TemporaryDirectory(prefix="sessiond-test-") as tmpdir:
        socket_path = str(Path(tmpdir) / "sessiond.sock")
        service = SessiondService(socket_path)
        await service.start()
        writer = None
        try:
            reader, writer = await asyncio.open_unix_connection(socket_path)
            writer.write(encode_message(start_pty_mirror_message(command="/definitely/missing/pty-mirror-shell")))
            await writer.drain()
            error = await _read_until(reader, "pty_status", active=False)
            assert error["reason"] == "error"
            assert "missing" in error["error"] or "No such file" in error["error"], error

            writer.write(encode_message(start_pty_mirror_message(command="/bin/sh")))
            await writer.drain()
            recovered = await _read_until(reader, "pty_status", active=True)
            assert recovered["reason"] == "started"
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            await service.close()

    with tempfile.TemporaryDirectory(prefix="sessiond-test-") as tmpdir:
        socket_path = str(Path(tmpdir) / "sessiond.sock")
        service = SessiondService(socket_path)
        await service.start()
        writer = None
        try:
            reader, writer = await asyncio.open_unix_connection(socket_path)
            writer.write(b'{"schema":"sessiond.protocol.v1","type":"pty_status","padding":"' + b"x" * 70000 + b'"}\n')
            await writer.drain()
            error = await _read_until(reader, "pty_status", active=False)
            assert error["reason"] == "error"
            assert "too large" in error["error"], error

            writer.write(encode_message(make_message(TYPE_PTY_STATUS)))
            await writer.drain()
            status = await _read_until(reader, "pty_status", active=False)
            assert status["reason"] == "idle"
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            await service.close()

    with tempfile.TemporaryDirectory(prefix="sessiond-test-") as tmpdir:
        socket_path = str(Path(tmpdir) / "sessiond.sock")
        service = SessiondService(socket_path)
        await service.start()
        writer = None
        try:
            reader, writer = await asyncio.open_unix_connection(socket_path)
            writer.write(encode_message(start_pty_mirror_message(command="/bin/sh -c 'exit 7'")))
            await writer.drain()
            await _read_until(reader, "pty_status", active=True)
            await asyncio.sleep(0.05)
            writer.write(encode_message(make_message(TYPE_PTY_STATUS)))
            await writer.drain()
            final = await _read_until(reader, "pty_status", active=False)
            assert final["reason"] == "exit:7"
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            await service.close()

    with tempfile.TemporaryDirectory(prefix="sessiond-test-") as tmpdir:
        socket_path = Path(tmpdir) / "sessiond.sock"
        socket_path.write_text("not a socket", encoding="utf-8")
        service = SessiondService(str(socket_path))
        try:
            try:
                await service.start()
            except RuntimeError as exc:
                assert "not a socket" in str(exc)
            else:
                raise AssertionError("sessiond must not unlink a non-socket path")
        finally:
            await service.close()
        assert socket_path.exists()


def main() -> None:
    if sys.platform == "cygwin":
        print("skip: asyncio Unix socket client hangs on this Cygwin/MSYS runtime")
        return
    asyncio.run(_run())
    print("ok: sessiond socket starts PTY, streams text, and exits")


if __name__ == "__main__":
    main()
