"""Read-only HTTP metadata for Unicode / Send String safety."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

try:
    from aiohttp import web
except ModuleNotFoundError:  # Allow local payload tests without the HTTP runtime dependency.
    web = None  # type: ignore[assignment]

_HERE = Path(__file__).parent
_REPO_ROOT = _HERE.parents[1]
if str(_REPO_ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "daemon"))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from logicd.text_send_safety import build_text_send_real_send_plan, text_send_safety_policy  # noqa: E402

TEXT_SEND_SAFETY_ROUTE = "/api/interaction/text-send-safety"
TEXT_SEND_PLAN_ROUTE = "/api/interaction/text-send-safety/plan"


def _load_settings(config_json: Path) -> dict[str, Any]:
    try:
        data = json.loads(config_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    settings = data.get("settings")
    return settings if isinstance(settings, dict) else {}


def text_send_safety_payload(config_json: Path) -> dict[str, Any]:
    return {
        "result": "ok",
        "route": TEXT_SEND_SAFETY_ROUTE,
        "plan_route": TEXT_SEND_PLAN_ROUTE,
        **text_send_safety_policy(_load_settings(config_json)),
    }


def text_send_plan_payload(config_json: Path, body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {"result": "error", "reason": "body_must_be_object"}
    if "action" not in body:
        return {"result": "error", "reason": "action_required"}
    action = body.get("action")
    if not isinstance(action, str):
        return {"result": "error", "reason": "action_must_be_string"}
    return {
        "result": "ok",
        "route": TEXT_SEND_PLAN_ROUTE,
        "read_only": True,
        "plan": build_text_send_real_send_plan(action, _load_settings(config_json)),
    }


async def text_send_safety_response(config_json: Path) -> web.Response:
    if web is None:
        raise RuntimeError("aiohttp is required for HTTP responses")
    return web.json_response(text_send_safety_payload(config_json))


async def text_send_plan_response(request: web.Request, config_json: Path) -> web.Response:
    if web is None:
        raise RuntimeError("aiohttp is required for HTTP responses")
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        return web.json_response({"result": "error", "msg": "Invalid JSON"}, status=400)
    payload = text_send_plan_payload(config_json, body)
    status = 200 if payload.get("result") == "ok" else 400
    return web.json_response(payload, status=status)


def register_text_send_safety_route(app: web.Application, config_json: Path) -> None:
    if web is None:
        raise RuntimeError("aiohttp is required to register HTTP routes")

    async def handle_text_send_safety(_request: web.Request) -> web.Response:
        return await text_send_safety_response(config_json)

    async def handle_text_send_plan(request: web.Request) -> web.Response:
        return await text_send_plan_response(request, config_json)

    app.router.add_get(TEXT_SEND_SAFETY_ROUTE, handle_text_send_safety)
    app.router.add_post(TEXT_SEND_PLAN_ROUTE, handle_text_send_plan)
