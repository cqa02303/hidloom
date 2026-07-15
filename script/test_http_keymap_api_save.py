#!/usr/bin/env python3
"""Static/local checks for HTTP keymap remap persistence."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon" / "http"))

from keymap_api import DebouncedKeymapSaver, keymap_set_response  # noqa: E402


class FakeRequest:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    async def json(self) -> dict:
        return self._payload


async def main_async() -> None:
    calls: list[dict] = []
    saves_scheduled = 0

    async def send_ctrl(cmd: dict) -> dict:
        calls.append(cmd)
        if cmd["t"] == "M":
            return {"t": "M", "result": "ok"}
        if cmd["t"] == "S":
            return {"t": "S", "result": "ok", "path": "/mnt/p3/keymap.json"}
        raise AssertionError(cmd)

    def schedule_save() -> None:
        nonlocal saves_scheduled
        saves_scheduled += 1

    resp = await keymap_set_response(
        FakeRequest({"layer": 2, "row": 8, "col": 0, "action": "KC_F13"}),  # type: ignore[arg-type]
        send_ctrl,
        schedule_save,
    )
    assert calls == [
        {"t": "M", "l": 2, "r": 8, "c": 0, "a": "KC_F13"},
    ]
    assert saves_scheduled == 1
    body = json.loads(resp.text)
    assert body["result"] == "ok"
    assert body["save"] == "scheduled"

    calls.clear()
    saves_scheduled = 0
    resp = await keymap_set_response(
        FakeRequest({"layer": 2, "row": 8, "col": 0, "action": " LSFT( LGUI(KC_F23) )　"}),  # type: ignore[arg-type]
        send_ctrl,
        schedule_save,
    )
    assert calls == [
        {"t": "M", "l": 2, "r": 8, "c": 0, "a": "LSFT(LGUI(KC_F23))"},
    ]
    assert saves_scheduled == 1
    body = json.loads(resp.text)
    assert body["result"] == "ok"

    debounced_calls: list[dict] = []

    async def debounced_send_ctrl(cmd: dict) -> dict:
        debounced_calls.append(cmd)
        return {"t": cmd["t"], "result": "ok", "path": "/mnt/p3/keymap.json"}

    saver = DebouncedKeymapSaver(debounced_send_ctrl, delay_seconds=0.01)
    saver.schedule()
    saver.schedule()
    saver.schedule()
    await asyncio.sleep(0.03)
    assert debounced_calls == [{"t": "S"}]


def main() -> None:
    asyncio.run(main_async())
    print("ok: HTTP keymap remap schedules debounced semantic LED persistence")


if __name__ == "__main__":
    main()
