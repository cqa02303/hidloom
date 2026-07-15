"""Read-only LED role inspector for the HTTP Lighting UI."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Optional

from aiohttp import web

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DAEMON_ROOT = _REPO_ROOT / "daemon"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_DAEMON_ROOT) not in sys.path:
    sys.path.insert(0, str(_DAEMON_ROOT))

from ledd.semantic_roles import (  # noqa: E402
    VALID_ROLES,
    canonical_keycode,
    infer_role_from_keycode,
    normalize_led_semantic_role_config,
)
from vil_layout import load_keymap_layers  # noqa: E402
from hidloom_paths import default_config_dir, default_config_file  # noqa: E402

CONF_DIR = default_config_dir(_REPO_ROOT)
KEYMAP_JSON = default_config_file("keymap.json", _REPO_ROOT)
LEDD_JSON = default_config_file("ledd.json", _REPO_ROOT)
ROLE_INSPECTOR_ROUTE = "/api/lighting/role-inspector"
ROLE_ORDER = ("normal", "modifier", "function", "layer", "lock", "script", "system")

QueryLayers = Callable[[], Awaitable[Optional[dict[str, Any]]]]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _semantic_config_from_ledd(ledd_config: Mapping[str, Any]):
    raw = ledd_config.get("semantic_roles") or ledd_config.get("led_semantic_roles") or {}
    if not isinstance(raw, Mapping):
        raw = {}
    return normalize_led_semantic_role_config(raw)


def _reason_for_inferred_role(keycode: str, role: str) -> str:
    if role == "modifier":
        return f"{keycode} is a modifier key"
    if role == "function":
        return f"{keycode} is a function key"
    if role == "layer":
        return f"{keycode} is a layer action"
    if role == "lock":
        return f"{keycode} is a lock-state key"
    if role == "script":
        return f"{keycode} is a script action"
    if role == "system":
        return f"{keycode} is a system action"
    return "default normal key role"


def inspect_key_role(keycode: str, semantic_config: Any) -> dict[str, str]:
    canonical = canonical_keycode(keycode)
    configured = semantic_config.roles.get(canonical) or semantic_config.roles.get(keycode)
    if configured in VALID_ROLES:
        return {
            "role": configured,
            "source": "semantic_roles_config",
            "reason": f"{canonical or keycode} is configured as {configured}",
            "confidence": "high",
        }
    inferred = infer_role_from_keycode(canonical)
    return {
        "role": inferred if inferred in VALID_ROLES else "normal",
        "source": "keycode_rule" if inferred != "normal" else "fallback",
        "reason": _reason_for_inferred_role(canonical or keycode, inferred),
        "confidence": "high" if inferred != "normal" else "low",
    }


def _position_sort_key(pos: str) -> tuple[int, int, str]:
    try:
        row, col = (int(part) for part in str(pos).split(",", 1))
    except (TypeError, ValueError):
        return (9999, 9999, str(pos))
    return (row, col, str(pos))


def build_role_inspector_payload(
    layers: list[dict[str, str]],
    *,
    ledd_json: Path = LEDD_JSON,
) -> dict[str, Any]:
    ledd_config = _load_json(ledd_json)
    semantic = _semantic_config_from_ledd(ledd_config)
    summary = {role: 0 for role in ROLE_ORDER}
    source_summary: dict[str, int] = {}
    layer_payloads: list[dict[str, Any]] = []

    for layer_idx, layer in enumerate(layers):
        keys: list[dict[str, Any]] = []
        for pos in sorted(layer, key=_position_sort_key):
            try:
                row, col = (int(part) for part in str(pos).split(",", 1))
            except (TypeError, ValueError):
                continue
            keycode = str(layer[pos])
            info = inspect_key_role(keycode, semantic)
            role = info["role"]
            source = info["source"]
            summary[role] = summary.get(role, 0) + 1
            source_summary[source] = source_summary.get(source, 0) + 1
            keys.append({
                "row": row,
                "col": col,
                "layer": layer_idx,
                "keycode": keycode,
                **info,
                "reactive_trigger": semantic.reactive_enabled_for_keycode(keycode),
                "overlay_priority": semantic.overlay_priority_for_keycode(keycode),
            })
        layer_payloads.append({"layer": layer_idx, "keys": keys})

    return {
        "result": "ok",
        "layers": layer_payloads,
        "summary": summary,
        "source_summary": source_summary,
        "schema": {
            "role_source": ("semantic_roles_config", "keycode_rule", "fallback"),
            "manual_override_editor": False,
        },
    }


async def role_inspector_response(query_layers: QueryLayers) -> web.Response:
    logicd_data = await query_layers()
    if logicd_data is not None and isinstance(logicd_data.get("layers"), list):
        layers = [
            {str(k): str(v) for k, v in layer.items()}
            for layer in logicd_data["layers"]
            if isinstance(layer, dict)
        ]
    else:
        layers = load_keymap_layers(KEYMAP_JSON)
    try:
        return web.json_response(build_role_inspector_payload(layers))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return web.json_response({"result": "error", "msg": str(exc)}, status=500)


def register_lighting_role_inspector_route(app: web.Application, query_layers: QueryLayers) -> None:
    async def handle_lighting_role_inspector(_request: web.Request) -> web.Response:
        return await role_inspector_response(query_layers)

    app.router.add_get(ROLE_INSPECTOR_ROUTE, handle_lighting_role_inspector)
