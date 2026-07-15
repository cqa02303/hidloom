#!/usr/bin/env python3
"""Regression test for logicd WIFI_* action dispatch."""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.input_events import InputEventContext, handle_resolved_action  # noqa: E402
from logicd.keymap import LayerManager  # noqa: E402
from logicd.wifi_manager import WifiStatus  # noqa: E402


class FakeMacros:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    async def handle(self, action: str, is_press: bool) -> None:
        self.calls.append((action, is_press))


@dataclass
class FakeWifiManager:
    status: WifiStatus
    handled: list[tuple[str, bool]]

    async def handle_action(self, action: str, is_press: bool) -> bool:
        self.handled.append((action, is_press))
        return action.startswith("WIFI_")

    async def get_status(self) -> WifiStatus:
        return self.status


class FakeBtManager:
    async def handle_action(self, _action: str, _is_press: bool) -> bool:
        return False


def make_ctx(wifi: FakeWifiManager, alerts: list[tuple[str, float]]) -> InputEventContext:
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
        bt_manager=FakeBtManager(),
        wifi_manager=wifi,
    )
    ctx.test_macros = macros
    return ctx


async def main_async() -> None:
    alerts: list[tuple[str, float]] = []
    wifi = FakeWifiManager(WifiStatus(blocked=True), [])
    ctx = make_ctx(wifi, alerts)
    await handle_resolved_action("WIFI_POWER_OFF", True, ctx)
    assert wifi.handled[-1] == ("WIFI_POWER_OFF", True)
    assert alerts[-1] == ("Wi-Fi OFF\nuntil reboot", 2.0)
    assert ctx.test_macros.calls == []

    await handle_resolved_action("WIFI_POWER_OFF", False, ctx)
    assert wifi.handled[-1] == ("WIFI_POWER_OFF", False)
    assert len(alerts) == 1

    wifi.status = WifiStatus(blocked=False, connected=True, ssid="HomeAP")
    await handle_resolved_action("WIFI_STATUS", True, ctx)
    assert alerts[-1] == ("Wi-Fi ON\nHomeAP", 2.0)

    wifi.status = WifiStatus(blocked=False, connected=False)
    await handle_resolved_action("WIFI_POWER_ON", True, ctx)
    assert alerts[-1] == ("Wi-Fi ON", 2.0)

    wifi.status = WifiStatus(blocked=None, connected=None)
    await handle_resolved_action("WIFI_POWER_TOGGLE", True, ctx)
    assert alerts[-1] == ("Wi-Fi UNKNOWN", 2.0)

    await handle_resolved_action("KC_A", True, ctx)
    assert ctx.test_macros.calls[-1] == ("KC_A", True)

    print("ok: logicd Wi-Fi actions emit OLED alerts and are consumed")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
