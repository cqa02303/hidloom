"""HTTP route for read-only Conditional Layers inspector metadata."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from aiohttp import web

_HERE = Path(__file__).parent
_REPO_ROOT = _HERE.parents[1]
if str(_REPO_ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "daemon"))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from interaction_api import _load_config  # noqa: E402
from keymap_api import ACTIVE_LAYER_FALLBACK  # noqa: E402
from logicd.conditional_layer_inspector import conditional_layer_inspector_payload  # noqa: E402

CONDITIONAL_LAYER_INSPECTOR_ROUTE = "/api/interaction/conditional-layers/inspector"
QueryActiveLayers = Callable[[], Awaitable[Optional[dict[str, Any]]]]


def _saved_conditional_rules(config_json: Path) -> list[dict[str, Any]]:
    cfg = _load_config(config_json)
    interaction = cfg.get("settings", {}).get("interaction", {})
    if not isinstance(interaction, dict):
        return []
    rules = interaction.get("conditional_layers", [])
    if not isinstance(rules, list):
        return []
    return [dict(rule) for rule in rules if isinstance(rule, dict)]


def conditional_layer_http_payload(
    config_json: Path,
    active: dict[str, Any] | None,
    *,
    logicd_available: bool,
) -> dict[str, Any]:
    active_snapshot = active if isinstance(active, dict) else dict(ACTIVE_LAYER_FALLBACK)
    payload = conditional_layer_inspector_payload(
        _saved_conditional_rules(config_json),
        active_snapshot,
    )
    return {
        "result": "ok",
        "route": CONDITIONAL_LAYER_INSPECTOR_ROUTE,
        "logicd_available": logicd_available,
        "active_source": "logicd" if logicd_available else "fallback",
        **payload,
    }


async def conditional_layer_inspector_response(
    config_json: Path,
    query_active_layers: QueryActiveLayers,
) -> web.Response:
    try:
        logicd_data = await query_active_layers()
        active = logicd_data.get("active") if isinstance(logicd_data, dict) else None
        logicd_available = isinstance(active, dict)
        return web.json_response(conditional_layer_http_payload(
            config_json,
            active,
            logicd_available=logicd_available,
        ))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return web.json_response({"result": "error", "msg": str(exc)}, status=500)


def register_conditional_layer_inspector_route(
    app: web.Application,
    config_json: Path,
    query_active_layers: QueryActiveLayers,
) -> None:
    async def handle_conditional_layer_inspector(_request: web.Request) -> web.Response:
        return await conditional_layer_inspector_response(config_json, query_active_layers)

    app.router.add_get(CONDITIONAL_LAYER_INSPECTOR_ROUTE, handle_conditional_layer_inspector)
