"""Minimal sessiond socket server for PTY mirror M0."""
from __future__ import annotations

import argparse
import asyncio
import binascii
import contextlib
import logging
import os
from pathlib import Path
import re
import stat
from typing import Any

from .protocol import (
    DEFAULT_COLUMNS,
    DEFAULT_ROWS,
    DEFAULT_SESSIOND_SOCKET,
    TYPE_PTY_KEY_INPUT,
    TYPE_POLL_PTY_OUTPUT,
    TYPE_PTY_STATUS,
    TYPE_START_PTY_MIRROR,
    TYPE_STOP_PTY_MIRROR,
    TYPE_WATCH_PTY_OUTPUT,
    decode_message,
    encode_message,
    make_message,
    pty_status_message,
)
from .pty_mirror import PtyMirrorSession, key_action_to_pty_bytes

log = logging.getLogger(__name__)

MAX_MESSAGE_BYTES = 64 * 1024
STREAM_READER_LIMIT = MAX_MESSAGE_BYTES * 2
_COMMAND_COMMIT_ACTIONS = frozenset({"KC_ENTER", "KC_ENT", "KC_RETURN"})
_ANSI_ESCAPE_RE = re.compile(
    r"(?:\x1b\][^\x07]*(?:\x07|\x1b\\))|(?:\x1b\[[0-?]*[ -/]*[@-~])"
)


class SessiondService:
    def __init__(self, socket_path: str = DEFAULT_SESSIOND_SOCKET) -> None:
        self.socket_path = socket_path
        self.server: asyncio.AbstractServer | None = None
        self.session: PtyMirrorSession | None = None
        self.last_exit_reason = "idle"
        self.seen_session = False

    async def start(self) -> None:
        path = Path(self.socket_path)
        if path.exists():
            mode = path.stat().st_mode
            if not stat.S_ISSOCK(mode):
                raise RuntimeError(f"sessiond socket path exists and is not a socket: {self.socket_path}")
            path.unlink()
        self.server = await asyncio.start_unix_server(
            self.handle_client,
            path=self.socket_path,
            limit=STREAM_READER_LIMIT,
        )
        os.chmod(self.socket_path, 0o666)
        log.info("sessiond listening on %s", self.socket_path)

    async def close(self) -> None:
        self.stop_session("service_close")
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        with contextlib.suppress(FileNotFoundError):
            path = Path(self.socket_path)
            if stat.S_ISSOCK(path.stat().st_mode):
                path.unlink()

    async def serve_forever(self) -> None:
        if self.server is None:
            await self.start()
        assert self.server is not None
        async with self.server:
            await self.server.serve_forever()

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while line := await reader.readline():
                try:
                    if len(line) > MAX_MESSAGE_BYTES:
                        raise ValueError("sessiond message too large")
                    message = decode_message(line)
                except Exception as exc:
                    log.warning("sessiond message failed: %s", exc)
                    writer.write(encode_message(make_message(TYPE_PTY_STATUS, active=self.active, reason="error", error=str(exc))))
                    await writer.drain()
                    continue
                if message.get("type") == TYPE_WATCH_PTY_OUTPUT:
                    await self.watch_output(message, writer)
                    break
                try:
                    responses = await self.process_message(message)
                except Exception as exc:
                    log.warning("sessiond message failed: %s", exc)
                    responses = [make_message(TYPE_PTY_STATUS, active=self.active, reason="error", error=str(exc))]
                for response in responses:
                    writer.write(encode_message(response))
                try:
                    await writer.drain()
                except (BrokenPipeError, ConnectionResetError):
                    break
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def process_line(self, line: bytes) -> list[dict[str, Any]]:
        try:
            if len(line) > MAX_MESSAGE_BYTES:
                raise ValueError("sessiond message too large")
            message = decode_message(line)
            return await self.process_message(message)
        except Exception as exc:
            log.warning("sessiond message failed: %s", exc)
            return [make_message(TYPE_PTY_STATUS, active=self.active, reason="error", error=str(exc))]

    @property
    def active(self) -> bool:
        return bool(self.session is not None and self.session.active)

    async def process_message(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        self._finalize_exited_session()
        message_type = message.get("type")
        if message_type == TYPE_START_PTY_MIRROR:
            return await self.start_session(message)
        if message_type == TYPE_STOP_PTY_MIRROR:
            reason = _clean_reason(message.get("reason", "stop"), default="stop")
            self.stop_session(reason)
            return [pty_status_message(False, reason=reason)]
        if message_type == TYPE_PTY_KEY_INPUT:
            return await self.handle_key_input(message)
        if message_type == TYPE_POLL_PTY_OUTPUT:
            return await self.poll_output(message)
        if message_type == TYPE_PTY_STATUS:
            return [self.status_message()]
        raise ValueError(f"unsupported sessiond message type: {message_type!r}")

    async def start_session(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        if self.active:
            return [self.status_message(reason="already_active")]
        command = str(message.get("command", "bash") or "bash")
        rows = _bounded_int(message.get("rows", DEFAULT_ROWS), default=DEFAULT_ROWS, lower=1, upper=120)
        columns = _bounded_int(message.get("columns", DEFAULT_COLUMNS), default=DEFAULT_COLUMNS, lower=1, upper=240)
        session = PtyMirrorSession(command, rows=rows, columns=columns)
        session.start()
        self.session = session
        self.seen_session = True
        self.last_exit_reason = "started"
        responses = [self.status_message(reason="started")]
        text = await self._read_available_session_text(max_bytes=8192)
        if text:
            responses.append(make_message("pty_text_stream", text=text))
        return responses

    async def poll_output(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        self._finalize_exited_session()
        if not self.active or self.session is None:
            return [self.status_message()]
        max_bytes = _bounded_int(message.get("max_bytes", 8192), default=8192, lower=1, upper=65536)
        text = await self._read_available_session_text(max_bytes=max_bytes)
        responses: list[dict[str, Any]] = []
        if text:
            responses.append(make_message("pty_text_stream", text=text))
        if self.session is not None:
            await asyncio.to_thread(self.session.wait, timeout=0.0)
        if self._finalize_exited_session():
            responses.append(self.status_message())
        return responses or [self.status_message(reason="poll")]

    async def watch_output(self, message: dict[str, Any], writer: asyncio.StreamWriter) -> None:
        max_bytes = _bounded_int(message.get("max_bytes", 8192), default=8192, lower=1, upper=65536)
        interval_ms = _bounded_int(message.get("interval_ms", 25), default=25, lower=5, upper=1000)
        writer.write(encode_message(self.status_message(reason="watch")))
        await writer.drain()
        while True:
            self._finalize_exited_session()
            if not self.active or self.session is None:
                writer.write(encode_message(self.status_message()))
                await writer.drain()
                return
            text = await self._read_available_session_text(max_bytes=max_bytes)
            if text:
                writer.write(encode_message(make_message("pty_text_stream", text=text)))
                await writer.drain()
                continue
            await asyncio.sleep(interval_ms / 1000.0)

    async def handle_key_input(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.active or self.session is None:
            return [pty_status_message(False, reason="inactive")]

        written = 0
        input_bytes = b""
        if "bytes_hex" in message:
            try:
                input_bytes = binascii.unhexlify(str(message.get("bytes_hex", "")))
            except (binascii.Error, ValueError) as exc:
                raise ValueError("invalid bytes_hex payload") from exc
            written = self.session.write(input_bytes)
        else:
            action = str(message.get("action", ""))
            modifiers = message.get("modifiers", [])
            if not isinstance(modifiers, list):
                modifiers = []
            active_modifiers = [str(mod) for mod in modifiers]
            input_bytes = key_action_to_pty_bytes(
                action,
                is_press=bool(message.get("is_press", True)),
                active_modifiers=active_modifiers,
            )
            written = self.session.write(input_bytes)
            log.info(
                "sessiond PTY key input action=%s is_press=%s modifiers=%s written=%s",
                action,
                bool(message.get("is_press", True)),
                active_modifiers,
                written,
            )

        responses: list[dict[str, Any]] = []
        commits_command = self._message_commits_command(message)
        interrupts_command = b"\x03" in input_bytes
        if interrupts_command:
            signaled = False
            if self.session is not None:
                signaled = self.session.interrupt()
            discarded = await self._drain_session_text(timeout=0.35, max_bytes=65536)
            prompt_tail = _interrupt_prompt_tail(discarded)
            if not prompt_tail:
                extra = await self._drain_session_text(timeout=0.45, max_bytes=65536)
                if extra:
                    discarded += extra
                    prompt_tail = _interrupt_prompt_tail(discarded)
            discarded_len = max(0, len(discarded) - len(prompt_tail))
            log.info(
                "sessiond PTY interrupt discarded_output_len=%s prompt_tail_len=%s written=%s",
                discarded_len,
                len(prompt_tail),
                written,
            )
            if self.session is not None:
                await asyncio.to_thread(self.session.wait, timeout=0.05)
            finalized = self._finalize_exited_session()
            if prompt_tail and not finalized:
                responses.append(make_message("pty_text_stream", text=prompt_tail, written=written))
            if finalized:
                responses.append(self.status_message())
            else:
                responses.append(
                    make_message(
                        "pty_status",
                        active=self.active,
                        reason="interrupt",
                        output_discarded=True,
                        signal_sent=signaled,
                        discarded_text_length=discarded_len,
                        prompt_returned=bool(prompt_tail),
                        clear_output_queue=True,
                    )
                )
            return responses or [
                make_message(
                    "pty_status",
                    active=self.active,
                    reason="interrupt",
                    output_discarded=True,
                    signal_sent=signaled,
                    discarded_text_length=discarded_len,
                    prompt_returned=bool(prompt_tail),
                    clear_output_queue=True,
                )
            ]
        if commits_command and "bytes_hex" in message:
            text = await self._drain_session_text(timeout=0.35, max_bytes=65536)
            if text:
                responses.append(make_message("pty_text_stream", text=text, written=written))
        if self.session is not None:
            await asyncio.to_thread(self.session.wait, timeout=0.0)
        if self._finalize_exited_session():
            responses.append(self.status_message())
        return responses or [self.status_message(reason="input")]

    def _finalize_exited_session(self) -> bool:
        if self.session is None or self.session.active:
            return False
        code = self.session.wait(timeout=0.0)
        self.session.close()
        self.session = None
        self.last_exit_reason = f"exit:{code}"
        return True

    def status_message(self, *, reason: str | None = None) -> dict[str, Any]:
        rows = DEFAULT_ROWS
        columns = DEFAULT_COLUMNS
        pid = None
        if self.session is not None:
            rows = self.session.rows
            columns = self.session.columns
            if self.session.process is not None:
                pid = self.session.process.pid
        message = pty_status_message(self.active, reason=reason or self.last_exit_reason, rows=rows, columns=columns)
        if pid is not None:
            message["pid"] = pid
        return message

    def stop_session(self, reason: str) -> None:
        if self.session is not None:
            self.session.terminate()
            self.session = None
        self.last_exit_reason = _clean_reason(reason, default="stop")

    def _message_commits_command(self, message: dict[str, Any]) -> bool:
        if "bytes_hex" in message:
            try:
                data = binascii.unhexlify(str(message.get("bytes_hex", "")))
            except (binascii.Error, ValueError):
                return False
            return data.endswith((b"\r", b"\n"))
        return str(message.get("action", "")) in _COMMAND_COMMIT_ACTIONS and bool(message.get("is_press", True))

    async def _drain_session_text(self, *, timeout: float, max_bytes: int = 8192) -> str:
        if self.session is None:
            return ""
        return await asyncio.to_thread(self.session.read_text_until_quiet, timeout=timeout, max_bytes=max_bytes)

    async def _read_available_session_text(self, *, max_bytes: int = 8192) -> str:
        if self.session is None:
            return ""
        data = await asyncio.to_thread(self.session.read_available, timeout=0.0, max_bytes=max_bytes)
        if not data:
            return ""
        return data.decode("utf-8", errors="replace")


def _bounded_int(value: object, *, default: int, lower: int, upper: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(lower, min(upper, parsed))


def _clean_reason(value: object, *, default: str, max_len: int = 80) -> str:
    text = str(value or default).replace("\r", " ").replace("\n", " ").strip()
    if not text:
        text = default
    return text[:max(1, max_len)]


def _looks_like_ready_prompt(text: str) -> bool:
    stripped = _ANSI_ESCAPE_RE.sub("", str(text or "")).rstrip()
    return stripped.endswith("$") or stripped.endswith("#")


def _interrupt_prompt_tail(text: str) -> str:
    """Return only the final ready prompt after Ctrl-C, if one is visible."""
    if not text:
        return ""
    normalized = str(text).replace("\r\n", "\n").replace("\r", "\n")
    tail = next((line for line in reversed(normalized.split("\n")) if line.strip()), "")
    if not _looks_like_ready_prompt(tail):
        return ""
    return "\r\n" + tail


async def _amain() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", default=DEFAULT_SESSIOND_SOCKET)
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument(
        "--exit-when-idle-sec",
        type=float,
        default=0.0,
        help="exit after this many idle seconds once a PTY session has been used; 0 disables",
    )
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.INFO))
    service = SessiondService(args.socket)
    try:
        if args.exit_when_idle_sec > 0:
            await service.start()
            assert service.server is not None
            serve_task = asyncio.create_task(service.server.serve_forever())
            idle_task = asyncio.create_task(_wait_until_idle(service, idle_sec=args.exit_when_idle_sec))
            done, pending = await asyncio.wait({serve_task, idle_task}, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in pending:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            for task in done:
                await task
        else:
            await service.serve_forever()
    finally:
        await service.close()


async def _wait_until_idle(service: SessiondService, *, idle_sec: float) -> None:
    inactive_since: float | None = None
    while True:
        if service.active or not service.seen_session:
            inactive_since = None
        elif inactive_since is None:
            inactive_since = asyncio.get_running_loop().time()
        elif asyncio.get_running_loop().time() - inactive_since >= max(0.1, idle_sec):
            return
        await asyncio.sleep(0.2)


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
