"""
Layer-based keymap management.

Layer lookup order: highest active layer number wins.
"KC_TRNS" (transparent) falls through to next lower layer.
"KC_NONE" blocks fall-through.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, List, Set

log = logging.getLogger(__name__)

_MO_RE = re.compile(r'^MO\((\d+)\)$')
_TG_RE = re.compile(r'^TG\((\d+)\)$')
_TO_RE = re.compile(r'^TO\((\d+)\)$')
_DF_RE = re.compile(r'^DF\((\d+)\)$')
_OSL_RE = re.compile(r'^OSL\((\d+)\)$')
_LL_RE = re.compile(r'^(QK_LAYER_LOCK|QK_LLCK)$')


class LayerManager:
    """Manages keymap layers and the active-layer stack."""

    def __init__(self) -> None:
        self._layers: List[Dict[str, str]] = [{}]
        self._momentary: Set[int] = set()
        self._toggled: Set[int] = set()
        self._oneshot: Set[int] = set()
        self._locked: Set[int] = set()
        self._conditional: Set[int] = set()
        self._conditional_rules: list[dict[str, Any]] = []
        self._default_layer: int = 0

    def load(self, layers_config: List[Dict[str, str]]) -> None:
        if not layers_config:
            self._layers = [{}]
            self._default_layer = 0
            self._momentary.clear()
            self._toggled.clear()
            self._oneshot.clear()
            self._locked.clear()
            self._conditional.clear()
            return
        self._layers = [dict(layer) for layer in layers_config]
        self._default_layer = 0
        self._momentary.clear()
        self._toggled.clear()
        self._oneshot.clear()
        self._locked.clear()
        self._conditional.clear()
        self._recompute_conditional_layers()
        log.info("Loaded %d layer(s)", len(self._layers))

    def _valid_layer(self, layer: int) -> bool:
        return 0 <= layer < len(self._layers)

    def _prune_invalid_active_layers(self) -> None:
        self._momentary = {layer for layer in self._momentary if self._valid_layer(layer)}
        self._toggled = {layer for layer in self._toggled if self._valid_layer(layer)}
        self._oneshot = {layer for layer in self._oneshot if self._valid_layer(layer)}
        self._locked = {layer for layer in self._locked if self._valid_layer(layer)}
        self._conditional = {layer for layer in self._conditional if self._valid_layer(layer)}
        if not self._valid_layer(self._default_layer):
            self._default_layer = 0

    def _manual_active_layers(self) -> set[int]:
        self._prune_invalid_active_layers()
        return self._momentary | self._toggled | self._oneshot | self._locked | {self._default_layer, 0}

    def _recompute_conditional_layers(self) -> None:
        manual_active = self._manual_active_layers()
        conditional: set[int] = set()
        for rule in self._conditional_rules:
            sources = {int(layer) for layer in rule.get("if_all", [])}
            target = int(rule.get("then", -1))
            if not self._valid_layer(target):
                continue
            if sources <= manual_active:
                conditional.add(target)
        self._conditional = conditional

    def set_conditional_rules(self, rules: Iterable[dict[str, Any]] | None) -> None:
        self._conditional_rules = [dict(rule) for rule in rules or []]
        self._conditional.clear()
        self._recompute_conditional_layers()

    def _active_layers(self) -> list[int]:
        self._recompute_conditional_layers()
        active = self._manual_active_layers() | self._conditional
        return sorted(active, reverse=True)

    def layers_snapshot(self) -> List[Dict[str, str]]:
        """Return a copy of the runtime keymap layers."""
        return [dict(layer) for layer in self._layers]

    def active_snapshot(self) -> dict[str, list[int]]:
        """Return the active layer state in the ctrl API response format."""
        self._recompute_conditional_layers()
        return {
            "momentary": sorted(self._momentary),
            "toggled": sorted(self._toggled),
            "oneshot": sorted(self._oneshot),
            "locked": sorted(self._locked),
            "conditional": sorted(self._conditional),
            "all": self._active_layers(),
        }

    def get_action(self, row: int, col: int) -> str:
        """Return the effective action for (row, col) considering the layer stack."""
        key = f"{row},{col}"
        for idx in self._active_layers():
            if idx >= len(self._layers):
                continue
            action = self._layers[idx].get(key, "KC_TRNS")
            if action == "KC_TRNS":
                continue
            return action
        return "KC_NONE"

    def on_press(self, action: str) -> None:
        m = _MO_RE.match(action)
        if m:
            self._momentary.add(int(m.group(1)))
            return
        m = _TG_RE.match(action)
        if m:
            self.toggle(int(m.group(1)))
            return
        m = _TO_RE.match(action)
        if m:
            self.to_layer(int(m.group(1)))
            return
        m = _DF_RE.match(action)
        if m:
            self.set_default(int(m.group(1)))
            return
        m = _OSL_RE.match(action)
        if m:
            self.oneshot_on(int(m.group(1)))
            return
        if _LL_RE.match(action):
            self.layer_lock_toggle_current()

    def on_release(self, action: str) -> None:
        m = _MO_RE.match(action)
        if m:
            self._momentary.discard(int(m.group(1)))
            self._recompute_conditional_layers()

    def momentary_on(self, layer: int) -> None:
        if not self._valid_layer(layer):
            log.warning("Ignoring momentary layer outside configured range: %d", layer)
            return
        self._momentary.add(layer)
        self._recompute_conditional_layers()

    def momentary_off(self, layer: int) -> None:
        self._momentary.discard(layer)
        self._recompute_conditional_layers()

    def toggle(self, layer: int) -> None:
        if not self._valid_layer(layer):
            log.warning("Ignoring toggle layer outside configured range: %d", layer)
            return
        if layer in self._toggled:
            self._toggled.discard(layer)
        else:
            self._toggled.add(layer)
        self._recompute_conditional_layers()

    def to_layer(self, layer: int) -> None:
        if not self._valid_layer(layer):
            log.warning("Ignoring target layer outside configured range: %d", layer)
            return
        self._momentary.clear()
        self._toggled.clear()
        self._locked.clear()
        self.oneshot_clear()
        if layer != self._default_layer:
            self._toggled.add(layer)
        self._recompute_conditional_layers()

    def set_default(self, layer: int) -> None:
        if not self._valid_layer(layer):
            log.warning("Ignoring default layer outside configured range: %d", layer)
            return
        self._default_layer = layer
        self._momentary.clear()
        self._locked.clear()
        self.oneshot_clear()
        self._recompute_conditional_layers()

    def oneshot_on(self, layer: int) -> None:
        if not self._valid_layer(layer):
            log.warning("Ignoring oneshot layer outside configured range: %d", layer)
            return
        self._oneshot.add(layer)
        self._recompute_conditional_layers()

    def oneshot_clear(self) -> None:
        self._oneshot.clear()
        self._recompute_conditional_layers()

    def has_oneshot(self) -> bool:
        return bool(self._oneshot)

    def layer_lock_toggle_current(self) -> int | None:
        """Toggle lock for the highest active non-default layer.

        Layer Lock is transient runtime state.  It does not know which key
        triggered it; the current layer stack decides the target.  If the target
        came from OSL, the one-shot state is consumed into locked state so the
        layer remains active after the next normal key.
        """
        candidates = [
            layer
            for layer in self._active_layers()
            if layer not in {0, self._default_layer}
        ]
        if not candidates:
            return None
        target = candidates[0]
        if target in self._locked:
            self._locked.discard(target)
        else:
            self._locked.add(target)
            self._oneshot.discard(target)
        self._recompute_conditional_layers()
        return target

    def locked_clear(self) -> None:
        """Clear transient Layer Lock state."""
        self._locked.clear()
        self._recompute_conditional_layers()

    def set_action(self, layer: int, row: int, col: int, action: str) -> None:
        while layer >= len(self._layers):
            self._layers.append({})
        self._layers[layer][f"{row},{col}"] = action
        log.info("Runtime remap: layer=%d (%d,%d) → %s", layer, row, col, action)

    def _known_matrix_keys(self) -> set[str]:
        keys: set[str] = set()
        for layer in self._layers:
            keys.update(layer.keys())
        return keys

    def add_layer(self, matrix_keys: Iterable[str] | None = None) -> int:
        layer = len(self._layers)
        keys = set(matrix_keys or [])
        if not keys:
            keys = self._known_matrix_keys()
        self._layers.append({key: "KC_TRNS" for key in sorted(keys)})
        log.info("Runtime layer added: layer=%d keys=%d", layer, len(keys))
        return layer

    def clear_layer(self, layer: int, matrix_keys: Iterable[str] | None = None) -> tuple[str, int]:
        if layer <= 0:
            raise ValueError("layer 0 cannot be cleared")
        if layer >= len(self._layers):
            raise ValueError(f"layer does not exist: {layer}")
        if layer == len(self._layers) - 1:
            self._layers.pop()
            self._momentary.discard(layer)
            self._toggled.discard(layer)
            self._oneshot.discard(layer)
            self._locked.discard(layer)
            self._conditional.discard(layer)
            if self._default_layer == layer:
                self._default_layer = 0
            self._recompute_conditional_layers()
            log.info("Runtime layer removed: layer=%d", layer)
            return "removed", 0
        keys = set(matrix_keys or [])
        if not keys:
            keys = self._known_matrix_keys()
        self._layers[layer] = {key: "KC_TRNS" for key in sorted(keys)}
        self._momentary.discard(layer)
        self._toggled.discard(layer)
        self._oneshot.discard(layer)
        self._locked.discard(layer)
        self._conditional.discard(layer)
        if self._default_layer == layer:
            self._default_layer = 0
        self._recompute_conditional_layers()
        log.info("Runtime layer cleared: layer=%d keys=%d", layer, len(keys))
        return "cleared", len(keys)

    @staticmethod
    def is_layer_action(action: str) -> bool:
        return bool(
            _MO_RE.match(action)
            or _TG_RE.match(action)
            or _TO_RE.match(action)
            or _DF_RE.match(action)
            or _OSL_RE.match(action)
            or _LL_RE.match(action)
        )
