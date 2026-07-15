#!/usr/bin/env python3
"""Smoke tests for Dynamic Macro / Leader groundwork helpers."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.dynamic_macro_leader import (  # noqa: E402
    DynamicMacroRuntime,
    LeaderRuntime,
    dynamic_macro_record_filter,
    validate_leader_settings,
)


def main() -> None:
    assert dynamic_macro_record_filter("KC_A")["recordable"]
    assert dynamic_macro_record_filter("S(KC_A)")["recordable"]
    assert dynamic_macro_record_filter("U+3042")["recordable"]
    assert dynamic_macro_record_filter("MS_BTN1")["recordable"]
    assert dynamic_macro_record_filter("DM_REC1")["reason"] == "dynamic_macro_control"
    assert dynamic_macro_record_filter("SCRIPT(foo)")["reason"] == "script_action"
    assert dynamic_macro_record_filter("BT_POWER_OFF")["reason"] == "connectivity_action"
    assert dynamic_macro_record_filter("MO(1)")["reason"] == "layer_action"

    runtime = DynamicMacroRuntime(max_actions_per_slot=2)
    started = runtime.handle_control("DM_REC1")
    assert started["accepted"] and started["state"] == "recording" and started["active_slot"] == 1
    assert runtime.record_action("KC_A")["accepted"]
    rejected = runtime.record_action("SCRIPT(foo)")
    assert not rejected["accepted"]
    assert rejected["reason"] == "script_action"
    assert runtime.record_action("KC_B")["accepted"]
    assert runtime.record_action("KC_C")["reason"] == "slot_full"
    stopped = runtime.handle_control("DM_RSTP")
    assert stopped["accepted"] and stopped["state"] == "idle"

    playback = runtime.handle_control("DM_PLY1")
    assert playback["accepted"]
    assert playback["state"] == "playing"
    assert playback["actions"] == ("KC_A", "KC_B")
    assert runtime.handle_control("DM_PLY1")["reason"] == "playback_active"
    assert runtime.finish_playback()["accepted"]
    assert runtime.handle_control("DM_PLY2")["reason"] == "empty_slot"

    runtime.handle_control("DM_REC2")
    runtime.record_action("KC_X")
    cancelled = runtime.cancel("output_switch")
    assert cancelled["accepted"]
    assert cancelled["last_cancel_reason"] == "output_switch"
    assert cancelled["slot_lengths"] == {1: 0, 2: 0}
    assert not cancelled["persistent"]
    assert not cancelled["sends_hid_reports"]

    disabled = validate_leader_settings({})
    assert disabled["default_disabled"]
    assert disabled["valid"]

    invalid = validate_leader_settings({
        "enabled": True,
        "timeout": 99,
        "sequences": {"KC_A": "SCRIPT(foo)"},
    })
    assert not invalid["valid"]
    assert "leader_timeout_out_of_range" in invalid["errors"]
    assert "invalid_leader_action:KC_A" in invalid["errors"]

    leader = LeaderRuntime({
        "enabled": True,
        "timeout": 0.5,
        "sequences": {
            "KC_A,KC_B": "KC_ESC",
            "KC_C": "KC_TAB",
        },
    })
    assert leader.start(10.0)["accepted"]
    progress = leader.input_action("KC_A", 10.1)
    assert progress["accepted"] and progress["event"] == "leader_progress"
    matched = leader.input_action("KC_B", 10.2)
    assert matched["accepted"]
    assert matched["event"] == "leader_matched"
    assert matched["action"] == "KC_ESC"

    leader.start(20.0)
    timeout = leader.input_action("KC_A", 20.6)
    assert timeout["event"] == "leader_cancelled"
    assert timeout["reason"] == "timeout"

    leader.start(30.0)
    cancelled = leader.input_action("MO(1)", 30.1)
    assert cancelled["reason"] == "non_recordable_action"
    assert not cancelled["pending"]
    assert not cancelled["sends_hid_reports"]

    print("ok: Dynamic Macro / Leader runtime groundwork helpers")


if __name__ == "__main__":
    main()
