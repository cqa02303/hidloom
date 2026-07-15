#!/usr/bin/env python3
"""Regression tests for MORSE feedback HTTP bridge and UI."""
from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon" / "http"))
sys.path.insert(0, str(ROOT))

if "aiohttp" not in sys.modules:
    class FakeResponse:
        def __init__(self, data, status: int = 200):
            self.text = json.dumps(data)
            self.status = status

    aiohttp_stub = types.ModuleType("aiohttp")
    web_stub = types.SimpleNamespace(
        Response=FakeResponse,
        Application=object,
        Request=object,
        json_response=lambda data, status=200, **_kwargs: FakeResponse(data, status=status),
    )
    aiohttp_stub.web = web_stub
    sys.modules["aiohttp"] = aiohttp_stub
    sys.modules["aiohttp.web"] = web_stub

from morse_feedback_api import MORSE_FEEDBACK_ROUTE, morse_feedback_response  # noqa: E402


def response_json(response) -> dict:
    return json.loads(response.text)


async def test_morse_feedback_response_ok() -> None:
    async def send_ctrl(cmd: dict) -> dict:
        assert cmd == {"t": "MORSE_FEEDBACK"}
        return {
            "t": "MORSE_FEEDBACK",
            "result": "ok",
            "events": [{"type": "morse", "phase": "commit", "sequence": ".", "action": "KC_E"}],
            "count": 1,
        }

    response = await morse_feedback_response(send_ctrl)
    payload = response_json(response)
    assert response.status == 200
    assert payload["result"] == "ok"
    assert payload["count"] == 1
    assert payload["schema"]["route"] == MORSE_FEEDBACK_ROUTE
    assert payload["schema"]["drain"] is True


async def test_morse_feedback_response_unavailable() -> None:
    async def send_ctrl(_cmd: dict) -> None:
        return None

    response = await morse_feedback_response(send_ctrl)
    payload = response_json(response)
    assert response.status == 503
    assert payload["result"] == "error"
    assert payload["events"] == []


def test_static_assets_are_wired() -> None:
    httpd = (ROOT / "daemon" / "http" / "httpd.py").read_text(encoding="utf-8")
    morse_js = (ROOT / "daemon" / "http" / "static" / "morse_inspector_panel.js").read_text(encoding="utf-8")
    css = (ROOT / "daemon" / "http" / "static" / "interaction_panel.css").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "morse" / "behavior-current.md").read_text(encoding="utf-8")

    assert "from morse_feedback_api import register_morse_feedback_route" in httpd
    assert "register_morse_feedback_route(app, _send_ctrl_command)" in httpd
    assert 'fetch("/api/interaction/morse-feedback", { credentials: "same-origin" })' in morse_js
    assert "startMorseFeedbackPolling" in morse_js
    assert "interaction-morse-feedback" in morse_js
    assert ".interaction-morse-feedback" in css
    assert "/api/interaction/morse-feedback" in docs


def main() -> None:
    assert MORSE_FEEDBACK_ROUTE == "/api/interaction/morse-feedback"
    asyncio.run(test_morse_feedback_response_ok())
    asyncio.run(test_morse_feedback_response_unavailable())
    test_static_assets_are_wired()
    print("ok: MORSE feedback HTTP bridge")


if __name__ == "__main__":
    main()
