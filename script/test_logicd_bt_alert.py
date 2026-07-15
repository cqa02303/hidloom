#!/usr/bin/env python3
"""Regression test for Bluetooth OLED alerts."""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.bt_manager import BtStatus  # noqa: E402
from logicd.bt_passkey import BtPasskeyInput  # noqa: E402
from logicd.input_events import InputEventContext, handle_resolved_action  # noqa: E402
from logicd.keymap import LayerManager  # noqa: E402


class FakeMacros:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    async def handle(self, _action: str, _is_press: bool) -> None:
        self.calls.append((_action, _is_press))


@dataclass
class FakeBtManager:
    status: BtStatus
    handled: list[tuple[str, bool]]
    ensure_powered_calls: int = 0

    async def handle_action(self, action: str, is_press: bool) -> bool:
        self.handled.append((action, is_press))
        return action.startswith("BT_")

    async def get_status(self) -> BtStatus:
        return self.status

    async def ensure_powered_for_output(self) -> None:
        self.ensure_powered_calls += 1


def make_ctx(
    bt: FakeBtManager,
    alerts: list[tuple[str, float]],
    pairing_states: list[tuple[str, str]] | None = None,
    bt_passkey: BtPasskeyInput | None = None,
) -> InputEventContext:
    layers = LayerManager()
    layers.load([{}])
    macros = FakeMacros()
    ctx = InputEventContext(
        layers=layers,
        interactions=None,
        macros=macros,
        encoders=None,
        joysticks=None,
        pressed_matrix=set(),
        push_ledd_key_event=lambda _row, _col, _press: None,
        push_ledd_status=lambda: None,
        push_i2cd_status=lambda: None,
        push_i2cd_alert=lambda msg, sec=2.0: alerts.append((msg, sec)),
        push_ledd_anim=lambda _anim: None,
        apply_lighting_key_action=lambda _action, _is_press: False,
        mouse_write_fn=lambda _report: None,
        bt_manager=bt,
        push_bt_pairing_state=(lambda phase, digits="": pairing_states.append((phase, digits))) if pairing_states is not None else None,
        bt_passkey=bt_passkey,
    )
    ctx.test_macros = macros
    return ctx


async def main_async() -> None:
    alerts: list[tuple[str, float]] = []
    pairing_states: list[tuple[str, str]] = []
    bt = FakeBtManager(
        status=BtStatus(powered=True, pairable=True, discoverable=True),
        handled=[],
    )
    passkey = BtPasskeyInput(
        passkey_file="/tmp/test-logicd-bt-passkey.txt",
        manual_input_enabled=False,
    )
    ctx = make_ctx(bt, alerts, pairing_states, passkey)
    await handle_resolved_action("BT_PAIRING_TOGGLE", True, ctx)
    assert alerts[-1] == ("BT PAIRING", 2.0)
    assert pairing_states[-1] == ("pairing", "")
    assert passkey.active is False
    await handle_resolved_action("KC_3", True, ctx)
    assert pairing_states[-1] == ("pairing", "")
    assert ctx.test_macros.calls[-1] == ("KC_3", True)

    manual_passkey = BtPasskeyInput(passkey_file="/tmp/test-logicd-bt-passkey.txt")
    manual_passkey.begin()
    await handle_resolved_action("KC_3", True, make_ctx(bt, alerts, pairing_states, manual_passkey))
    assert pairing_states[-1] == ("passkey", "3")

    bt.status = BtStatus(powered=False, pairable=False, discoverable=False)
    await handle_resolved_action("BT_PAIRING_OFF", True, make_ctx(bt, alerts, pairing_states, passkey))
    assert pairing_states[-1] == ("off", "")
    assert passkey.active is False

    await handle_resolved_action("BT_POWER_OFF", True, make_ctx(bt, alerts, pairing_states))
    assert alerts[-1] == ("BT OFF", 2.0)
    assert pairing_states[-1] == ("off", "")

    bt.status = BtStatus(powered=True, connected_devices=("AA:BB:CC:DD:EE:FF",))
    await handle_resolved_action("BT_STATUS", True, make_ctx(bt, alerts))
    assert alerts[-1] == ("BT CONNECTED\n1 device", 2.0)

    await handle_resolved_action("BT_DISCONNECT", True, make_ctx(bt, alerts))
    assert alerts[-1] == ("BT DISCONNECTED", 2.0)

    before = list(alerts)
    await handle_resolved_action("BT_STATUS", False, make_ctx(bt, alerts))
    assert alerts == before

    await handle_resolved_action("KC_BT", True, make_ctx(bt, alerts))
    assert bt.ensure_powered_calls == 1

    print("ok: Bluetooth actions emit OLED alerts")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
