#!/usr/bin/env python3
"""Tests for LED semantic role normalization and ledd runtime integration."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from ledd.direct_frame import decode_direct_frame, encode_direct_frame  # noqa: E402
from ledd.ledd import AnimationManager  # noqa: E402
from ledd.ledd import _default_layer_overlay_color  # noqa: E402
from ledd.logicd_client import handle_logicd_message  # noqa: E402
from ledd.semantic_roles import (
    canonical_keycode,
    infer_role_from_keycode,
    keymap_json_to_base_keycodes,
    lock_state_for_keycode,
    normalize_led_semantic_role_config,
)
from ledd.strip import Color  # noqa: E402


class FakeStrip:
    def __init__(self, n: int) -> None:
        self.pixels = [0] * n
        self.show_count = 0

    def setPixelColor(self, idx: int, color: int) -> None:
        self.pixels[idx] = color

    def show(self) -> None:
        self.show_count += 1


def _make_manager() -> AnimationManager:
    positions = {
        "0,0": {"x": 0, "y": 0},
        "0,1": {"x": 1, "y": 0},
        "0,2": {"x": 2, "y": 0},
        "0,3": {"x": 3, "y": 0},
    }
    return AnimationManager(
        FakeStrip(4),
        4,
        {
            "leds": positions,
            "keycodes_by_position": {
                "0,0": "KC_LCTL",
                "0,1": "KC_A",
                "0,2": "LT(1,KC_SPACE)",
                "0,3": "KC_CAPS",
            },
            "semantic_roles": {
                "state_overlays": {
                    "layer_1": {"keys": ["LT(1,KC_SPACE)"], "color": [0, 50, 90], "priority": 30},
                    "caps_lock": {"keys": ["KC_CAPS"], "color": [0, 0, 90], "priority": 40},
                    "alert": {"keys": ["KC_CAPS"], "color": [90, 0, 0], "priority": 90},
                },
                "reactive": {"exclude_roles": ["modifier", "function", "layer", "lock"]},
            },
            "animation": {"default_id": 0},
            "ipc": {"direct_frame_fallback": "restore_default"},
        },
        positions,
    )


def _test_normalization() -> None:
    assert canonical_keycode("KC_NLCK") == "KC_NUMLOCK"
    assert canonical_keycode("KC_SLCK") == "KC_SCROLLLOCK"
    assert lock_state_for_keycode("KC_CAPS") == "caps_lock"
    assert lock_state_for_keycode("KC_NLCK") == "num_lock"
    assert lock_state_for_keycode("KC_SLCK") == "scroll_lock"
    assert infer_role_from_keycode("KC_LCTL") == "modifier"
    assert infer_role_from_keycode("KC_F12") == "function"
    assert infer_role_from_keycode("MO(1)") == "layer"
    assert infer_role_from_keycode("LT(1,KC_SPACE)") == "layer"
    assert infer_role_from_keycode("KC_CAPS") == "lock"
    assert infer_role_from_keycode("KC_CAPSLOCK") == "lock"
    assert infer_role_from_keycode("KC_NLCK") == "lock"
    assert infer_role_from_keycode("KC_SH10") == "script"
    assert infer_role_from_keycode("BT_POWER_OFF") == "system"
    assert infer_role_from_keycode("KC_BTN1") == "normal"
    assert infer_role_from_keycode("KC_A") == "normal"

    cfg = normalize_led_semantic_role_config({
        "roles": {"KC_A": "function", "KC_LCTL": "modifier"},
        "state_overlays": {
            "ctrl_lock": {"keys": ["KC_LCTL"], "color": [0, 0, 80], "priority": 45},
            "alert": {"keys": ["KC_LCTL"], "color": [80, 0, 0], "effect_blend": "max", "priority": 90},
        },
        "reactive": {"exclude_roles": ["modifier", "function", "layer", "lock"]},
        "overlay_priority": {"lock": 45},
    })
    assert cfg.role_for_keycode("KC_A") == "function"
    assert cfg.role_for_keycode("KC_B") == "normal"
    assert not cfg.reactive_enabled_for_keycode("KC_A")
    assert cfg.reactive_enabled_for_keycode("KC_B")
    assert cfg.state_overlays["ctrl_lock"]["color"] == [0, 0, 80]
    assert cfg.overlay_priority["lock"] == 45
    assert cfg.overlay_priority_for_keycode("KC_A") == 20
    assert cfg.restore_color_for_keycode("KC_LCTL", {"ctrl_lock"}) == [0, 0, 80]
    assert cfg.restore_color_for_keycode("KC_LCTL", {"ctrl_lock", "alert"}) == [80, 0, 0]
    assert cfg.blended_color_for_position("0,0", "KC_LCTL", {"alert"}, [10, 20, 30]) == [80, 20, 30]
    assert cfg.restore_color_for_keycode("KC_A", {"ctrl_lock"}) is None
    assert cfg.fallback_internal_lock_toggle is False

    fallback_lock_cfg = normalize_led_semantic_role_config({"fallback_internal_lock_toggle": True})
    assert fallback_lock_cfg.fallback_internal_lock_toggle is True

    modifier_reactive_cfg = normalize_led_semantic_role_config({
        "reactive": {"modifier_triggers_effects": True},
    })
    assert modifier_reactive_cfg.reactive_enabled_for_keycode("KC_LCTL")
    assert not modifier_reactive_cfg.reactive_enabled_for_keycode("KC_F1")

    modifier_excluded_cfg = normalize_led_semantic_role_config({
        "reactive": {"exclude_roles": ["function"], "modifier_triggers_effects": False},
    })
    assert not modifier_excluded_cfg.reactive_enabled_for_keycode("KC_LCTL")
    assert not modifier_excluded_cfg.reactive_enabled_for_keycode("KC_F1")

    lang_layer_tap_cfg = normalize_led_semantic_role_config({
        "roles": {"LT(1,KC_LANG2)": "normal", "LT(2,KC_LANG1)": "normal"},
        "reactive": {"exclude_roles": ["function", "layer", "lock"], "modifier_triggers_effects": True},
    })
    assert lang_layer_tap_cfg.reactive_enabled_for_keycode("LT(1,KC_LANG2)")
    assert lang_layer_tap_cfg.reactive_enabled_for_keycode("LT(2,KC_LANG1)")
    assert not lang_layer_tap_cfg.reactive_enabled_for_keycode("MO(1)")

    lock_cfg = normalize_led_semantic_role_config({
        "lock_indicators": {
            "blend": "max",
            "states": {
                "caps_lock": {
                    "follow_keys": True,
                    "extra_leds": ["0,0"],
                    "color": [255, 0, 0],
                    "key_colors": {"KC_CAPS": [120, 80, 0]},
                },
                "num_lock": {
                    "follow_keys": True,
                    "extra_leds": ["0,0"],
                    "color": [0, 0, 255],
                },
            },
        }
    })
    assert lock_cfg.overlay_blend == "max"
    assert lock_cfg.state_overlays["caps_lock"]["keys"] == ["KC_CAPSLOCK"]
    assert lock_cfg.restore_color_for_position("0,1", "KC_CAPS", {"caps_lock"}) == [120, 80, 0]
    assert lock_cfg.restore_color_for_position("0,0", "KC_A", {"caps_lock", "num_lock"}) == [255, 0, 255]

    base = keymap_json_to_base_keycodes({
        "_layout_def": {"main": [[0, 0, "SW1"], [0, 1, "SW2"]]},
        "layers": [{"main": ["KC_A", "KC_LCTL"]}],
    })
    assert base == {"0,0": "KC_A", "0,1": "KC_LCTL"}

    for bad in [
        {"roles": {"KC_A": "bad"}},
        {"state_overlays": {"x": {"keys": ["KC_A"], "color": [999, 0, 0]}}},
        {"state_overlays": {"x": {"keys": ["KC_A"], "color": [0, 0, 0], "effect_blend": "bad"}}},
        {"state_overlays": {"x": {"keys": ["KC_A"], "color": [0, 0, 0], "effect_alpha": 2}}},
        {"reactive": {"exclude_roles": ["bad"]}},
    ]:
        try:
            normalize_led_semantic_role_config(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for {bad}")


def _test_runtime_reactive_excludes_semantic_roles() -> None:
    manager = _make_manager()
    manager._vialrgb_mode = 31
    manager.on_key_event(0, 0, True)  # modifier
    manager.on_key_event(0, 2, True)  # layer key
    manager.on_key_event(0, 3, True)  # lock key
    assert manager._vialrgb_reactive_hits == []
    manager.on_key_event(0, 1, True)  # normal key
    assert len(manager._vialrgb_reactive_hits) == 1
    assert manager._vialrgb_reactive_hits[0]["idx"] == 1


def _test_runtime_state_overlay_priority_and_restore() -> None:
    manager = _make_manager()
    render_strip = manager._strip
    raw_strip = manager._raw_strip
    for idx in range(4):
        render_strip.setPixelColor(idx, Color(1, 2, 3))
    render_strip.show()
    manager.set_active_layer(1)
    assert raw_strip.pixels[2] == Color(0, 50, 90)

    manager.set_state_overlay("caps_lock", True)
    assert raw_strip.pixels[3] == Color(0, 0, 90)
    manager.set_state_overlay("alert", True)
    assert raw_strip.pixels[3] == Color(90, 0, 0)
    manager.set_state_overlay("alert", False)
    assert raw_strip.pixels[3] == Color(0, 0, 90)
    manager.set_state_overlay("caps_lock", False)
    assert raw_strip.pixels[3] == Color(1, 2, 3)
    manager.set_state_overlay("caps_lock", True)
    assert raw_strip.pixels[3] == Color(0, 0, 90)

    manager.on_key_event(0, 3, True)
    assert raw_strip.pixels[3] == Color(0, 0, 90)

    # Direct-frame restore_default should leave active state overlays visible
    # after the animation is restored.
    packet = encode_direct_frame(frame_id=1, led_count=4, payload=bytes([10, 20, 30] * 4))
    manager.apply_direct_frame(decode_direct_frame(packet, expected_led_count=4))
    called: list[int] = []

    def fake_switch(anim_id: int) -> bool:
        called.append(anim_id)
        manager._current_id = anim_id
        return True

    manager.switch = fake_switch  # type: ignore[method-assign]
    manager.on_direct_frame_producer_disconnected()
    assert called == [0]
    assert raw_strip.pixels[2] == Color(0, 50, 90)
    assert raw_strip.pixels[3] == Color(0, 0, 90)


def _test_layer_overlay_can_include_layer_changed_keys() -> None:
    positions = {
        "0,0": {"x": 0, "y": 0},
        "0,1": {"x": 1, "y": 0},
        "0,2": {"x": 2, "y": 0},
        "0,3": {"x": 3, "y": 0},
    }
    manager = AnimationManager(
        FakeStrip(4),
        4,
        {
            "leds": positions,
            "keycode_layers_by_position": [
                {"0,0": "LT(1,KC_LANG2)", "0,1": "KC_1", "0,2": "KC_2", "0,3": "KC_A"},
                {"0,0": "KC_TRNS", "0,1": "KC_F1", "0,2": "KC_DEL", "0,3": "KC_TRNS"},
            ],
            "semantic_roles": {
                "roles": {"LT(1,KC_LANG2)": "normal"},
                "state_overlays": {
                    "layer:1": {
                        "keys": ["LT(1,KC_LANG2)"],
                        "include_layer_changes": True,
                        "color": [0, 80, 0],
                        "effect_blend": "max",
                        "priority": 30,
                    },
                },
            },
            "animation": {"default_id": 0},
        },
        positions,
    )
    raw_strip = manager._raw_strip
    manager.on_layer_state([1, 0])
    assert raw_strip.pixels[0] == Color(0, 80, 0)
    assert raw_strip.pixels[1] == Color(0, 80, 0)
    assert raw_strip.pixels[2] == Color(0, 80, 0)
    assert raw_strip.pixels[3] == Color(0, 0, 0)

    manager._strip.setPixelColor(1, Color(90, 10, 20))
    manager._strip.show()
    assert raw_strip.pixels[1] == Color(90, 80, 20)

    manager.on_layer_state([0])
    assert raw_strip.pixels == [0, Color(90, 10, 20), 0, 0]


def _test_layer_overlays_are_created_for_added_layers() -> None:
    positions = {
        "0,0": {"x": 0, "y": 0},
        "0,1": {"x": 1, "y": 0},
        "0,2": {"x": 2, "y": 0},
    }
    manager = AnimationManager(
        FakeStrip(3),
        3,
        {
            "leds": positions,
            "keycode_layers_by_position": [
                {"0,0": "LT(2,KC_A)", "0,1": "KC_1", "0,2": "KC_2"},
                {"0,0": "KC_TRNS"},
                {"0,0": "KC_TRNS", "0,1": "KC_F1", "0,2": "KC_DEL"},
            ],
            "semantic_roles": {
                "roles": {"LT(2,KC_A)": "normal"},
            },
            "animation": {"default_id": 0},
        },
        positions,
    )
    assert "layer:2" in manager._semantic_roles.state_overlays
    manager.on_layer_state([2, 0])
    assert manager._raw_strip.pixels[0] == Color(0, 48, 120)
    assert manager._raw_strip.pixels[1] == Color(0, 48, 120)
    assert manager._raw_strip.pixels[2] == Color(0, 48, 120)

    override_manager = AnimationManager(
        FakeStrip(3),
        3,
        {
            "leds": positions,
            "keycode_layers_by_position": [
                {"0,0": "LT(2,KC_A)", "0,1": "KC_1", "0,2": "KC_2"},
                {"0,0": "KC_TRNS"},
                {"0,0": "KC_TRNS", "0,1": "KC_F1", "0,2": "KC_DEL"},
            ],
            "semantic_roles": {
                "roles": {"LT(2,KC_A)": "normal"},
                "state_overlays": {
                    "layer:2": {
                        "keys": ["LT(2,KC_A)"],
                        "include_layer_changes": True,
                        "color": [20, 30, 40],
                        "effect_blend": "replace",
                    },
                },
            },
            "animation": {"default_id": 0},
        },
        positions,
    )
    override_manager.on_layer_state([2, 0])
    assert override_manager._raw_strip.pixels[0] == Color(20, 30, 40)
    assert override_manager._raw_strip.pixels[1] == Color(20, 30, 40)
    assert override_manager._raw_strip.pixels[2] == Color(20, 30, 40)

    layer_exists_manager = AnimationManager(
        FakeStrip(3),
        3,
        {
            "leds": positions,
            "keycode_layers_by_position": [
                {"0,0": "KC_A", "0,1": "KC_1", "0,2": "KC_2"},
                {"0,0": "KC_TRNS"},
                {"0,0": "KC_TRNS", "0,1": "KC_F1", "0,2": "KC_DEL"},
            ],
            "semantic_roles": {},
            "animation": {"default_id": 0},
        },
        positions,
    )
    assert "layer:1" not in layer_exists_manager._semantic_roles.state_overlays
    assert "layer:2" in layer_exists_manager._semantic_roles.state_overlays
    layer_exists_manager.on_layer_state([2, 0])
    assert layer_exists_manager._raw_strip.pixels[0] == Color(0, 0, 0)
    assert layer_exists_manager._raw_strip.pixels[1] == Color(0, 48, 120)
    assert layer_exists_manager._raw_strip.pixels[2] == Color(0, 48, 120)


def _test_higher_active_layer_overlay_wins_same_priority() -> None:
    positions = {
        "0,0": {"x": 0, "y": 0},
        "0,1": {"x": 1, "y": 0},
    }
    manager = AnimationManager(
        FakeStrip(2),
        2,
        {
            "leds": positions,
            "keycode_layers_by_position": [
                {"0,0": "LT(1,KC_A)", "0,1": "KC_1"},
                {"0,0": "LT(2,KC_B)", "0,1": "KC_F1"},
                {"0,0": "KC_TRNS", "0,1": "KC_F2"},
            ],
            "semantic_roles": {
                "roles": {"LT(1,KC_A)": "normal", "LT(2,KC_B)": "normal"},
                "state_overlays": {
                    "layer:1": {
                        "keys": ["LT(1,KC_A)", "LT(2,KC_B)"],
                        "include_layer_changes": True,
                        "color": [0, 80, 0],
                        "priority": 30,
                    },
                    "layer:2": {
                        "keys": ["LT(2,KC_B)"],
                        "include_layer_changes": True,
                        "color": [0, 48, 120],
                        "priority": 30,
                    },
                },
            },
            "animation": {"default_id": 0},
        },
        positions,
    )
    manager.on_layer_state([1, 2, 0])
    assert manager._active_layers == [2, 1, 0]
    assert manager._raw_strip.pixels[0] == Color(0, 48, 120)
    assert manager._raw_strip.pixels[1] == Color(0, 48, 120)


def _test_default_layer_colors_are_predefined_and_cycle() -> None:
    assert _default_layer_overlay_color(1) == [0, 80, 0]
    assert _default_layer_overlay_color(2) == [0, 48, 120]
    assert _default_layer_overlay_color(6) == [120, 0, 48]
    assert _default_layer_overlay_color(7) == [0, 80, 0]


def _test_overlay_alpha_blends_with_effect_base() -> None:
    positions = {"0,0": {"x": 0, "y": 0}}
    manager = AnimationManager(
        FakeStrip(1),
        1,
        {
            "leds": positions,
            "keycode_layers_by_position": [{"0,0": "MO(1)"}],
            "semantic_roles": {
                "state_overlays": {
                    "layer:1": {
                        "keys": ["MO(1)"],
                        "color": [0, 100, 0],
                        "effect_blend": "alpha",
                        "effect_alpha": 0.25,
                        "priority": 30,
                    },
                },
            },
            "animation": {"default_id": 0},
        },
        positions,
    )
    manager._strip.setPixelColor(0, Color(100, 20, 60))
    manager._strip.show()
    manager.on_layer_state([1, 0])
    assert manager._raw_strip.pixels[0] == Color(75, 40, 45)


def _test_runtime_lock_fallback_toggle_is_explicit() -> None:
    manager = _make_manager()
    raw_strip = manager._raw_strip
    manager._vialrgb_mode = 31
    manager.on_key_event(0, 3, True)
    assert raw_strip.pixels[3] == Color(0, 0, 0)
    assert manager._vialrgb_reactive_hits == []

    manager._semantic_roles = normalize_led_semantic_role_config({
        "state_overlays": {
            "caps_lock": {"keys": ["KC_CAPS"], "color": [0, 0, 90], "priority": 40},
        },
        "reactive": {"exclude_roles": ["modifier", "function", "layer", "lock"]},
        "fallback_internal_lock_toggle": True,
    })
    manager.on_key_event(0, 3, True)
    assert raw_strip.pixels[3] == Color(0, 0, 90)
    manager.on_key_event(0, 3, True)
    assert raw_strip.pixels[3] == Color(0, 0, 0)


def _test_runtime_lock_alias_blend_and_active_layer() -> None:
    positions = {
        "0,0": {"x": 0, "y": 0},
        "0,1": {"x": 1, "y": 0},
        "0,2": {"x": 2, "y": 0},
    }
    manager = AnimationManager(
        FakeStrip(3),
        3,
        {
            "leds": positions,
            "keycode_layers_by_position": [
                {"0,0": "KC_CAPS", "0,1": "KC_A", "0,2": "KC_TRNS"},
                {"0,0": "KC_TRNS", "0,1": "KC_NLCK", "0,2": "KC_SLCK"},
            ],
            "semantic_roles": {
                "lock_indicators": {
                    "blend": "max",
                    "states": {
                        "caps_lock": {
                            "follow_keys": True,
                            "extra_leds": ["0,2"],
                            "color": [255, 0, 0],
                        },
                        "num_lock": {
                            "follow_keys": True,
                            "extra_leds": ["0,2"],
                            "color": [0, 0, 255],
                        },
                        "scroll_lock": {
                            "follow_keys": True,
                            "extra_leds": ["0,2"],
                            "color": [0, 255, 0],
                        },
                    },
                },
                "reactive": {"exclude_roles": ["modifier", "function", "layer", "lock"]},
            },
            "animation": {"default_id": 0},
        },
        positions,
    )
    raw_strip = manager._raw_strip
    manager.set_state_overlay("caps_lock", True)
    assert raw_strip.pixels[0] == Color(255, 0, 0)
    assert raw_strip.pixels[2] == Color(255, 0, 0)

    manager.set_state_overlay("num_lock", True)
    assert raw_strip.pixels[1] == Color(0, 0, 0)
    assert raw_strip.pixels[2] == Color(255, 0, 255)
    manager.on_layer_state([1, 0])
    assert raw_strip.pixels[1] == Color(0, 0, 255)
    assert raw_strip.pixels[2] == Color(255, 0, 255)
    manager.set_state_overlay("scroll_lock", True)
    assert raw_strip.pixels[2] == Color(255, 255, 255)
    manager.on_key_event(0, 1, True)
    assert manager._vialrgb_reactive_hits == []


def _test_runtime_semantic_reload() -> None:
    positions = {"0,0": {"x": 0, "y": 0}, "0,1": {"x": 1, "y": 0}}
    manager = AnimationManager(
        FakeStrip(2),
        2,
        {
            "leds": positions,
            "keycode_layers_by_position": [{"0,0": "KC_CAPS", "0,1": "KC_A"}],
            "semantic_roles": {
                "lock_indicators": {
                    "blend": "max",
                    "states": {
                        "caps_lock": {"follow_keys": True, "color": [255, 0, 0]},
                    },
                },
            },
            "animation": {"default_id": 0},
        },
        positions,
    )
    raw_strip = manager._raw_strip
    manager.set_state_overlay("caps_lock", True)
    assert raw_strip.pixels[0] == Color(255, 0, 0)

    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "ledd.json"
        config_path.write_text("{", encoding="utf-8")
        assert manager.reload_semantic_roles(config_path) is False
        assert raw_strip.pixels[0] == Color(255, 0, 0)

        config_path.write_text(json.dumps({
            "led": {"gpio_bcm": 12, "brightness": 64, "color_order": "GRB"},
            "leds": positions,
            "keycode_layers_by_position": [{"0,0": "KC_A", "0,1": "KC_NLCK"}],
            "semantic_roles": {
                "state_overlays": {},
                "lock_indicators": {
                    "blend": "max",
                    "states": {
                        "num_lock": {"follow_keys": True, "color": [0, 0, 255]},
                    },
                },
            },
            "animation": {"default_id": 0},
        }), encoding="utf-8")
        assert manager.reload_semantic_roles(config_path) is True
        assert "caps_lock" not in manager._active_semantic_states
        manager.set_state_overlay("num_lock", True)
        assert raw_strip.pixels[1] == Color(0, 0, 255)


def _test_logicd_state_messages() -> None:
    manager = _make_manager()
    render_strip = manager._strip
    raw_strip = manager._raw_strip
    for idx in range(4):
        render_strip.setPixelColor(idx, Color(1, 2, 3))
    render_strip.show()

    handle_logicd_message('{"t":"layer","layer":1}', manager)
    assert raw_strip.pixels[2] == Color(0, 50, 90)
    handle_logicd_message('{"t":"layer","layer":0}', manager)
    assert raw_strip.pixels[2] == Color(1, 2, 3)

    handle_logicd_message('{"t":"led_state","state":"alert","active":true}', manager)
    assert raw_strip.pixels[3] == Color(90, 0, 0)
    handle_logicd_message('{"t":"lock_state","name":"alert","on":false}', manager)
    assert raw_strip.pixels[3] == Color(1, 2, 3)


def main() -> None:
    _test_normalization()
    _test_runtime_reactive_excludes_semantic_roles()
    _test_runtime_state_overlay_priority_and_restore()
    _test_layer_overlay_can_include_layer_changed_keys()
    _test_layer_overlays_are_created_for_added_layers()
    _test_higher_active_layer_overlay_wins_same_priority()
    _test_default_layer_colors_are_predefined_and_cycle()
    _test_overlay_alpha_blends_with_effect_base()
    _test_runtime_lock_fallback_toggle_is_explicit()
    _test_runtime_lock_alias_blend_and_active_layer()
    _test_runtime_semantic_reload()
    _test_logicd_state_messages()
    print("ok: LED semantic roles")


if __name__ == "__main__":
    main()
