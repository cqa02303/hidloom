"""HTTP bridge for MORSE feedback events from logicd."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

MORSE_FEEDBACK_ROUTE = "/api/interaction/morse-feedback"
SendCtrl = Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]]


async def morse_feedback_response(send_ctrl_command: SendCtrl) -> web.Response:
    """Drain buffered MORSE feedback events through logicd ctrl socket."""
    resp = await send_ctrl_command({"t": "MORSE_FEEDBACK"})
    if resp is None:
        return web.json_response({
            "result": "error",
            "msg": "logicd unavailable",
            "events": [],
            "count": 0,
        }, status=503)
    if resp.get("result") != "ok":
        return web.json_response({
            "result": "error",
            "msg": resp.get("msg", "morse feedback unavailable"),
            "events": [],
            "count": 0,
        }, status=503)
    events = resp.get("events", [])
    if not isinstance(events, list):
        events = []
    return web.json_response({
        "result": "ok",
        "events": events,
        "count": len(events),
        "schema": {
            "route": MORSE_FEEDBACK_ROUTE,
            "source": "logicd ctrl MORSE_FEEDBACK",
            "drain": True,
        },
    })


def register_morse_feedback_route(app: web.Application, send_ctrl_command: SendCtrl) -> None:
    async def _handle(_request: web.Request) -> web.Response:
        return await morse_feedback_response(send_ctrl_command)

    app.router.add_get(MORSE_FEEDBACK_ROUTE, _handle)
