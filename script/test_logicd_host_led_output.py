#!/usr/bin/env python3
"""Regression tests for host keyboard LED output mapping."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.ctrl import CtrlContext, process_ctrl_json  # noqa: E402
from logicd.host_led_output import (  # noqa: E402
    apply_host_led_report,
    host_led_states_from_report,
    normalize_host_led_output_config,
    toggle_host_led_state_for_action,
)


class DummyWriter:
    def __init__(self) -> None:
        self.data: list[dict] = []

    def write(self, data: bytes) -> None:
        for line in data.decode("utf-8").splitlines():
            self.data.append(json.loads(line))

    async def drain(self) -> None:
        return None


def base_ctx(handle_host_led_report=None) -> CtrlContext:
    return CtrlContext(
        matrix_in_range=lambda row, col: True,
        handle_analog_stick=lambda index, x, y: asyncio.sleep(0),
        layers=None,
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
        handle_host_led_report=handle_host_led_report,
    )


async def main_async() -> None:
    cfg = normalize_host_led_output_config({
        "states": {"caps_lock": True, "num_lock": True, "scroll_lock": False},
    })
    assert host_led_states_from_report(0b0000_0011, cfg) == {"caps_lock": True, "num_lock": True}
    assert toggle_host_led_state_for_action("KC_CAPS", {}, cfg, lambda state, enabled: None) is None

    fallback_cfg = normalize_host_led_output_config({
        "fallback_internal_toggle": True,
        "states": {"caps_lock": True, "num_lock": True, "scroll_lock": False},
    })

    pushed: list[tuple[str, bool]] = []
    states: dict[str, bool] = {}
    changed = apply_host_led_report(0b0000_0010, states, cfg, lambda state, enabled: pushed.append((state, enabled)))
    assert changed == {"caps_lock": True}
    assert pushed == [("caps_lock", True)]
    assert states == {"caps_lock": True}
    pushed.clear()

    assert apply_host_led_report(0, {}, cfg, lambda state, enabled: pushed.append((state, enabled))) == {}
    assert pushed == []
    changed = apply_host_led_report(0, {}, cfg, lambda state, enabled: pushed.append((state, enabled)), force_sync=True)
    assert changed == {"caps_lock": False, "num_lock": False}
    assert pushed == [("caps_lock", False), ("num_lock", False)]
    pushed.clear()

    assert toggle_host_led_state_for_action("KC_CAPS", states, fallback_cfg, lambda state, enabled: pushed.append((state, enabled))) == "caps_lock"
    assert states["caps_lock"] is False
    assert toggle_host_led_state_for_action("KC_NLCK", states, fallback_cfg, lambda state, enabled: pushed.append((state, enabled))) == "num_lock"
    assert states["num_lock"] is True
    assert toggle_host_led_state_for_action("KC_SCROLLLOCK", states, fallback_cfg, lambda state, enabled: pushed.append((state, enabled))) is None

    all_cfg = normalize_host_led_output_config({
        "fallback_internal_toggle": True,
        "states": {"caps_lock": True, "num_lock": True, "scroll_lock": True, "kana": True},
    })
    assert toggle_host_led_state_for_action("KC_SLCK", states, all_cfg, lambda state, enabled: pushed.append((state, enabled))) == "scroll_lock"
    assert toggle_host_led_state_for_action("KC_INT2", states, all_cfg, lambda state, enabled: pushed.append((state, enabled))) == "kana"

    async def handle_report(report: int) -> dict[str, bool]:
        return {"caps_lock": bool(report & 0x02)}

    writer = DummyWriter()
    await process_ctrl_json('{"t":"HOST_LED","report":2}', base_ctx(handle_report), writer)
    assert writer.data[-1] == {"t": "HOST_LED", "result": "ok", "report": 2, "changed": {"caps_lock": True}}

    await process_ctrl_json('{"t":"HOST_LED","report":999}', base_ctx(handle_report), writer)
    assert writer.data[-1]["result"] == "error"

    reloads = []
    ctx = base_ctx(handle_report)
    ctx.push_ledd_semantic_reload = lambda: reloads.append("semantic")
    await process_ctrl_json('{"t":"LEDD_RELOAD","target":"semantic_roles"}', ctx, writer)
    assert reloads == ["semantic"]
    assert writer.data[-1] == {"t": "LEDD_RELOAD", "result": "ok", "target": "semantic_roles"}

    try:
        normalize_host_led_output_config({"states": {"bad": True}})
    except ValueError:
        pass
    else:
        raise AssertionError("unknown host LED state should fail")

    print("ok: logicd host LED output mapping")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
