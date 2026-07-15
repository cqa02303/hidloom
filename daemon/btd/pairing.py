"""Pairing/discoverable control boundary for btd BlueZ experiments."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol

log = logging.getLogger("btd.pairing")

CommandRunner = Callable[..., Awaitable[str]]
DEFAULT_PAIRING_AGENT_CAPABILITY = "KeyboardOnly"
DEFAULT_PAIRING_PASSKEY_FILE = "/tmp/btd_pairing_passkey.txt"
ALLOWED_PAIRING_AGENT_CAPABILITIES = {
    "DisplayOnly",
    "DisplayYesNo",
    "KeyboardOnly",
    "KeyboardDisplay",
    "NoInputNoOutput",
}


class PairingModeAdapter(Protocol):
    async def enable_pairing_mode(self) -> None:
        """Enable host-visible pairing mode."""

    async def restore_pairing_mode(self) -> None:
        """Restore state changed by enable_pairing_mode."""


@dataclass
class PairingStatus:
    enabled: bool = False
    adapter_kind: str = "dry-run"
    agent_capability: str = ""
    pairable: bool | None = None
    discoverable: bool | None = None
    error: str = ""


@dataclass
class DryRunPairingModeAdapter:
    enabled: bool = False
    enable_discoverable: bool = False

    async def enable_pairing_mode(self) -> None:
        self.enabled = True
        log.info("dry-run pairing mode enabled")

    async def restore_pairing_mode(self) -> None:
        self.enabled = False
        log.info("dry-run pairing mode restored")

    def status(self) -> PairingStatus:
        return PairingStatus(
            enabled=self.enabled,
            adapter_kind="dry-run",
            pairable=self.enabled,
            discoverable=self.enabled and self.enable_discoverable,
        )


@dataclass
class BluetoothctlPairingModeAdapter:
    """Small bluetoothctl-based pairing mode helper.

    This mirrors logicd.bt_manager's first control layer so btd can be tested as
    a standalone BLE HID peripheral without requiring a physical BT_PAIRING key.
    It snapshots pairable/discoverable and restores those booleans on stop.
    """

    runner: CommandRunner | None = None
    command_timeout: float = 5.0
    agent_capability: str = DEFAULT_PAIRING_AGENT_CAPABILITY
    passkey_file: str = DEFAULT_PAIRING_PASSKEY_FILE
    enable_discoverable: bool = False
    enabled: bool = False
    pairable: bool | None = None
    discoverable: bool | None = None
    _previous_pairable: bool | None = None
    _previous_discoverable: bool | None = None
    _agent_proc: Any | None = None
    _agent_log_task: asyncio.Task[None] | None = None
    last_error: str = ""

    async def enable_pairing_mode(self) -> None:
        try:
            show = await self._run("bluetoothctl", "show", check=False)
            self._previous_pairable = _parse_bt_bool(show, "Pairable")
            self._previous_discoverable = _parse_bt_bool(show, "Discoverable")
            if self.runner is None:
                await self._start_agent_process()
            else:
                await self._run("bluetoothctl", "agent", self.agent_capability, check=False)
                await self._run("bluetoothctl", "default-agent", check=False)
            await self._run("bluetoothctl", "pairable", "on")
            discoverable = "on" if self.enable_discoverable else "off"
            await self._run("bluetoothctl", "discoverable", discoverable)
            self.enabled = True
            self.pairable = True
            self.discoverable = self.enable_discoverable
            self.last_error = ""
            log.info("Bluetooth pairing mode enabled for btd agent=%s", self.agent_capability)
        except Exception as exc:
            self.last_error = str(exc)
            log.warning("Bluetooth pairing mode enable failed: %s", exc)

    async def restore_pairing_mode(self) -> None:
        if self._previous_pairable is None and self._previous_discoverable is None:
            await self._stop_agent_process()
            return
        try:
            if self._previous_pairable is not None:
                await self._run("bluetoothctl", "pairable", "on" if self._previous_pairable else "off", check=False)
                self.pairable = self._previous_pairable
            if self._previous_discoverable is not None:
                await self._run("bluetoothctl", "discoverable", "on" if self._previous_discoverable else "off", check=False)
                self.discoverable = self._previous_discoverable
            self.enabled = False
            self.last_error = ""
            log.info("Bluetooth pairing mode restored for btd")
        except Exception as exc:
            self.last_error = str(exc)
            log.warning("Bluetooth pairing mode restore failed: %s", exc)
        finally:
            await self._stop_agent_process()

    def status(self) -> PairingStatus:
        return PairingStatus(
            enabled=self.enabled,
            adapter_kind="bluetoothctl",
            agent_capability=self.agent_capability,
            pairable=self.pairable,
            discoverable=self.discoverable,
            error=self.last_error,
        )

    async def _run(self, *cmd: str, check: bool = True) -> str:
        if self.runner is not None:
            return await self.runner(*cmd, check=check)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.command_timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError("command timed out: " + " ".join(cmd))
        out = stdout.decode(errors="replace")
        err = stderr.decode(errors="replace")
        if check and proc.returncode != 0:
            raise RuntimeError(f"{' '.join(cmd)} failed ({proc.returncode}): {err.strip() or out.strip()}")
        if err.strip():
            log.debug("%s stderr: %s", " ".join(cmd), err.strip())
        return out

    async def _start_agent_process(self) -> None:
        if self._agent_proc is not None and self._agent_proc.returncode is None:
            return
        self._agent_proc = await asyncio.create_subprocess_exec(
            "bluetoothctl",
            "--agent",
            self.agent_capability,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        if self._agent_proc.stdout is not None:
            self._agent_log_task = asyncio.create_task(
                self._log_agent_output(self._agent_proc.stdout, self._agent_proc.stdin)
            )
        await asyncio.sleep(0.3)
        if self._agent_proc.returncode is not None:
            raise RuntimeError(f"bluetoothctl --agent {self.agent_capability} exited early")
        if self._agent_proc.stdin is not None:
            self._agent_proc.stdin.write(b"default-agent\n")
            await self._agent_proc.stdin.drain()
        log.info("Bluetooth pairing agent started capability=%s", self.agent_capability)

    async def _stop_agent_process(self) -> None:
        proc = self._agent_proc
        log_task = self._agent_log_task
        self._agent_proc = None
        self._agent_log_task = None
        if proc is None or proc.returncode is not None:
            if log_task is not None:
                log_task.cancel()
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        if log_task is not None:
            log_task.cancel()
            try:
                await log_task
            except asyncio.CancelledError:
                pass
        log.info("Bluetooth pairing agent stopped")

    async def _log_agent_output(self, stream: asyncio.StreamReader, stdin: Any | None) -> None:
        while True:
            line = await stream.readline()
            if not line:
                return
            text = line.decode(errors="replace").strip()
            if not text:
                continue
            log.info("Bluetooth pairing agent: %s", text)
            if _is_yes_no_agent_prompt(text) and stdin is not None:
                stdin.write(b"yes\n")
                await stdin.drain()
                log.info("Bluetooth pairing agent confirmation accepted")
            elif ("Enter passkey" in text or "Request passkey" in text) and stdin is not None:
                passkey = await _wait_for_passkey_file(self.passkey_file, timeout=25.0)
                if passkey:
                    stdin.write((passkey + "\n").encode())
                    await stdin.drain()
                    log.info("Bluetooth pairing agent passkey submitted from %s", self.passkey_file)


def build_pairing_mode_adapter(kind: str | None = None, *, agent_capability: str | None = None) -> PairingModeAdapter:
    normalized = (kind or "dry-run").strip().lower().replace("_", "-")
    enable_discoverable = _env_bool("BTD_PAIRING_DISCOVERABLE", "BT_PAIRING_DISCOVERABLE", default=False)
    if normalized in {"", "dry-run", "dryrun", "mock"}:
        return DryRunPairingModeAdapter(enable_discoverable=enable_discoverable)
    if normalized in {"bluetoothctl", "bluez", "system"}:
        return BluetoothctlPairingModeAdapter(
            agent_capability=normalize_pairing_agent_capability(agent_capability),
            passkey_file=os.environ.get("BTD_PAIRING_PASSKEY_FILE", DEFAULT_PAIRING_PASSKEY_FILE),
            enable_discoverable=enable_discoverable,
        )
    raise ValueError("unknown pairing mode adapter kind: %s" % kind)


def _parse_bt_bool(text: str, field_name: str) -> bool | None:
    m = re.search(rf"^\s*{re.escape(field_name)}:\s*(yes|no)\s*$", text, re.MULTILINE | re.IGNORECASE)
    if not m:
        return None
    return m.group(1).lower() == "yes"


def _env_bool(*names: str, default: bool = False) -> bool:
    for name in names:
        raw = os.environ.get(name)
        if raw is not None:
            return raw.strip().lower() in {"1", "true", "yes", "on"}
    return default


def normalize_pairing_agent_capability(value: str | None) -> str:
    capability = (value or DEFAULT_PAIRING_AGENT_CAPABILITY).strip()
    if capability not in ALLOWED_PAIRING_AGENT_CAPABILITIES:
        allowed = ", ".join(sorted(ALLOWED_PAIRING_AGENT_CAPABILITIES))
        raise ValueError(f"invalid pairing agent capability {value!r}; expected one of: {allowed}")
    return capability


def _is_yes_no_agent_prompt(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "Confirm passkey",
            "Request confirmation",
            "Authorize service",
            "Accept pairing",
        )
    )


async def _wait_for_passkey_file(path: str, *, timeout: float) -> str | None:
    deadline = asyncio.get_running_loop().time() + timeout
    passkey_path = Path(path)
    while asyncio.get_running_loop().time() < deadline:
        try:
            text = passkey_path.read_text().strip()
        except FileNotFoundError:
            text = ""
        if text:
            try:
                passkey_path.unlink()
            except FileNotFoundError:
                pass
            if text.isdigit():
                return text
            log.warning("Ignoring non-numeric pairing passkey file %s", path)
            return None
        await asyncio.sleep(0.2)
    log.warning("Bluetooth pairing agent timed out waiting for passkey file: %s", path)
    return None
