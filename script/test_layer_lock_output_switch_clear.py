#!/usr/bin/env python3
"""Regression test for clearing Layer Lock before output target switches."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.input_events import InputEventContext, handle_resolved_action  # noqa: E402
from logicd.keymap import LayerManager  # noqa: E402
from logicd.layer_action import handle_layer_action  # noqa: E402


class MacroRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, bool]] = []

    async def handle(self, action: str, is_press: bool) -> None:
        self.events.append((action, is_press))


class InteractionStub:
    def __init__(self) -> None:
        self.shortcut_clears = 0

    def clear_key_locks(self, reason: str) -> list[object]:
        assert reason == "output_switch"
        return []

    def clear_held_keys(self, reason: str, exclude_actions: tuple[str, ...]) -> list[object]:
        assert reason == "output_switch"
        assert exclude_actions == ("KC_USB",)
        return []

    def clear_runtime_shortcuts(self) -> None:
        self.shortcut_clears += 1


def _ctx(layers: LayerManager, interactions: InteractionStub, macros: MacroRecorder) -> InputEventContext:
    return InputEventContext(
        layers=layers,
        interactions=interactions,
        macros=macros,
        encoders=None,
        joysticks=None,
        pressed_matrix={(4, 6), (1, 1)},
        push_ledd_key_event=lambda _row, _col, _press: None,
        push_ledd_status=lambda: status_calls.append("ledd"),
        push_i2cd_status=lambda: status_calls.append("i2cd"),
        push_i2cd_alert=lambda *_args, **_kwargs: None,
        push_ledd_anim=lambda _anim: None,
        apply_lighting_key_action=lambda _action, _press: False,
        mouse_write_fn=lambda _report: None,
        bt_manager=SimpleNamespace(handle_action=lambda _action, _press: asyncio.sleep(0, result=False)),
        wifi_manager=SimpleNamespace(handle_action=lambda _action, _press: asyncio.sleep(0, result=False)),
    )


status_calls: list[str] = []


async def main_async() -> None:
    layers = LayerManager()
    layers.load([{"0,0": "KC_A"}, {"0,0": "KC_B"}, {"0,0": "KC_C"}])
    layers.momentary_on(2)
    result = handle_layer_action(layers, "QK_LAYER_LOCK", True)
    assert result is not None and result.changed
    assert layers.active_snapshot()["locked"] == [2]

    interactions = InteractionStub()
    macros = MacroRecorder()
    ctx = _ctx(layers, interactions, macros)

    await handle_resolved_action("KC_USB", True, ctx, matrix_key=(4, 6))

    assert layers.active_snapshot()["locked"] == []
    assert status_calls == ["ledd", "i2cd"]
    assert interactions.shortcut_clears == 1
    assert ctx.pressed_matrix == {(4, 6)}
    assert macros.events == [("KC_USB", True)]


def main() -> None:
    asyncio.run(main_async())
    print("ok: output switch clears Layer Lock runtime state")


if __name__ == "__main__":
    main()
