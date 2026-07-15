#!/usr/bin/env python3
"""Regression tests for Bluetooth pairing passkey input mode."""
from __future__ import annotations

import tempfile
import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.bt_manager import BtManager, _is_yes_no_agent_prompt, _wait_for_passkey_file  # noqa: E402
from logicd.bt_passkey import BtPasskeyInput, build_bt_passkey_input  # noqa: E402


async def main_async() -> None:
    manager = BtManager()
    assert manager.agent_capability == "DisplayYesNo"
    assert manager.enable_discoverable_during_pairing is False

    calls: list[tuple[str, ...]] = []

    async def fake_bluetoothctl(*args: str, check: bool = True) -> str:
        del check
        calls.append(args)
        return ""

    async def fake_start_agent() -> None:
        calls.append(("start-agent",))

    async def fake_stop_agent() -> None:
        calls.append(("stop-agent",))

    manager._bluetoothctl = fake_bluetoothctl
    manager._start_agent_process = fake_start_agent
    manager._stop_agent_process = fake_stop_agent
    await manager.pairing(True)
    await manager.pairing(False)
    assert calls == [
        ("start-agent",),
        ("pairable", "on"),
        ("discoverable", "off"),
        ("pairable", "off"),
        ("discoverable", "off"),
        ("stop-agent",),
    ]

    calls.clear()
    manager.enable_discoverable_during_pairing = True
    await manager.pairing(True)
    assert calls == [
        ("start-agent",),
        ("pairable", "on"),
        ("discoverable", "on"),
    ]

    status_manager = BtManager()

    async def fake_run_text(*cmd: str, check: bool = True) -> str:
        del check
        if cmd == ("bluetoothctl", "show"):
            return "Controller 11:22:33:44:55:66 test\n\tPowered: yes\n\tDiscoverable: no\n\tPairable: no\n"
        if cmd == ("bluetoothctl", "paired-devices"):
            return "Invalid command in menu main: paired-devices\n"
        if cmd == ("bluetoothctl", "devices", "Connected"):
            return ""
        if cmd == ("bluetoothctl", "devices"):
            return "Device AA:BB:CC:DD:EE:FF iPhone\n"
        if cmd == ("bluetoothctl", "info", "AA:BB:CC:DD:EE:FF"):
            return "Device AA:BB:CC:DD:EE:FF\n\tPaired: yes\n\tBonded: yes\n\tTrusted: yes\n\tConnected: no\n"
        return ""

    async def fake_service_active(_name: str) -> bool:
        return True

    status_manager._run_text = fake_run_text
    status_manager._service_active = fake_service_active
    status = await status_manager.get_status()
    assert status.paired_devices == ("AA:BB:CC:DD:EE:FF",)
    assert status.connected_devices == ()

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "passkey.txt"
        built = build_bt_passkey_input()
        assert built.manual_input_enabled is False

        state = BtPasskeyInput(passkey_file=str(path))

        assert state.handle_action("KC_1", True).consumed is False
        begin = state.begin()
        assert begin.phase == "pairing"
        assert state.active is True
        assert state.handle_action("KC_A", True).consumed is False
        assert state.handle_action("KC_A", False).consumed is False

        result = state.handle_action("KC_3", True)
        assert result.consumed is True
        assert result.phase == "passkey"
        assert result.digits == "3"
        state.handle_action("KC_9", True)
        state.handle_action("KC_9", False)
        state.handle_action("KC_9", True)
        assert state.digits == "399"
        state.handle_action("KC_BSPC", True)
        assert state.digits == "39"
        state.handle_action("KC_0", True)
        state.handle_action("KC_1", True)
        state.handle_action("KC_2", True)
        state.handle_action("KC_3", True)
        state.handle_action("KC_4", True)
        assert state.digits == "390123"
        state.handle_action("KC_5", True)
        assert state.digits == "390123"

        submit = state.handle_action("KC_ENT", True)
        assert submit.consumed is True
        assert submit.submitted is True
        assert submit.phase == "submitted"
        assert submit.digits == "390123"
        assert path.read_text() == "390123"
        assert state.active is False
        assert state.digits == ""

        state.begin()
        state.handle_action("KC_4", True)
        cancel = state.handle_action("KC_ESC", True)
        assert cancel.canceled is True
        assert state.active is False
        assert state.digits == ""

        path.write_text("123456")
        assert await _wait_for_passkey_file(str(path), timeout=0.5) == "123456"
        assert not path.exists()
        assert _is_yes_no_agent_prompt("[agent] Confirm passkey 123456 (yes/no):")
        assert _is_yes_no_agent_prompt("[agent] Authorize service 00001812-0000-1000-8000-00805f9b34fb (yes/no):")
        assert not _is_yes_no_agent_prompt("[agent] Enter passkey (number in 0-999999):")

    print("ok: Bluetooth passkey input mode")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
