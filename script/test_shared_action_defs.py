#!/usr/bin/env python3
"""Regression tests for logicd.shared_action_defs."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.layer_action import parse_layer_action  # noqa: E402
from logicd.shared_action_defs import (  # noqa: E402
    is_animation_action,
    is_layer_action,
    is_layer_action_in_range,
    is_macro_action,
    is_script_action,
    is_unicode_action,
    is_wrapper_action,
    parse_shared_layer_action,
    shared_layer_actions,
    shared_modifier_wrappers,
    shared_vial_custom_action_map,
    shared_vial_custom_actions,
    shared_vial_layer_action_bases,
)


def main() -> None:
    wrappers = set(shared_modifier_wrappers())
    assert "S" in wrappers
    assert "LCTL" in wrappers
    assert "RGUI" in wrappers

    layers = set(shared_layer_actions())
    assert layers == {"MO", "TG", "TO", "DF", "OSL", "QK_LAYER_LOCK", "QK_LLCK"}

    for action in ("MO", "TG", "TO", "DF", "OSL"):
        parsed = parse_layer_action(f"{action}(1)")
        assert parsed == (action, 1)
        assert parse_shared_layer_action(f"{action}(1)") == (action, 1)
    assert parse_layer_action("QK_LAYER_LOCK") == ("QK_LAYER_LOCK", -1)
    assert parse_shared_layer_action("QK_LLCK") == ("QK_LLCK", -1)

    bases = shared_vial_layer_action_bases()
    assert bases["MO"] == 0x5100
    assert bases["TG"] == 0x5300
    assert bases["DF"] == 0x5200
    assert "TO" not in bases
    assert "OSL" not in bases

    custom_actions = set(shared_vial_custom_actions())
    assert "KC_USB" in custom_actions
    assert "KC_BT" in custom_actions
    assert "KC_CONNAUTO" in custom_actions
    assert "KC_CONSOLE" in custom_actions
    assert "BT_STATUS" in custom_actions
    assert "BT_POWER_TOGGLE" in custom_actions
    assert "OSL(0)" in custom_actions
    assert "OSL(31)" in custom_actions
    assert "LT(2,KC_A)" in custom_actions
    assert "MT(KC_LSFT,KC_A)" in custom_actions
    assert "TT(2)" in custom_actions
    assert "TD(TD0)" in custom_actions
    assert "CAPS_WORD" in custom_actions
    assert "REPEAT_KEY" in custom_actions
    assert "ALT_REPEAT_KEY" in custom_actions
    assert "QK_LAYER_LOCK" not in custom_actions
    assert "QK_LLCK" not in custom_actions
    assert "DRAG_LOCK" not in custom_actions
    assert "RGB_TOG" not in custom_actions
    assert len(shared_vial_custom_actions()) <= 64

    custom_map = shared_vial_custom_action_map(0x5F80)
    assert custom_map["KC_SH0"] == 0x5F80
    assert custom_map["KC_SH1"] == 0x5F81
    assert custom_map["BT_STATUS"] > custom_map["KC_USB"]
    assert custom_map["OSL(0)"] > custom_map["BT_FORGET_DEVICE"]
    assert custom_map["TD(TD0)"] > custom_map["TT(2)"]
    assert custom_map["KC_SHUTDOWN"] > custom_map["BT_FORGET_DEVICE"]
    assert custom_map["KC_BT"] > custom_map["KC_SHUTDOWN"]
    assert custom_map["CAPS_WORD"] > custom_map["KC_BT"]
    assert custom_map["ALT_REPEAT_KEY"] == 0x5F80 + 63

    assert is_layer_action("MO(1)")
    assert is_layer_action("OSL(31)")
    assert is_layer_action("MO(32)")
    assert is_layer_action("QK_LAYER_LOCK")
    assert is_layer_action("QK_LLCK")
    assert not is_layer_action("MO(-1)")
    assert not is_layer_action("BAD(1)")

    assert is_layer_action_in_range("MO(0)")
    assert is_layer_action_in_range("OSL(31)")
    assert is_layer_action_in_range("QK_LAYER_LOCK")
    assert is_layer_action_in_range("QK_LLCK")
    assert not is_layer_action_in_range("MO(32)")
    assert not is_layer_action_in_range("OSL(99)")
    assert is_layer_action_in_range("MO(32)", max_layers=64)

    assert is_wrapper_action("S(KC_1)")
    assert is_wrapper_action("LCTL(S(KC_A))")
    assert not is_wrapper_action("BAD(KC_A)")

    assert is_animation_action("ANIM(3)")
    assert not is_animation_action("ANIM(x)")

    assert is_unicode_action("U+3042")
    assert is_unicode_action("U+1F600")
    assert not is_unicode_action("U+ZZZZ")

    assert is_macro_action("MACRO:hello")
    assert is_macro_action("MACRO:foo.bar-1")
    assert not is_macro_action("MACRO:")
    assert not is_macro_action("MACRO:bad/slash")

    assert is_script_action("SCRIPT(foo)")
    assert is_script_action("SCRIPT(foo.bar-1)")
    assert not is_script_action("SCRIPT()")
    assert not is_script_action("SCRIPT(bad/slash)")

    print("ok: shared action defs")


if __name__ == "__main__":
    main()
