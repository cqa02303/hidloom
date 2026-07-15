"""Read-only inspector helpers for Conditional Layers.

The runtime owner remains LayerManager.  This module builds a UI/API-friendly
view that separates saved rule definitions from current active runtime state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class ConditionalLayerWarning:
    """Read-only warning for a conditional layer rule."""

    name: str
    severity: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass(frozen=True)
class ConditionalLayerRuleView:
    """Normalized rule view for inspector output."""

    name: str
    if_all: tuple[int, ...]
    then: int
    active: bool
    source_active: tuple[int, ...]
    source_missing: tuple[int, ...]
    chain_ignored: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "if_all": list(self.if_all),
            "then": self.then,
            "active": self.active,
            "source_active": list(self.source_active),
            "source_missing": list(self.source_missing),
            "chain_ignored": self.chain_ignored,
        }


def _active_set(active_snapshot: Mapping[str, Any]) -> set[int]:
    manual: set[int] = set()
    for key in ("momentary", "toggled", "oneshot", "locked"):
        manual.update(int(layer) for layer in active_snapshot.get(key, []) or [])
    all_layers = {int(layer) for layer in active_snapshot.get("all", []) or []}
    conditional = {int(layer) for layer in active_snapshot.get("conditional", []) or []}
    manual.update(all_layers - conditional)
    return manual


def conditional_layer_rule_warnings(rules: Iterable[Mapping[str, Any]]) -> tuple[ConditionalLayerWarning, ...]:
    """Return read-only warnings for rule shapes that deserve UI attention."""
    warnings: list[ConditionalLayerWarning] = []
    target_to_names: dict[int, list[str]] = {}
    rules_list = [dict(rule) for rule in rules]
    for idx, rule in enumerate(rules_list):
        name = str(rule.get("name") or f"rule_{idx}")
        try:
            sources = [int(layer) for layer in rule.get("if_all", [])]
            target = int(rule.get("then"))
        except (TypeError, ValueError):
            warnings.append(ConditionalLayerWarning(name, "error", "rule contains non-integer layer"))
            continue
        if len(sources) < 2:
            warnings.append(ConditionalLayerWarning(name, "warning", "if_all should contain at least two source layers"))
        if len(set(sources)) != len(sources):
            warnings.append(ConditionalLayerWarning(name, "warning", "if_all contains duplicate source layers"))
        if target in sources:
            warnings.append(ConditionalLayerWarning(name, "error", "then layer must not also be a source"))
        target_to_names.setdefault(target, []).append(name)

    target_layers = set(target_to_names)
    for idx, rule in enumerate(rules_list):
        name = str(rule.get("name") or f"rule_{idx}")
        try:
            sources = {int(layer) for layer in rule.get("if_all", [])}
        except (TypeError, ValueError):
            continue
        chained_sources = sorted(sources & target_layers)
        if chained_sources:
            warnings.append(ConditionalLayerWarning(
                name,
                "info",
                f"chain activation is not evaluated; conditional source(s) ignored: {chained_sources}",
            ))

    for target, names in sorted(target_to_names.items()):
        if len(names) > 1:
            warnings.append(ConditionalLayerWarning(
                ",".join(names),
                "info",
                f"multiple rules share target layer {target}",
            ))
    return tuple(warnings)


def conditional_layer_inspector_payload(
    rules: Iterable[Mapping[str, Any]],
    active_snapshot: Mapping[str, Any],
) -> dict[str, object]:
    """Build read-only inspector payload for conditional layer rules."""
    rules_list = [dict(rule) for rule in rules]
    manual_active = _active_set(active_snapshot)
    active_conditional = {int(layer) for layer in active_snapshot.get("conditional", []) or []}
    target_layers: set[int] = set()
    for rule in rules_list:
        try:
            target_layers.add(int(rule.get("then")))
        except (TypeError, ValueError):
            continue

    views: list[ConditionalLayerRuleView] = []
    for idx, rule in enumerate(rules_list):
        name = str(rule.get("name") or f"rule_{idx}")
        try:
            sources = tuple(int(layer) for layer in rule.get("if_all", []))
            target = int(rule.get("then"))
        except (TypeError, ValueError):
            continue
        source_active = tuple(layer for layer in sources if layer in manual_active)
        source_missing = tuple(layer for layer in sources if layer not in manual_active)
        chain_ignored = any(layer in target_layers for layer in sources)
        views.append(ConditionalLayerRuleView(
            name=name,
            if_all=sources,
            then=target,
            active=target in active_conditional,
            source_active=source_active,
            source_missing=source_missing,
            chain_ignored=chain_ignored,
        ))

    warnings = conditional_layer_rule_warnings(rules_list)
    return {
        "schema": "conditional_layers.inspector.v1",
        "rule_count": len(rules_list),
        "active_conditional": sorted(active_conditional),
        "manual_active": sorted(manual_active),
        "rules": [view.to_dict() for view in views],
        "warnings": [warning.to_dict() for warning in warnings],
        "chain_activation_supported": False,
        "read_only": True,
    }
