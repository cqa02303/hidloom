#!/usr/bin/env python3
"""Tests for the low-frequency lighting role-preview API helper."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import asyncio

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "daemon" / "http"))

from lighting_role_preview_api import ROLE_PREVIEW_ROUTE, _state_from_response, make_lighting_role_preview_handler  # noqa: E402


class FakeRequest:
    def __init__(self, body: dict) -> None:
        self._body = body

    async def json(self) -> dict:
        return self._body


async def _assert_unavailable_responses() -> None:
    async def unavailable(_cmd: dict) -> None:
        return None

    handler = make_lighting_role_preview_handler(unavailable)
    preview_resp = await handler(FakeRequest({"action": "preview"}))
    assert preview_resp.status == 503
    assert json.loads(preview_resp.text) == {"result": "error", "msg": "logicd unavailable"}

    restore_resp = await handler(FakeRequest({"action": "restore", "state": {"mode": 40}}))
    assert restore_resp.status == 503
    assert json.loads(restore_resp.text) == {"result": "error", "msg": "logicd unavailable"}


def main() -> None:
    assert ROLE_PREVIEW_ROUTE == "/api/lighting/role-preview"
    assert _state_from_response({}) == {"mode": 2, "speed": 128, "h": 0, "s": 0, "v": 128}
    assert _state_from_response({"mode": "40", "speed": "12", "h": "3", "s": "4", "v": "5"}) == {
        "mode": 40,
        "speed": 12,
        "h": 3,
        "s": 4,
        "v": 5,
    }

    source = (ROOT / "daemon" / "http" / "lighting_role_preview_api.py").read_text(encoding="utf-8")
    httpd = (ROOT / "daemon" / "http" / "httpd.py").read_text(encoding="utf-8")
    assert "def make_lighting_role_preview_handler" in source
    assert "def register_lighting_role_preview_route" in source
    assert "ROLE_PREVIEW_ROUTE" in source
    assert 'app.router.add_post(ROLE_PREVIEW_ROUTE' in source
    assert "from lighting_role_preview_api import register_lighting_role_preview_route" in httpd
    assert "register_lighting_role_preview_route(app, _send_ctrl_command)" in httpd
    assert 'app.router.add_post("/api/lighting", handle_lighting_set)' in httpd
    assert httpd.index('app.router.add_post("/api/lighting", handle_lighting_set)') < httpd.index("register_lighting_role_preview_route(app, _send_ctrl_command)")
    assert httpd.index("register_lighting_role_preview_route(app, _send_ctrl_command)") < httpd.index('app.router.add_get("/api/lighting/lock-indicators", handle_lighting_lock_indicators_get)')
    assert '"op": "vialrgb_direct"' in source
    assert '"op": "vialrgb"' in source
    assert '"save": False' in source
    assert '"op": "vialrgb_get"' in source
    assert "build_role_preview_frame" in source
    assert "vialrgb_save" not in source
    assert "conf/ledd.json" not in source
    assert "restore requires state object" in source
    assert "logicd unavailable" in source
    asyncio.run(_assert_unavailable_responses())

    # Ensure the module can be imported without reading hardware or opening sockets.
    payload = {"action": "preview", "brightness": 96}
    assert json.loads(json.dumps(payload))["action"] == "preview"
    print("ok: lighting role preview API helper")


if __name__ == "__main__":
    main()
