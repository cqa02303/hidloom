#!/usr/bin/env python3
"""Local smoke test for logicd Lighting key actions."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.lighting import DEFAULT_LED_STATE, apply_lighting_key_action, normalize_led_state, remember_nonzero_led_mode  # noqa: E402
from logicd.state import LogicdRuntime  # noqa: E402
from vialrgb_effects import VIALRGB_SPLASH_VALUE_MAX  # noqa: E402
from vialrgb_effects import VIALRGB_EFFECT_SEQUENCE, VIALRGB_EFFECTS  # noqa: E402


def main() -> None:
    assert LogicdRuntime().led_state == DEFAULT_LED_STATE
    assert LogicdRuntime().led_state is not DEFAULT_LED_STATE
    assert normalize_led_state({}) == DEFAULT_LED_STATE
    assert normalize_led_state({"mode": 40, "v": 255})["v"] == VIALRGB_SPLASH_VALUE_MAX
    assert normalize_led_state({"mode": 2, "v": 255})["v"] == 255

    pushed: list[dict[str, int]] = []
    alerts: list[tuple[str, float]] = []
    led_state = {"mode": 40, "speed": 128, "h": 80, "s": 128, "v": 128}
    last_nonzero_mode = remember_nonzero_led_mode(led_state, list(VIALRGB_EFFECT_SEQUENCE), 40)

    def apply(action: str, is_press: bool) -> bool:
        nonlocal last_nonzero_mode
        handled, last_nonzero_mode = apply_lighting_key_action(
            action,
            is_press,
            led_state,
            last_nonzero_mode,
            step=16,
            sequence=list(VIALRGB_EFFECT_SEQUENCE),
            effects=VIALRGB_EFFECTS,
            push_ledd_vialrgb=lambda: pushed.append(dict(led_state)),
            schedule_save=lambda: None,
            push_alert=lambda msg, sec=2.0: alerts.append((msg, sec)),
        )
        return handled

    assert apply("RGB_VAI", True)
    assert led_state["v"] == 144
    assert not alerts

    assert apply("RGB_VAD", True)
    assert led_state["v"] == 128

    assert apply("RGB_SPI", True)
    assert led_state["speed"] == 144

    assert apply("RGB_MOD", True)
    assert led_state["mode"] == 41
    assert alerts[-1][0] == "LED Effect\n41: Solid Splash"

    assert apply("RGB_RMOD", True)
    assert led_state["mode"] == 40
    assert alerts[-1][0] == "LED Effect\n40: Multisplash"

    assert apply("RGB_TOG", True)
    assert led_state["mode"] == 0
    assert apply("RGB_TOG", True)
    assert led_state["mode"] == 40

    assert apply("RM_VALU", True)
    assert led_state["v"] == 144
    for _ in range(8):
        assert apply("RGB_VAI", True)
    assert led_state["v"] == VIALRGB_SPLASH_VALUE_MAX

    assert apply("KC_A", True) is False
    assert apply("RGB_VAI", False) is True
    assert pushed

    print("ok: logicd Lighting key actions update LED state")


if __name__ == "__main__":
    main()
