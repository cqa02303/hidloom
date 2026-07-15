"""Read-only inspector for Combo / Tap Dance / Key Override settings."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

from aiohttp import web

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "daemon"))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from interaction_api import _load_config, _matrix_in_range_from_vial
from interaction_inspector_summary import attach_interaction_validation_summary
from logicd.interaction_config import validate_interaction_settings
from logicd.mod_morph import mod_morph_conflicts_for_key_overrides, normalize_mod_morph_config

INTERACTION_INSPECTOR_ROUTE = "/api/interaction/inspector"


def _warning(severity: str, message: str, source: str) -> dict[str, str]:
    return {"severity": severity, "message": message, "source": source}


def _status(warnings: list[dict[str, str]]) -> str:
    if any(item["severity"] == "error" for item in warnings):
        return "error"
    if warnings:
        return "warning"
    return "ok"


def _item(item_id: str, label: str, source: str, details: dict[str, Any], warnings: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "id": item_id,
        "label": label,
        "status": _status(warnings),
        "source": source,
        "warnings": warnings,
        "details": details,
    }


def _matrix_shape(vial_json: Path) -> tuple[int, int]:
    try:
        vial = json.loads(vial_json.read_text(encoding="utf-8"))
        matrix = vial.get("matrix", {}) if isinstance(vial, dict) else {}
        return int(matrix.get("rows", 32)), int(matrix.get("cols", 32))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return 32, 32


def _raw_interaction(config_json: Path) -> dict[str, Any]:
    cfg = _load_config(config_json)
    raw = cfg.get("settings", {}).get("interaction", {})
    return raw if isinstance(raw, dict) else {}


def _combo_items(raw: dict[str, Any], matrix_in_range: Callable[[int, int], bool], combo_term: float) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    combos = raw.get("combos", [])
    if not isinstance(combos, list):
        return [], [_warning("error", "settings.interaction.combos expected list", "settings.interaction.combos")]
    items: list[dict[str, Any]] = []
    warnings_all: list[dict[str, str]] = []
    seen_sets: dict[tuple[tuple[int, int], ...], str] = {}
    key_owners: dict[tuple[int, int], list[str]] = {}
    for idx, combo in enumerate(combos):
        source = f"settings.interaction.combos[{idx}]"
        warnings: list[dict[str, str]] = []
        keys_raw = combo.get("keys", []) if isinstance(combo, dict) else []
        action = combo.get("action") if isinstance(combo, dict) else None
        keys: list[tuple[int, int]] = []
        if not isinstance(combo, dict):
            warnings.append(_warning("error", "combo entry expected object", source))
        if not isinstance(keys_raw, list) or len(keys_raw) < 2:
            warnings.append(_warning("error", "combo needs at least two keys", source))
        for key_idx, raw_key in enumerate(keys_raw if isinstance(keys_raw, list) else []):
            if not isinstance(raw_key, (list, tuple)) or len(raw_key) != 2:
                warnings.append(_warning("error", f"key {key_idx} expected [row, col]", source))
                continue
            try:
                key = (int(raw_key[0]), int(raw_key[1]))
            except (TypeError, ValueError):
                warnings.append(_warning("error", f"key {key_idx} expected integer row/col", source))
                continue
            if not matrix_in_range(*key):
                warnings.append(_warning("error", f"key {key[0]},{key[1]} outside matrix", source))
            keys.append(key)
        if len(set(keys)) != len(keys):
            warnings.append(_warning("error", "combo contains duplicate source key", source))
        keyset = tuple(sorted(set(keys)))
        if keyset in seen_sets:
            warnings.append(_warning("warning", f"same key set as {seen_sets[keyset]}", source))
        elif keyset:
            seen_sets[keyset] = source
        for key in set(keys):
            key_owners.setdefault(key, []).append(source)
        if not isinstance(action, str) or not action:
            warnings.append(_warning("error", "combo action is missing", source))
        if combo_term < 0.015 or combo_term > 0.180:
            warnings.append(_warning("info", f"combo_term {combo_term:.3f}s may need real-device tuning", source))
        warnings_all.extend(warnings)
        items.append(_item(
            f"combo-{idx}",
            f"Combo {idx + 1}",
            source,
            {"keys": [list(key) for key in keys], "action": action},
            warnings,
        ))
    for key, owners in key_owners.items():
        if len(owners) < 2:
            continue
        warning = _warning("warning", f"source key {key[0]},{key[1]} is shared by {len(owners)} combos", ", ".join(owners))
        warnings_all.append(warning)
        for item in items:
            if item["source"] in owners:
                item["warnings"].append(warning)
                item["status"] = _status(item["warnings"])
    return items, warnings_all


def _tap_dance_items(raw: dict[str, Any], global_term: float) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    dances = raw.get("tap_dances", {})
    if not isinstance(dances, dict):
        return [], [_warning("error", "settings.interaction.tap_dances expected object", "settings.interaction.tap_dances")]
    items: list[dict[str, Any]] = []
    warnings_all: list[dict[str, str]] = []
    seen_lower: dict[str, str] = {}
    for idx, (name, actions) in enumerate(dances.items()):
        source = f"settings.interaction.tap_dances.{name}"
        warnings: list[dict[str, str]] = []
        if not isinstance(name, str) or not name:
            warnings.append(_warning("error", "tap dance name is empty", source))
        lowered = str(name).lower()
        if lowered in seen_lower and seen_lower[lowered] != source:
            warnings.append(_warning("warning", f"name resembles {seen_lower[lowered]}", source))
        seen_lower[lowered] = source
        if not isinstance(actions, dict) or not actions:
            warnings.append(_warning("error", "tap dance action map is empty", source))
            action_count = 0
            term = None
        else:
            action_count = len([key for key in actions if str(key) not in {"term", "hold", "on_hold", "tap_hold", "on_tap_hold"}])
            term = actions.get("term")
            if action_count == 0:
                warnings.append(_warning("error", "tap dance has no tap count actions", source))
            if "hold" in actions and ("tap_hold" in actions or "on_tap_hold" in actions):
                warnings.append(_warning("info", "hold and tap_hold are both defined", source))
            if term is not None:
                try:
                    parsed = float(term)
                    if parsed < 0.040 or parsed > max(0.500, global_term * 2.5):
                        warnings.append(_warning("info", f"term {parsed:.3f}s differs strongly from global {global_term:.3f}s", source))
                except (TypeError, ValueError):
                    warnings.append(_warning("error", "term expected number", source))
        warnings_all.extend(warnings)
        items.append(_item(
            f"tapdance-{idx}",
            str(name),
            source,
            {"actions": action_count, "term": term},
            warnings,
        ))
    return items, warnings_all


def _key_override_items(raw: dict[str, Any], layer_count: int) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    overrides = raw.get("key_overrides", [])
    if not isinstance(overrides, list):
        return [], [_warning("error", "settings.interaction.key_overrides expected list", "settings.interaction.key_overrides")]
    items: list[dict[str, Any]] = []
    warnings_all: list[dict[str, str]] = []
    seen: dict[tuple[str, str, str, int], str] = {}
    max_mask = (1 << min(layer_count, 16)) - 1 if layer_count > 0 else 0
    for idx, override in enumerate(overrides):
        source = f"settings.interaction.key_overrides[{idx}]"
        warnings: list[dict[str, str]] = []
        if not isinstance(override, dict):
            warnings.append(_warning("error", "key override entry expected object", source))
            details = {}
        else:
            trigger = override.get("trigger", [])
            key = override.get("key", "")
            replacement = override.get("replacement", "")
            try:
                layers = int(override.get("layers", 0xFFFF))
            except (TypeError, ValueError):
                layers = 0xFFFF
                warnings.append(_warning("error", "layers expected integer mask", source))
            if not trigger:
                warnings.append(_warning("error", "trigger is missing", source))
            if not key:
                warnings.append(_warning("error", "key is missing", source))
            if not replacement:
                warnings.append(_warning("error", "replacement is missing", source))
            if max_mask and layers & max_mask == 0:
                warnings.append(_warning("warning", f"layer mask 0x{layers:x} does not include configured layers", source))
            normalized_trigger = json.dumps(trigger, sort_keys=True, ensure_ascii=False)
            duplicate_key = (normalized_trigger, str(key), str(replacement), layers)
            if duplicate_key in seen:
                warnings.append(_warning("warning", f"same condition as {seen[duplicate_key]}", source))
            else:
                seen[duplicate_key] = source
            details = {"trigger": trigger, "key": key, "replacement": replacement, "layers": layers}
        warnings_all.extend(warnings)
        items.append(_item(f"override-{idx}", f"Key Override {idx + 1}", source, details, warnings))
    return items, warnings_all


def _key_override_keys(raw: dict[str, Any]) -> list[str]:
    overrides = raw.get("key_overrides", [])
    if not isinstance(overrides, list):
        return []
    return [
        str(override.get("key", ""))
        for override in overrides
        if isinstance(override, dict) and override.get("key")
    ]


def _mod_morph_items(raw: dict[str, Any], key_override_keys: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    raw_rules = raw.get("mod_morphs", {})
    if raw_rules in (None, ""):
        raw_rules = {}
    if not isinstance(raw_rules, dict):
        return [], [_warning("error", "settings.interaction.mod_morphs expected object", "settings.interaction.mod_morphs")]
    config = normalize_mod_morph_config(raw_rules)
    warnings_all: list[dict[str, str]] = []
    warning_by_name: dict[str, list[dict[str, str]]] = {}
    for warning in config.warnings:
        item = _warning("error", warning.message, f"settings.interaction.mod_morphs.{warning.name}")
        warnings_all.append(item)
        warning_by_name.setdefault(warning.name, []).append(item)
    for action in mod_morph_conflicts_for_key_overrides(config, key_override_keys):
        name = action.removeprefix("MOD_MORPH(").removesuffix(")")
        item = _warning("warning", f"{action} output overlaps a Key Override target", f"settings.interaction.mod_morphs.{name}")
        warnings_all.append(item)
        warning_by_name.setdefault(name, []).append(item)

    items: list[dict[str, Any]] = []
    for idx, (name, rule) in enumerate(sorted(config.rules.items())):
        warnings = list(warning_by_name.get(name, []))
        items.append(_item(
            f"modmorph-{idx}",
            "GRAVE_ESCAPE" if name == "grave_escape" else f"MOD_MORPH({name})",
            f"settings.interaction.mod_morphs.{name}",
            {
                "trigger_mods": sorted(rule.trigger_mods),
                "default_action": rule.default_action,
                "morphed_action": rule.morphed_action,
                "layers": "all" if rule.layers is None else sorted(rule.layers),
                "built_in": name == "grave_escape" and name not in raw_rules,
            },
            warnings,
        ))
    return items, warnings_all


def build_interaction_inspector_payload(config_json: Path, vial_json: Path) -> dict[str, Any]:
    raw = _raw_interaction(config_json)
    matrix_in_range = _matrix_in_range_from_vial(vial_json)
    validation = validate_interaction_settings(raw, matrix_in_range=matrix_in_range)
    rows, _cols = _matrix_shape(vial_json)
    cfg = _load_config(config_json)
    layers_raw = cfg.get("layers", [])
    layer_count = len(layers_raw) if isinstance(layers_raw, list) else rows
    combo_term = float(validation.settings.get("combo_term", 0.050))
    tap_dance_term = float(validation.settings.get("tap_dance_term", 0.200))

    combos, combo_warnings = _combo_items(raw, matrix_in_range, combo_term)
    tap_dances, tap_warnings = _tap_dance_items(raw, tap_dance_term)
    overrides, override_warnings = _key_override_items(raw, layer_count)
    mod_morphs, mod_morph_warnings = _mod_morph_items(raw, _key_override_keys(raw))
    validation_warnings = [
        _warning("error", warning, "settings.interaction")
        for warning in validation.warnings
    ]
    warnings = [*validation_warnings, *combo_warnings, *tap_warnings, *override_warnings, *mod_morph_warnings]
    payload = {
        "result": "ok",
        "schema": {"route": INTERACTION_INSPECTOR_ROUTE, "version": 1},
        "summary": {
            "combos": len(combos),
            "tap_dances": len(tap_dances),
            "key_overrides": len(overrides),
            "mod_morphs": len(mod_morphs),
            "warnings": len(warnings),
        },
        "sections": {
            "combos": combos,
            "tap_dances": tap_dances,
            "key_overrides": overrides,
            "mod_morphs": mod_morphs,
        },
        "warnings": warnings,
    }
    return attach_interaction_validation_summary(payload)


async def interaction_inspector_response(config_json: Path, vial_json: Path) -> web.Response:
    try:
        return web.json_response(build_interaction_inspector_payload(config_json, vial_json))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return web.json_response({"result": "error", "msg": str(exc)}, status=500)


def register_interaction_inspector_route(app: web.Application, config_json: Path, vial_json: Path) -> None:
    async def handle_interaction_inspector(_request: web.Request) -> web.Response:
        return await interaction_inspector_response(config_json, vial_json)

    app.router.add_get(INTERACTION_INSPECTOR_ROUTE, handle_interaction_inspector)
