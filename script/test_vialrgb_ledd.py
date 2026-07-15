#!/usr/bin/env python3
"""Local smoke test for ledd VialRGB mode handling."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from ledd.ledd import (  # noqa: E402
    AnimationManager,
    _handle_logicd_message,
    apply_startup_effect,
    startup_effect_config,
)


class FakeStrip:
    def __init__(self, count: int) -> None:
        self.leds = [0] * count
        self.show_count = 0

    def setPixelColor(self, idx: int, color: int) -> None:
        self.leds[idx] = color

    def show(self) -> None:
        self.show_count += 1


def main() -> None:
    assert startup_effect_config({})["mode"] == 6
    assert startup_effect_config({"startup_effect": None}) == {"enabled": False}
    invalid_effect = startup_effect_config({"startup_effect": {"speed": "bad", "v": "9"}})
    assert invalid_effect["speed"] == 48
    assert invalid_effect["v"] == 9

    startup_strip = FakeStrip(3)
    startup_manager = AnimationManager(startup_strip, 3, {"animation": {"fps": 30}}, {})
    assert apply_startup_effect(
        startup_manager,
        {"startup_effect": {"mode": 6, "speed": 64, "h": 1, "s": 2, "v": 32}},
    )
    assert startup_manager._vialrgb_mode == 6
    assert startup_manager._vialrgb_hsv == (1, 2, 32)
    startup_manager.stop()

    startup_only_manager = AnimationManager(
        FakeStrip(2),
        2,
        {"animation": {"fps": 30}, "semantic_roles": {"load_keymap_on_startup": False}},
        {"0,0": {"x": 0.0, "y": 0.0}, "0,1": {"x": 1.0, "y": 0.0}},
    )
    assert startup_only_manager._keycode_layers_by_position == []
    _handle_logicd_message(
        '{"t":"semantic_keymap","layers":[{"0,0":"KC_LSFT","0,1":"KC_A"},{"0,1":"KC_B"}]}',
        startup_only_manager,
    )
    assert startup_only_manager.keycode_for_position("0,0") == "KC_LSFT"
    startup_only_manager.on_layer_state([1, 0])
    assert startup_only_manager.keycode_for_position("0,1") == "KC_B"
    _handle_logicd_message(
        '{"t":"semantic_roles","semantic_roles":{"roles":{"KC_B":"function"},"reactive":{"exclude_roles":["function"]}}}',
        startup_only_manager,
    )
    assert startup_only_manager._semantic_roles.role_for_keycode("KC_B") == "function"
    assert not startup_only_manager._semantic_roles.reactive_enabled_for_keycode("KC_B")
    startup_only_manager.stop()

    strip = FakeStrip(4)
    manager = AnimationManager(strip, 4, {"animation": {"fps": 30}}, {})

    manager.apply_vialrgb(2, 128, 0, 255, 32)
    low = list(strip.leds)
    assert len(set(low)) == 1
    assert low[0] != 0
    assert manager._color_from_hsv(0, 255, 32) == low[0]
    assert manager._vialrgb_color_cache[(0, 255, 32)] == low[0]

    manager.apply_vialrgb(2, 128, 0, 255, 192)
    high = list(strip.leds)
    assert len(set(high)) == 1
    assert high[0] != low[0]

    manager.apply_vialrgb(1, 128, 0, 0, 0)
    assert strip.leds == [0, 0, 0, 0]
    manager.apply_vialrgb_direct(1, [[0, 255, 64], [85, 255, 64]])
    assert strip.leds[1] != 0
    assert strip.leds[2] != 0
    assert strip.leds[0] == 0

    manager_with_positions = AnimationManager(
        strip,
        4,
        {
            "animation": {"fps": 30},
            "bt_indicator": {
                "top": ["0,0", "0,1", "0,2", "0,3"],
                "digits": ["0,1", "0,2", "0,3"],
            },
        },
        {
            "0,0": {"x": 0.0, "y": 0.0},
            "0,1": {"x": 10.0, "y": 0.0},
            "0,2": {"x": 20.0, "y": 0.0},
            "0,3": {"x": 30.0, "y": 0.0},
        },
    )
    manager_with_positions.apply_vialrgb(31, 128, 80, 255, 128)
    manager_with_positions.on_key_event(0, 1, True)
    time.sleep(0.05)
    assert strip.leds[1] != strip.leds[0]

    semantic_strip = FakeStrip(2)
    semantic_manager = AnimationManager(
        semantic_strip,
        2,
        {
            "animation": {"fps": 30},
            "keycode_by_led_key": {"0,0": "KC_LCTL", "0,1": "KC_A"},
            "semantic_roles": {
                "state_overlays": {
                    "ctrl_lock": {"keys": ["KC_LCTL"], "color": [0, 0, 80], "priority": 45},
                    "layer:1": {"keys": ["KC_A"], "color": [0, 80, 0], "priority": 30},
                },
            },
        },
        {
            "0,0": {"x": 0.0, "y": 0.0},
            "0,1": {"x": 10.0, "y": 0.0},
        },
    )
    semantic_manager.apply_vialrgb(31, 128, 80, 255, 128)
    semantic_manager.on_key_event(0, 0, True)
    time.sleep(0.05)
    assert not semantic_manager._vialrgb_reactive_hits
    semantic_manager.set_semantic_overlay_state("ctrl_lock", True)
    semantic_manager.on_layer_state([1, 0])
    semantic_manager.on_key_event(0, 1, True)
    time.sleep(0.05)
    assert semantic_strip.leds[0] == semantic_manager._semantic_overlay_color_for_index(0)
    assert semantic_manager._semantic_overlay_color_for_index(1) is not None
    semantic_manager.stop()

    alphas_mods_strip = FakeStrip(4)
    alphas_mods_manager = AnimationManager(
        alphas_mods_strip,
        4,
        {
            "animation": {"fps": 30},
            "keycode_by_led_key": {
                "0,0": "KC_A",
                "0,1": "KC_1",
                "0,2": "KC_F1",
                "0,3": "KC_LCTL",
            },
        },
        {
            "0,0": {"x": 0.0, "y": 0.0},
            "0,1": {"x": 10.0, "y": 0.0},
            "0,2": {"x": 20.0, "y": 0.0},
            "0,3": {"x": 30.0, "y": 0.0},
        },
    )
    alphas_mods_manager.apply_vialrgb(3, 128, 0, 255, 128)
    time.sleep(0.05)
    alpha_color = alphas_mods_manager._color_from_hsv(0, 255, 128)
    mods_color = alphas_mods_manager._color_from_hsv(96, 255, 96)
    assert alphas_mods_strip.leds[0] == alpha_color
    assert alphas_mods_strip.leds[1:] == [mods_color, mods_color, mods_color]
    alphas_mods_manager.stop()

    manager_with_positions.apply_vialrgb(40, 128, 80, 255, 128)
    manager_with_positions.on_key_event(0, 1, True)
    time.sleep(0.05)
    assert any(color != 0 for color in strip.leds)

    idle_strip = FakeStrip(4)
    idle_manager = AnimationManager(
        idle_strip,
        4,
        {"animation": {"fps": 30}},
        {
            "0,0": {"x": 0.0, "y": 0.0},
            "0,1": {"x": 10.0, "y": 0.0},
            "0,2": {"x": 20.0, "y": 0.0},
            "0,3": {"x": 30.0, "y": 0.0},
        },
    )
    idle_manager.apply_vialrgb(40, 128, 80, 255, 128)
    time.sleep(0.12)
    idle_shows = idle_strip.show_count
    assert idle_shows <= 2
    idle_manager.on_key_event(0, 1, True)
    time.sleep(0.05)
    assert idle_strip.show_count > idle_shows
    idle_manager.stop()

    reactive_idle_strip = FakeStrip(4)
    reactive_idle_manager = AnimationManager(
        reactive_idle_strip,
        4,
        {"animation": {"fps": 30}},
        {
            "0,0": {"x": 0.0, "y": 0.0},
            "0,1": {"x": 10.0, "y": 0.0},
            "0,2": {"x": 20.0, "y": 0.0},
            "0,3": {"x": 30.0, "y": 0.0},
        },
    )
    reactive_idle_manager.apply_vialrgb(31, 128, 80, 255, 128)
    time.sleep(0.12)
    reactive_idle_shows = reactive_idle_strip.show_count
    assert reactive_idle_strip.leds == [0, 0, 0, 0]
    assert reactive_idle_shows <= 2
    reactive_idle_manager.on_key_event(0, 1, True)
    time.sleep(0.05)
    assert reactive_idle_strip.show_count > reactive_idle_shows
    assert reactive_idle_strip.leds[1] != 0
    reactive_idle_manager.stop()

    overlay_idle_strip = FakeStrip(2)
    overlay_idle_manager = AnimationManager(
        overlay_idle_strip,
        2,
        {
            "leds": {"0,0": {"x": 0, "y": 0}, "0,1": {"x": 1, "y": 0}},
            "keycode_layers_by_position": [{"0,0": "KC_CAPS", "0,1": "KC_A"}],
            "semantic_roles": {
                "state_overlays": {
                    "caps_lock": {"keys": ["KC_CAPS"], "color": [0, 0, 90]},
                },
                "reactive": {"exclude_roles": ["lock"]},
            },
            "animation": {"fps": 30},
        },
        {"0,0": {"x": 0, "y": 0}, "0,1": {"x": 1, "y": 0}},
    )
    overlay_idle_manager.apply_vialrgb(31, 128, 80, 255, 128)
    time.sleep(0.12)
    overlay_idle_manager.set_state_overlay("caps_lock", True)
    time.sleep(0.05)
    assert overlay_idle_strip.leds[0] != 0
    overlay_idle_manager.set_state_overlay("caps_lock", False)
    time.sleep(0.05)
    assert overlay_idle_strip.leds == [0, 0]
    overlay_idle_manager.stop()

    for mode in (39, 41, 42):
        manager_with_positions.apply_vialrgb(mode, 128, 80, 255, 128)
        manager_with_positions.on_key_event(0, 1, True)
        time.sleep(0.05)
        assert any(color != 0 for color in strip.leds)

    manager.apply_vialrgb(6, 64, 0, 255, 96)
    time.sleep(0.08)
    assert strip.show_count > 0
    manager.apply_vialrgb_direct_pattern("rainbow", 20.0, 96)
    time.sleep(0.08)
    assert manager._vialrgb_mode == 1
    assert manager._vialrgb_direct_pattern["pattern"] == "rainbow"
    assert any(color != 0 for color in strip.leds)
    before_bad_pattern = dict(manager._vialrgb_direct_pattern)
    manager.apply_vialrgb_direct_pattern("bad", 20.0, 96)
    assert manager._vialrgb_direct_pattern == before_bad_pattern
    manager.apply_vialrgb(13, 64, 0, 255, 96)
    time.sleep(0.08)
    assert strip.show_count > 0
    manager.apply_vialrgb(0, 128, 0, 0, 0)

    for mode in (3, 4, 5, 7, 8, 9, 10, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 30, 43, 44):
        manager_with_positions.apply_vialrgb(mode, 64, 0, 255, 96)
        time.sleep(0.08)
        assert strip.show_count > 0

    for mode in (29, 32, 33, 34, 35, 36, 37, 38):
        manager_with_positions.apply_vialrgb(mode, 128, 80, 255, 128)
        manager_with_positions.on_key_event(0, 1, True)
        time.sleep(0.05)
        assert any(color != 0 for color in strip.leds)

    life_strip = FakeStrip(9)
    life_positions = {
        f"{row},{col}": {"x": col * 10.0, "y": row * 10.0}
        for row in range(3)
        for col in range(3)
    }
    life_manager = AnimationManager(life_strip, 9, {"animation": {"fps": 30}}, life_positions)
    life_manager.apply_vialrgb(1001, 128, 100, 255, 128)
    time.sleep(0.05)
    idle_life = list(life_strip.leds)
    before_life_show = life_strip.show_count
    life_manager.on_key_event(1, 1, True)
    time.sleep(0.05)
    assert life_strip.show_count > before_life_show
    assert any(color != idle_life[idx] for idx, color in enumerate(life_strip.leds))
    assert life_manager._vialrgb_life_game.alive_count == 0
    assert life_manager._vialrgb_life_game.transition_frame(9)[4] == "pending"
    life_manager.stop()

    banner_strip = FakeStrip(70)
    banner_positions = {
        f"{row},{col}": {"x": col * 10.0, "y": row * 10.0}
        for row in range(7)
        for col in range(10)
    }
    banner_manager = AnimationManager(
        banner_strip,
        70,
        {
            "animation": {"fps": 30},
            "keycode_by_led_key": {"3,9": "KC_A", "3,8": "KC_ENTER", "3,7": "KC_LCTL", "3,6": "KC_F1"},
        },
        banner_positions,
    )
    banner_manager.apply_vialrgb(1003, 255, 180, 255, 128)
    time.sleep(0.05)
    before_banner_show = banner_strip.show_count
    banner_manager.on_key_event(3, 9, True)
    time.sleep(0.12)
    assert banner_strip.show_count > before_banner_show
    assert any(color != 0 for color in banner_strip.leds)
    before_enter_columns = list(banner_manager._vialrgb_key_banner_columns)
    before_enter_splashes = len(banner_manager._vialrgb_splashes)
    banner_manager.on_key_event(3, 8, True)
    assert banner_manager._vialrgb_key_banner_columns == before_enter_columns
    assert len(banner_manager._vialrgb_splashes) == before_enter_splashes + 1
    before_modifier_columns = list(banner_manager._vialrgb_key_banner_columns)
    before_modifier_splashes = len(banner_manager._vialrgb_splashes)
    banner_manager.on_key_event(3, 7, True)
    assert banner_manager._vialrgb_key_banner_columns == before_modifier_columns
    assert len(banner_manager._vialrgb_splashes) == before_modifier_splashes + 1
    before_function_columns = list(banner_manager._vialrgb_key_banner_columns)
    before_function_splashes = len(banner_manager._vialrgb_splashes)
    banner_manager.on_key_event(3, 6, True)
    assert banner_manager._vialrgb_key_banner_columns == before_function_columns
    assert len(banner_manager._vialrgb_splashes) == before_function_splashes + 1
    before_modifier_show = banner_strip.show_count
    time.sleep(0.12)
    assert banner_strip.show_count > before_modifier_show
    banner_manager.stop()

    manager_with_positions.apply_vialrgb(0, 128, 0, 0, 0)
    assert strip.leds == [0, 0, 0, 0]

    before = list(strip.leds)
    manager.apply_vialrgb(999, 300, -1, 999, -20)
    assert manager._vialrgb_speed == 255
    assert manager._vialrgb_hsv == (0, 255, 0)
    assert strip.leds == before

    manager.apply_vialrgb_direct(-1, [[0, 255, 64]])
    assert strip.leds == before
    manager.apply_vialrgb_direct(3, [[0, 255, 64], ["bad"], [85, 255, 64]])
    assert strip.leds[3] != 0

    _handle_logicd_message("{", manager)
    _handle_logicd_message("[1, 2]", manager)
    _handle_logicd_message('{"t":"mode","mode":"gadget"}', manager)
    _handle_logicd_message('{"t":"key","kind":"X","row":0,"col":0}', manager)
    _handle_logicd_message('{"t":"key","kind":"P","row":"bad","col":0}', manager)
    _handle_logicd_message('{"t":"anim","id":"bad"}', manager)
    _handle_logicd_message('{"t":"vialrgb","mode":2,"speed":"bad","h":0,"s":0,"v":0}', manager)
    _handle_logicd_message('{"t":"semantic_roles","semantic_roles":[]}', manager)
    _handle_logicd_message('{"t":"vialrgb_direct","first":0,"pixels":[[1,2]]}', manager)
    _handle_logicd_message('{"t":"vialrgb_direct_pattern","pattern":"pulse","fps":12,"brightness":80}', manager)
    assert manager._vialrgb_direct_pattern["pattern"] == "pulse"
    manager_with_positions.apply_vialrgb(6, 64, 0, 255, 96)
    time.sleep(0.08)
    assert manager_with_positions._thread is not None
    assert manager_with_positions._thread.is_alive()
    _handle_logicd_message('{"t":"bt_pairing","phase":"pairing"}', manager_with_positions)
    time.sleep(0.12)
    assert any(color != 0 for color in strip.leds)
    _handle_logicd_message('{"t":"bt_pairing","phase":"passkey","digits":"12"}', manager_with_positions)
    time.sleep(0.12)
    assert strip.leds[1] != 0
    assert strip.leds[2] != 0
    _handle_logicd_message('{"t":"bt_pairing","phase":"off"}', manager_with_positions)
    time.sleep(0.12)
    assert manager_with_positions._vialrgb_mode == 6
    assert manager_with_positions._thread is not None
    assert manager_with_positions._thread.is_alive()
    manager_with_positions.stop()
    _handle_logicd_message('{"t":"unknown"}', manager)

    print("ok: ledd VialRGB modes update the strip")


if __name__ == "__main__":
    main()
