#!/usr/bin/env python3
"""Regression tests for btd pairing mode adapter."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from btd.pairing import (  # noqa: E402
    DEFAULT_PAIRING_PASSKEY_FILE,
    BluetoothctlPairingModeAdapter,
    DryRunPairingModeAdapter,
    _is_yes_no_agent_prompt,
    _wait_for_passkey_file,
    build_pairing_mode_adapter,
    normalize_pairing_agent_capability,
)


async def main_async() -> None:
    dry = DryRunPairingModeAdapter()
    await dry.enable_pairing_mode()
    status = dry.status()
    assert status.enabled is True
    assert status.pairable is True
    assert status.discoverable is False
    await dry.restore_pairing_mode()
    assert dry.status().enabled is False

    calls: list[tuple[tuple[str, ...], bool]] = []

    async def runner(*cmd: str, check: bool = True) -> str:
        calls.append((cmd, check))
        if cmd == ("bluetoothctl", "show"):
            return "Controller AA:BB:CC:DD:EE:FF\n\tPairable: no\n\tDiscoverable: yes\n"
        return ""

    adapter = BluetoothctlPairingModeAdapter(runner=runner)
    await adapter.enable_pairing_mode()
    assert adapter.status().enabled is True
    assert adapter.status().agent_capability == "KeyboardOnly"
    await adapter.restore_pairing_mode()
    assert adapter.status().enabled is False
    command_text = [" ".join(cmd) for cmd, _ in calls]
    assert "bluetoothctl agent KeyboardOnly" in command_text
    assert "bluetoothctl default-agent" in command_text
    assert "bluetoothctl pairable on" in command_text
    assert "bluetoothctl discoverable off" in command_text
    assert "bluetoothctl pairable off" in command_text
    assert "bluetoothctl discoverable on" in command_text

    assert isinstance(build_pairing_mode_adapter(), DryRunPairingModeAdapter)
    assert isinstance(build_pairing_mode_adapter("bluetoothctl"), BluetoothctlPairingModeAdapter)
    custom_agent = build_pairing_mode_adapter("bluetoothctl", agent_capability="NoInputNoOutput")
    assert isinstance(custom_agent, BluetoothctlPairingModeAdapter)
    assert custom_agent.agent_capability == "NoInputNoOutput"
    assert custom_agent.passkey_file == DEFAULT_PAIRING_PASSKEY_FILE
    assert "Request passkey" in (ROOT / "daemon" / "btd" / "pairing.py").read_text()
    assert _is_yes_no_agent_prompt("[agent] Confirm passkey 123456 (yes/no):")
    assert _is_yes_no_agent_prompt("[agent] Authorize service 00001812-0000-1000-8000-00805f9b34fb (yes/no):")
    assert not _is_yes_no_agent_prompt("[agent] Enter passkey (number in 0-999999):")
    passkey_path = ROOT / ".tmp-test-passkey"
    passkey_path.write_text("123456")
    assert await _wait_for_passkey_file(str(passkey_path), timeout=0.5) == "123456"
    assert not passkey_path.exists()
    passkey_path.write_text("abc")
    assert await _wait_for_passkey_file(str(passkey_path), timeout=0.5) is None
    assert normalize_pairing_agent_capability(None) == "KeyboardOnly"
    assert normalize_pairing_agent_capability("KeyboardDisplay") == "KeyboardDisplay"
    try:
        normalize_pairing_agent_capability("BadAgent")
    except ValueError as exc:
        assert "invalid pairing agent capability" in str(exc)
    else:
        raise AssertionError("invalid pairing agent should fail")
    try:
        build_pairing_mode_adapter("bad")
    except ValueError as exc:
        assert "unknown pairing mode adapter kind" in str(exc)
    else:
        raise AssertionError("invalid pairing adapter should fail")

    print("ok: btd pairing mode adapter")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
