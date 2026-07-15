#!/usr/bin/env python3
"""Regression checks for /api/keymap/active payloads."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon" / "http"))

from keymap_api import keymap_active_response, keymap_layer_lock_clear_response  # noqa: E402


async def test_keymap_active_fallback_includes_all_runtime_sources() -> None:
    async def unavailable() -> None:
        return None

    response = await keymap_active_response(unavailable)
    assert response.status == 503
    payload = response.text
    for field in ["momentary", "toggled", "oneshot", "locked", "conditional", "all"]:
        assert f'"{field}"' in payload


async def test_keymap_active_ok_normalizes_partial_runtime_sources() -> None:
    async def partial() -> dict[str, object]:
        return {"active": {"oneshot": [1], "all": [1, 0]}}

    response = await keymap_active_response(partial)
    assert response.status == 200
    payload = response.text
    assert '"oneshot": [1]' in payload
    assert '"all": [1, 0]' in payload
    for field in ["momentary", "toggled", "locked", "conditional"]:
        assert f'"{field}": []' in payload


async def test_layer_lock_clear_route_only_mutates_runtime_lock() -> None:
    calls: list[dict[str, object]] = []
    audit: list[dict[str, object]] = []

    async def send_ctrl(payload: dict[str, object]) -> dict[str, object]:
        calls.append(payload)
        return {
            "t": "LAYER_LOCK_CLEAR",
            "result": "ok",
            "changed": True,
            "locked_before": [2],
            "active": {"locked": [], "all": [0]},
        }

    def audit_log(_request: object, action: str, **fields: object) -> None:
        audit.append({"action": action, **fields})

    response = await keymap_layer_lock_clear_response(object(), send_ctrl, audit_log)
    assert response.status == 200
    assert calls == [{"t": "LAYER_LOCK_CLEAR"}]
    assert '"locked_before": [2]' in response.text
    assert '"active": {"locked": [], "all": [0]}' in response.text
    assert audit[-1]["action"] == "layer_lock_clear"
    assert audit[-1]["changed"] == "true"


def main() -> None:
    asyncio.run(test_keymap_active_fallback_includes_all_runtime_sources())
    asyncio.run(test_keymap_active_ok_normalizes_partial_runtime_sources())
    asyncio.run(test_layer_lock_clear_route_only_mutates_runtime_lock())
    print("ok: /api/keymap/active includes runtime layer sources")


if __name__ == "__main__":
    main()
