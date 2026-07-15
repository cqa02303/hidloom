"""VialRGB and QMK lighting-key state handling for logicd."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from typing import Awaitable, Callable

from vialrgb_effects import clamp_vialrgb_value_for_mode

log = logging.getLogger(__name__)

LIGHTING_KEY_ALIASES = {
    "RGB_TOGGLE": "RGB_TOG",
    "RGB_MODE_FORWARD": "RGB_MOD",
    "RGB_MODE_REVERSE": "RGB_RMOD",
    "RGB_HUE_UP": "RGB_HUI",
    "RGB_HUE_DOWN": "RGB_HUD",
    "RGB_SAT_UP": "RGB_SAI",
    "RGB_SAT_DOWN": "RGB_SAD",
    "RGB_VAL_UP": "RGB_VAI",
    "RGB_VAL_DOWN": "RGB_VAD",
    "RGB_SPEED_UP": "RGB_SPI",
    "RGB_SPEED_DOWN": "RGB_SPD",
    "RM_TOG": "RM_TOGG",
    "RM_ON": "RGB_ON",
    "RM_OFF": "RGB_OFF",
    "RM_TOGG": "RGB_TOG",
    "RM_NEXT": "RGB_MOD",
    "RM_PREV": "RGB_RMOD",
    "RM_HUEU": "RGB_HUI",
    "RM_HUED": "RGB_HUD",
    "RM_SATU": "RGB_SAI",
    "RM_SATD": "RGB_SAD",
    "RM_VALU": "RGB_VAI",
    "RM_VALD": "RGB_VAD",
    "RM_SPDU": "RGB_SPI",
    "RM_SPDD": "RGB_SPD",
}

LIGHTING_KEYS = {
    "RGB_ON", "RGB_OFF", "RGB_TOG", "RGB_MOD", "RGB_RMOD",
    "RGB_HUI", "RGB_HUD", "RGB_SAI", "RGB_SAD",
    "RGB_VAI", "RGB_VAD", "RGB_SPI", "RGB_SPD",
}

DEFAULT_LED_STATE = {"mode": 40, "speed": 128, "h": 175, "s": 77, "v": 160}


def normalize_led_state(raw: dict) -> dict[str, int]:
    state: dict[str, int] = {}
    for key, default in DEFAULT_LED_STATE.items():
        value = int(raw.get(key, default))
        upper = 65535 if key == "mode" else 255
        state[key] = max(0, min(upper, value))
    state["v"] = clamp_vialrgb_value_for_mode(state["mode"], state["v"])
    return state


def remember_nonzero_led_mode(state: dict[str, int], sequence: list[int], current: int) -> int:
    mode = int(state.get("mode", 0))
    return mode if mode in sequence else current


def normalize_vialrgb_mode(mode: int, allowed_modes: set[int]) -> int:
    if mode in allowed_modes:
        return mode
    log.warning("unsupported VialRGB mode %d; using Solid Color", mode)
    return 2


def load_led_state(path: str, state: dict[str, int], sequence: list[int], current_last_mode: int) -> int:
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        if isinstance(raw, dict):
            state.update(normalize_led_state(raw))
            current_last_mode = remember_nonzero_led_mode(state, sequence, current_last_mode)
            log.info("LED state loaded from %s: %s", path, state)
    except FileNotFoundError:
        log.info("LED state file not found; using defaults: %s", path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        log.warning("LED state load failed (%s): %s", path, exc)
    return current_last_mode


def save_led_state(path: str, state: dict[str, int]) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".led_state.", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(normalize_led_state(state), fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp_path, path)
        os.chmod(path, 0o644)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    return path


async def debounced_save_led_state(path: str, state: dict[str, int], debounce_sec: float) -> None:
    await asyncio.sleep(debounce_sec)
    saved_path = save_led_state(path, state)
    log.info("LED state saved to %s", saved_path)


def vialrgb_effect_name(mode: int, effects: dict[int, str]) -> str:
    return effects.get(mode, f"Unknown ({mode})")


def schedule_led_state_save(
    current_task: asyncio.Task | None,
    save_now: Callable[[], str],
    save_later: Callable[[], Awaitable[None]],
) -> asyncio.Task | None:
    if current_task is not None and not current_task.done():
        current_task.cancel()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        save_now()
        return None
    return loop.create_task(save_later())


def notify_i2cd_led_effect_if_changed(
    previous_mode: int,
    current_mode: int,
    effects: dict[int, str],
    push_alert: Callable[[str, float], None],
) -> None:
    if previous_mode == current_mode:
        return
    name = vialrgb_effect_name(current_mode, effects)
    push_alert(f"LED Effect\n{current_mode}: {name}", 2.0)


def cycle_led_mode(state: dict[str, int], sequence: list[int], last_nonzero_mode: int, delta: int) -> None:
    current = int(state.get("mode", 0))
    if current not in sequence:
        current = last_nonzero_mode if last_nonzero_mode in sequence else 2
    idx = sequence.index(current)
    state["mode"] = sequence[(idx + delta) % len(sequence)]


def bump_led_state_field(state: dict[str, int], field: str, delta: int) -> None:
    state[field] = max(0, min(255, int(state.get(field, 0)) + delta))


def apply_led_state_update(
    state: dict[str, int],
    previous_mode: int,
    last_nonzero_mode: int,
    sequence: list[int],
    effects: dict[int, str],
    push_ledd_vialrgb: Callable[[], None],
    schedule_save: Callable[[], None],
    push_alert: Callable[[str, float], None],
) -> int:
    state.update(normalize_led_state(state))
    last_nonzero_mode = remember_nonzero_led_mode(state, sequence, last_nonzero_mode)
    push_ledd_vialrgb()
    schedule_save()
    notify_i2cd_led_effect_if_changed(previous_mode, int(state.get("mode", 0)), effects, push_alert)
    return last_nonzero_mode


def apply_lighting_key_action(
    action: str,
    is_press: bool,
    state: dict[str, int],
    last_nonzero_mode: int,
    *,
    step: int,
    sequence: list[int],
    effects: dict[int, str],
    push_ledd_vialrgb: Callable[[], None],
    schedule_save: Callable[[], None],
    push_alert: Callable[[str, float], None],
) -> tuple[bool, int]:
    action = LIGHTING_KEY_ALIASES.get(action, action)
    if action not in LIGHTING_KEYS:
        return False, last_nonzero_mode
    if not is_press:
        return True, last_nonzero_mode

    previous_mode = int(state.get("mode", 0))
    if action == "RGB_ON":
        state["mode"] = last_nonzero_mode if last_nonzero_mode in sequence else 2
    elif action == "RGB_OFF":
        last_nonzero_mode = remember_nonzero_led_mode(state, sequence, last_nonzero_mode)
        state["mode"] = 0
    elif action == "RGB_TOG":
        if int(state.get("mode", 0)) == 0:
            state["mode"] = last_nonzero_mode if last_nonzero_mode in sequence else 2
        else:
            last_nonzero_mode = remember_nonzero_led_mode(state, sequence, last_nonzero_mode)
            state["mode"] = 0
    elif action == "RGB_MOD":
        cycle_led_mode(state, sequence, last_nonzero_mode, 1)
    elif action == "RGB_RMOD":
        cycle_led_mode(state, sequence, last_nonzero_mode, -1)
    elif action == "RGB_HUI":
        bump_led_state_field(state, "h", step)
    elif action == "RGB_HUD":
        bump_led_state_field(state, "h", -step)
    elif action == "RGB_SAI":
        bump_led_state_field(state, "s", step)
    elif action == "RGB_SAD":
        bump_led_state_field(state, "s", -step)
    elif action == "RGB_VAI":
        bump_led_state_field(state, "v", step)
    elif action == "RGB_VAD":
        bump_led_state_field(state, "v", -step)
    elif action == "RGB_SPI":
        bump_led_state_field(state, "speed", step)
    elif action == "RGB_SPD":
        bump_led_state_field(state, "speed", -step)

    last_nonzero_mode = apply_led_state_update(
        state,
        previous_mode,
        last_nonzero_mode,
        sequence,
        effects,
        push_ledd_vialrgb,
        schedule_save,
        push_alert,
    )
    log.info(
        "lighting key %s -> mode=%d speed=%d hsv=(%d,%d,%d)",
        action, state["mode"], state["speed"], state["h"], state["s"], state["v"],
    )
    return True, last_nonzero_mode
