"""Layer action dispatch helpers for logicd.

This module keeps QMK/Vial layer key handling out of the main logicd event
loop.  It is intentionally small and side-effect free except for mutating the
provided LayerManager instance.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from .keymap import LayerManager

_LAYER_ACTION_RE = re.compile(r"^(MO|TG|TO|DF|OSL)\((\d+)\)$")
_LAYER_LOCK_ACTIONS = {"QK_LAYER_LOCK", "QK_LLCK"}
_LAYER_ACTION_NAMES = ("MO", "TG", "TO", "DF", "OSL", "QK_LAYER_LOCK", "QK_LLCK")


@dataclass(frozen=True)
class LayerActionResult:
    """Result returned when a layer action was handled."""

    op: str
    layer: int
    changed: bool


def parse_layer_action(action: str) -> tuple[str, int] | None:
    """Return (operation, layer) for a layer action string, or None.

    Target-less Layer Lock actions return layer ``-1`` because the runtime
    LayerManager chooses the currently active non-default layer at press time.
    """
    if action in _LAYER_LOCK_ACTIONS:
        return action, -1
    m = _LAYER_ACTION_RE.match(action)
    if not m:
        return None
    return m.group(1), int(m.group(2))


def layer_action_names() -> tuple[str, ...]:
    """Return supported layer action names."""
    return _LAYER_ACTION_NAMES


def handle_layer_action(layers: LayerManager, action: str, is_press: bool) -> LayerActionResult | None:
    """Handle MO/TG/TO/DF/OSL/Layer Lock layer actions.

    Returns None when action is not a layer action.  For release-only events
    that do not change state, changed is False so callers can still consume the
    layer key without forwarding it to MacroExecutor.
    """
    parsed = parse_layer_action(action)
    if parsed is None:
        return None

    op, layer_n = parsed
    changed = False
    if op == "MO":
        if is_press:
            layers.momentary_on(layer_n)
        else:
            layers.momentary_off(layer_n)
        changed = True
    elif op in _LAYER_LOCK_ACTIONS:
        if is_press:
            target = layers.layer_lock_toggle_current()
            layer_n = -1 if target is None else target
            changed = target is not None
        else:
            changed = False
    elif not is_press:
        changed = False
    elif op == "TG":
        layers.toggle(layer_n)
        changed = True
    elif op == "TO":
        layers.to_layer(layer_n)
        changed = True
    elif op == "DF":
        layers.set_default(layer_n)
        changed = True
    elif op == "OSL":
        layers.oneshot_on(layer_n)
        changed = True

    return LayerActionResult(op=op, layer=layer_n, changed=changed)


def handle_layer_action_with_status(
    layers: LayerManager,
    action: str,
    is_press: bool,
    push_ledd_status: Callable[[], None],
    push_i2cd_status: Callable[[], None],
) -> bool:
    """Handle a layer action and notify status sinks.

    Returns True when the action was a layer action and should be consumed.
    """
    result = handle_layer_action(layers, action, is_press)
    if result is None:
        return False
    if result.changed:
        push_ledd_status()
        push_i2cd_status()
    return True
