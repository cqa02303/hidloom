#!/usr/bin/env python3
"""Regression tests for BT_POWER_OFF managed service behavior."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.bt_manager import BtManager, BtStatus  # noqa: E402


class FakeBtManager(BtManager):
    def __init__(self) -> None:
        super().__init__(command_timeout=0.1)
        self.commands: list[tuple[str, ...]] = []
        self.status = BtStatus(powered=False)

    async def _run_text(self, *cmd: str, check: bool = True) -> str:  # noqa: ARG002
        self.commands.append(tuple(cmd))
        if cmd[:3] == ("bluetoothctl", "show"):
            return "Powered: yes\n" if self.status.powered else "Powered: no\n"
        return ""

    async def get_status(self) -> BtStatus:
        return self.status


async def main_async() -> None:
    old_services = os.environ.get("BT_POWER_MANAGED_SERVICES")
    old_stop = os.environ.get("BT_POWER_STOP_MANAGED_SERVICES")
    old_start = os.environ.get("BT_POWER_START_MANAGED_SERVICES")
    try:
        os.environ.pop("BT_POWER_MANAGED_SERVICES", None)
        os.environ.pop("BT_POWER_STOP_MANAGED_SERVICES", None)
        os.environ.pop("BT_POWER_START_MANAGED_SERVICES", None)
        bt = FakeBtManager()
        assert bt.managed_power_services == ("btd",)
        bt.status = BtStatus(powered=True)
        await bt.power(False)
        assert ("bluetoothctl", "pairable", "off") in bt.commands
        assert ("bluetoothctl", "discoverable", "off") in bt.commands
        assert ("systemctl", "stop", "btd") in bt.commands
        assert ("bluetoothctl", "power", "off") in bt.commands

        bt = FakeBtManager()
        bt.status = BtStatus(powered=False)
        await bt.power(True)
        assert ("rfkill", "unblock", "bluetooth") in bt.commands
        assert ("systemctl", "start", "bluetooth") in bt.commands
        assert ("bluetoothctl", "power", "on") in bt.commands
        assert ("systemctl", "start", "btd") in bt.commands

        os.environ["BT_POWER_MANAGED_SERVICES"] = "btd custom-bt.service"
        bt = FakeBtManager()
        assert bt.managed_power_services == ("btd", "custom-bt.service")
        bt.status = BtStatus(powered=True)
        await bt.power(False)
        assert ("systemctl", "stop", "btd") in bt.commands
        assert ("systemctl", "stop", "custom-bt.service") in bt.commands

        os.environ["BT_POWER_STOP_MANAGED_SERVICES"] = "0"
        bt = FakeBtManager()
        bt.status = BtStatus(powered=True)
        await bt.power(False)
        assert not any(cmd[:2] == ("systemctl", "stop") for cmd in bt.commands)
    finally:
        if old_services is None:
            os.environ.pop("BT_POWER_MANAGED_SERVICES", None)
        else:
            os.environ["BT_POWER_MANAGED_SERVICES"] = old_services
        if old_stop is None:
            os.environ.pop("BT_POWER_STOP_MANAGED_SERVICES", None)
        else:
            os.environ["BT_POWER_STOP_MANAGED_SERVICES"] = old_stop
        if old_start is None:
            os.environ.pop("BT_POWER_START_MANAGED_SERVICES", None)
        else:
            os.environ["BT_POWER_START_MANAGED_SERVICES"] = old_start
    print("ok: BT power managed services")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
