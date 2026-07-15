#!/usr/bin/env python3
"""Regression tests for logicd ctrl SPID_CONNECT / SPID_DISCONNECT handling."""
from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.ctrl import CtrlContext, process_ctrl_json  # noqa: E402


class DummyWriter:
    def __init__(self) -> None:
        self.data: list[dict] = []

    def write(self, payload: bytes) -> None:
        self.data.append(json.loads(payload.decode("utf-8")))

    async def drain(self) -> None:
        return None


class DummyLayers:
    def layers_snapshot(self):
        return []

    def active_snapshot(self):
        return []


@dataclass
class Calls:
    connects: list[str] = field(default_factory=list)
    disconnects: int = 0


async def main_async() -> None:
    calls = Calls()

    async def connect(socket_path: str) -> None:
        calls.connects.append(socket_path)

    async def disconnect() -> None:
        calls.disconnects += 1

    ctx = CtrlContext(
        matrix_in_range=lambda row, col: True,
        handle_analog_stick=lambda index, x, y: asyncio.sleep(0),
        layers=DummyLayers(),
        current_hid_mode="auto",
        current_output_target="auto",
        pressed_matrix=set(),
        save_runtime_keymap=lambda: "",
        reset_runtime_keymap=lambda: {},
        led_state={},
        normalize_led_state=lambda raw: {},
        load_led_state=lambda: None,
        save_led_state=lambda: "",
        cancel_led_state_save=lambda: None,
        push_ledd_vialrgb_direct=lambda first, pixels: None,
        push_ledd_vialrgb_direct_pattern=lambda pattern, fps, brightness: None,
        normalize_vialrgb_mode=lambda mode: mode,
        remember_nonzero_led_mode=lambda: None,
        push_ledd_vialrgb=lambda: None,
        schedule_led_state_save=lambda: None,
        notify_i2cd_led_effect_if_changed=lambda prev, cur: None,
        handle_spid_connect=connect,
        handle_spid_disconnect=disconnect,
    )

    writer = DummyWriter()
    await process_ctrl_json('{"t":"SPID_CONNECT","socket":"/tmp/test-spi.sock"}', ctx, writer)
    assert calls.connects == ["/tmp/test-spi.sock"]
    assert writer.data[-1] == {"t": "SPID_CONNECT", "result": "ok", "socket": "/tmp/test-spi.sock"}

    await process_ctrl_json('{"t":"SPID_STATUS","state":"ready","socket":"/tmp/ready-spi.sock"}', ctx, writer)
    assert calls.connects[-1] == "/tmp/ready-spi.sock"
    assert writer.data[-1]["result"] == "ok"

    await process_ctrl_json('{"t":"SPID_DISCONNECT"}', ctx, writer)
    assert calls.disconnects == 1
    assert writer.data[-1] == {"t": "SPID_DISCONNECT", "result": "ok"}

    await process_ctrl_json('{"t":"SPID_STATUS","state":"no_device"}', ctx, writer)
    assert calls.disconnects == 2
    assert writer.data[-1]["result"] == "ok"

    no_spid_ctx = CtrlContext(
        matrix_in_range=lambda row, col: True,
        handle_analog_stick=lambda index, x, y: asyncio.sleep(0),
        layers=DummyLayers(),
        current_hid_mode="auto",
        current_output_target="auto",
        pressed_matrix=set(),
        save_runtime_keymap=lambda: "",
        reset_runtime_keymap=lambda: {},
        led_state={},
        normalize_led_state=lambda raw: {},
        load_led_state=lambda: None,
        save_led_state=lambda: "",
        cancel_led_state_save=lambda: None,
        push_ledd_vialrgb_direct=lambda first, pixels: None,
        push_ledd_vialrgb_direct_pattern=lambda pattern, fps, brightness: None,
        normalize_vialrgb_mode=lambda mode: mode,
        remember_nonzero_led_mode=lambda: None,
        push_ledd_vialrgb=lambda: None,
        schedule_led_state_save=lambda: None,
        notify_i2cd_led_effect_if_changed=lambda prev, cur: None,
    )
    err_writer = DummyWriter()
    await process_ctrl_json('{"t":"SPID_CONNECT"}', no_spid_ctx, err_writer)
    assert err_writer.data[-1]["result"] == "error"

    print("ok: logicd ctrl spid")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
