"""Client-side helpers for logicd -> sessiond PTY mirror M0."""
from __future__ import annotations

import asyncio
from pathlib import Path
import os
import pwd
import logging
import subprocess
from typing import Any

from sessiond.protocol import (
    DEFAULT_COLUMNS,
    DEFAULT_ROWS,
    DEFAULT_SESSIOND_SOCKET,
    TYPE_PTY_KEY_INPUT,
    TYPE_POLL_PTY_OUTPUT,
    TYPE_PTY_STATUS,
    TYPE_PTY_TEXT_STREAM,
    TYPE_START_PTY_MIRROR,
    TYPE_STOP_PTY_MIRROR,
    TYPE_WATCH_PTY_OUTPUT,
    decode_message,
    encode_message,
    make_message,
    start_pty_mirror_message,
)

from .pty_terminal_text import (
    build_pty_terminal_receiver_plan,
    build_pty_terminal_startup_plan,
    build_pty_terminal_text_plans,
    normalize_pty_terminal_host_profile,
    pty_terminal_profile_uses_receiver,
    WINDOWS_TEXT_EDITOR_PROFILE,
)

log = logging.getLogger(__name__)


class SessiondPtyMirrorClient:
    """Small request/response client; logicd does not listen on a new socket."""

    def __init__(
        self,
        socket_path: str = DEFAULT_SESSIOND_SOCKET,
        *,
        read_timeout: float = 2.0,
        host_profile: str | None = None,
        auto_start: bool = False,
        repo_root: str | None = None,
        idle_exit_sec: float = 10.0,
        log_path: str = "/tmp/sessiond.log",
        sessiond_user: str | None = None,
    ) -> None:
        self.socket_path = socket_path
        self.read_timeout = read_timeout
        self.host_profile = normalize_pty_terminal_host_profile(host_profile)
        self.receiver_started = False
        self.auto_start = auto_start
        self.repo_root = str(repo_root or Path(__file__).resolve().parents[2])
        self.idle_exit_sec = idle_exit_sec
        self.log_path = log_path
        self.sessiond_user = sessiond_user

    async def start(
        self,
        *,
        command: str = "bash",
        columns: int = DEFAULT_COLUMNS,
        rows: int = DEFAULT_ROWS,
        source: str = "logicd",
    ) -> dict[str, Any]:
        self.receiver_started = False
        message = start_pty_mirror_message(command=command, columns=columns, rows=rows, source=source)
        result = await self.request(message)
        if result.get("ok") or not self.auto_start or result.get("responses"):
            return result
        log.info(
            "sessiond unavailable for start request; attempting auto-start socket=%s error=%s",
            self.socket_path,
            result.get("error"),
        )
        if not await self._ensure_sessiond_started():
            log.warning(
                "sessiond auto-start failed socket=%s repo_root=%s log_path=%s",
                self.socket_path,
                self.repo_root,
                self.log_path,
            )
            return result
        retry = await self.request(message)
        log.info(
            "sessiond start retry result ok=%s responses=%s error=%s",
            retry.get("ok"),
            [
                {
                    "type": item.get("type"),
                    "active": item.get("active"),
                    "reason": item.get("reason"),
                    "error": item.get("error"),
                }
                for item in retry.get("responses", [])
                if isinstance(item, dict)
            ],
            retry.get("error"),
        )
        return retry

    async def stop(self, *, reason: str = "logicd_stop") -> dict[str, Any]:
        try:
            return await self.request(make_message(TYPE_STOP_PTY_MIRROR, reason=reason))
        finally:
            self.receiver_started = False

    async def status(self) -> dict[str, Any]:
        return await self.request(make_message(TYPE_PTY_STATUS))

    async def poll_output(self, *, max_bytes: int = 8192) -> dict[str, Any]:
        return await self.request(make_message(TYPE_POLL_PTY_OUTPUT, max_bytes=max_bytes))

    async def watch_output(self, on_result: Any, *, max_bytes: int = 8192, interval_ms: int = 25) -> None:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(self.socket_path),
            timeout=max(0.05, self.read_timeout),
        )
        try:
            writer.write(
                encode_message(
                    make_message(TYPE_WATCH_PTY_OUTPUT, max_bytes=max_bytes, interval_ms=interval_ms)
                )
            )
            await writer.drain()
            while True:
                line = await reader.readline()
                if not line:
                    return
                response = decode_message(line)
                result = {"ok": "error" not in response, "responses": [response], "text_plans": []}
                if response.get("type") == TYPE_PTY_TEXT_STREAM:
                    result["text_plans"] = self.build_text_plans_for_stream(str(response.get("text", "")))
                callback_result = on_result(result)
                if asyncio.iscoroutine(callback_result):
                    await callback_result
                if response.get("type") == TYPE_PTY_STATUS and response.get("active") is False:
                    return
        finally:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), timeout=0.2)
            except (OSError, asyncio.TimeoutError):
                pass

    async def send_key_action(
        self,
        action: str,
        *,
        is_press: bool = True,
        modifiers: list[str] | None = None,
    ) -> dict[str, Any]:
        return await self.request(
            make_message(
                TYPE_PTY_KEY_INPUT,
                action=action,
                is_press=is_press,
                modifiers=list(modifiers or []),
            )
        )

    def build_text_plans_for_stream(self, text: str) -> list[dict[str, Any]]:
        text_plans: list[dict[str, Any]] = []
        if not self.receiver_started:
            if pty_terminal_profile_uses_receiver(self.host_profile):
                text_plans.append(build_pty_terminal_receiver_plan(host_profile=self.host_profile))
            elif self.host_profile == WINDOWS_TEXT_EDITOR_PROFILE:
                text_plans.append(build_pty_terminal_startup_plan(host_profile=self.host_profile))
            self.receiver_started = True
        text_plans.extend(
            build_pty_terminal_text_plans(
                str(text or ""),
                host_profile=self.host_profile,
            )
        )
        return text_plans

    async def request(self, message: dict[str, Any]) -> dict[str, Any]:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(self.socket_path),
                timeout=max(0.05, self.read_timeout),
            )
        except (OSError, asyncio.TimeoutError) as exc:
            error = (
                f"connect timeout after {max(0.05, self.read_timeout):.2f}s"
                if isinstance(exc, asyncio.TimeoutError)
                else str(exc)
            )
            return {
                "ok": False,
                "socket": self.socket_path,
                "error": error,
                "responses": [],
                "text_plans": [],
            }

        responses: list[dict[str, Any]] = []
        text_plans: list[dict[str, Any]] = []
        request_type = message.get("type")
        try:
            writer.write(encode_message(message))
            await writer.drain()
            deadline = asyncio.get_running_loop().time() + max(0.05, self.read_timeout)
            text_seen = False
            while asyncio.get_running_loop().time() < deadline:
                timeout = deadline - asyncio.get_running_loop().time()
                if text_seen:
                    timeout = min(timeout, 0.05)
                try:
                    line = await asyncio.wait_for(reader.readline(), timeout=timeout)
                except asyncio.TimeoutError:
                    break
                if not line:
                    break
                response = decode_message(line)
                responses.append(response)
                if response.get("type") == TYPE_PTY_TEXT_STREAM:
                    text_plans.extend(self.build_text_plans_for_stream(str(response.get("text", ""))))
                    text_seen = True
                    continue
                if response.get("type") == TYPE_PTY_STATUS and request_type == TYPE_PTY_KEY_INPUT:
                    break
                if response.get("type") == TYPE_PTY_STATUS and request_type not in {TYPE_PTY_KEY_INPUT, TYPE_START_PTY_MIRROR}:
                    break
                if response.get("type") == TYPE_PTY_STATUS and response.get("clear_output_queue") is True:
                    break
                if response.get("type") == TYPE_PTY_STATUS and response.get("active") is False:
                    break
        except Exception as exc:
            return {
                "ok": False,
                "socket": self.socket_path,
                "request": message,
                "error": str(exc),
                "responses": responses,
                "text_plans": text_plans,
            }
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

        ok = any(
            item.get("type") in {TYPE_PTY_STATUS, TYPE_PTY_TEXT_STREAM} and "error" not in item
            for item in responses
        )
        return {
            "ok": ok,
            "socket": self.socket_path,
            "request": message,
            "responses": responses,
            "text_plans": text_plans,
        }

    async def _ensure_sessiond_started(self) -> bool:
        path = Path(self.socket_path)
        if path.exists() and not path.is_socket():
            log.warning("sessiond socket path exists but is not a socket: %s", self.socket_path)
            return False
        repo_root = Path(self.repo_root)
        log_file: Any = subprocess.DEVNULL
        try:
            try:
                log_file = await asyncio.to_thread(open, self.log_path, "ab")
            except OSError as exc:
                log.warning(
                    "sessiond auto-start log open failed path=%s error=%s; using DEVNULL",
                    self.log_path,
                    exc,
                )
            env = dict(os.environ)
            env["PYTHONPATH"] = f"{repo_root / 'daemon'}:{repo_root}"
            env["HIDLOOM_REPO_ROOT"] = str(repo_root)
            command = [
                "python3",
                "-m",
                "sessiond.sessiond",
                "--socket",
                self.socket_path,
                "--exit-when-idle-sec",
                str(max(0.0, float(self.idle_exit_sec))),
            ]
            if os.geteuid() == 0:
                user = self._sessiond_user(repo_root)
                if user and user != "root":
                    env_command: list[str] = []
                    for key in ("PYTHONPATH", "HIDLOOM_REPO_ROOT"):
                        env_command.append(f"{key}={env[key]}")
                    command = ["sudo", "-u", user, "env", *env_command, *command]
            log.info("starting sessiond command=%s socket=%s", command[:4], self.socket_path)
            proc = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(repo_root),
                env=env,
                stdout=log_file,
                stderr=log_file,
            )
        except Exception:
            log.exception("sessiond auto-start spawn failed socket=%s", self.socket_path)
            if hasattr(log_file, "close"):
                log_file.close()
            return False
        finally:
            if hasattr(log_file, "close"):
                log_file.close()

        for _ in range(20):
            status = await self.request(make_message(TYPE_PTY_STATUS))
            if status.get("ok"):
                log.info("sessiond auto-start ready socket=%s", self.socket_path)
                return True
            if proc.returncode is not None:
                break
            await asyncio.sleep(0.1)
        return False

    def _sessiond_user(self, repo_root: Path) -> str:
        if self.sessiond_user:
            return self.sessiond_user
        try:
            return pwd.getpwuid(repo_root.stat().st_uid).pw_name
        except (KeyError, OSError):
            return "pi"
