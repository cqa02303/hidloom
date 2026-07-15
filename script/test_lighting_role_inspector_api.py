#!/usr/bin/env python3
"""Tests for the read-only lighting role inspector."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "daemon" / "http"))

from lighting_role_inspector import (  # noqa: E402
    ROLE_INSPECTOR_ROUTE,
    build_role_inspector_payload,
    inspect_key_role,
    role_inspector_response,
)
from ledd.semantic_roles import normalize_led_semantic_role_config  # noqa: E402


async def _assert_response_uses_logicd_layers() -> None:
    async def query_layers() -> dict:
        return {"layers": [{"0,0": "KC_A", "0,1": "KC_LSFT", "0,2": "BT_POWER_OFF"}]}

    resp = await role_inspector_response(query_layers)
    assert resp.status == 200
    data = json.loads(resp.text)
    assert data["result"] == "ok"
    assert data["summary"]["modifier"] == 1
    assert data["summary"]["system"] == 1
    assert data["layers"][0]["keys"][1]["reason"] == "KC_LSFT is a modifier key"


def main() -> None:
    assert ROLE_INSPECTOR_ROUTE == "/api/lighting/role-inspector"

    semantic = normalize_led_semantic_role_config({"roles": {"KC_A": "function"}})
    assert inspect_key_role("KC_A", semantic) == {
        "role": "function",
        "source": "semantic_roles_config",
        "reason": "KC_A is configured as function",
        "confidence": "high",
    }
    assert inspect_key_role("KC_LCTL", semantic)["source"] == "keycode_rule"
    assert inspect_key_role("KC_BTN1", semantic)["role"] == "normal"
    assert inspect_key_role("KC_B", semantic)["source"] == "fallback"

    with tempfile.TemporaryDirectory() as tmpdir:
        ledd_json = Path(tmpdir) / "ledd.json"
        ledd_json.write_text('{"semantic_roles":{"roles":{"KC_A":"function"}}}', encoding="utf-8")
        payload = build_role_inspector_payload(
            [{"0,1": "KC_A", "0,0": "KC_LSFT", "0,2": "MO(1)", "0,3": "BT_POWER_OFF"}],
            ledd_json=ledd_json,
        )
    assert payload["result"] == "ok"
    assert payload["summary"]["function"] == 1
    assert payload["summary"]["modifier"] == 1
    assert payload["summary"]["layer"] == 1
    assert payload["summary"]["system"] == 1
    assert payload["source_summary"]["semantic_roles_config"] == 1
    assert payload["schema"]["manual_override_editor"] is False
    assert [item["col"] for item in payload["layers"][0]["keys"]] == [0, 1, 2, 3]

    source = (ROOT / "daemon" / "http" / "lighting_role_inspector.py").read_text(encoding="utf-8")
    httpd = (ROOT / "daemon" / "http" / "httpd.py").read_text(encoding="utf-8")
    lighting_js = (ROOT / "daemon" / "http" / "static" / "lighting_panel.js").read_text(encoding="utf-8")
    lighting_css = (ROOT / "daemon" / "http" / "static" / "lighting_panel.css").read_text(encoding="utf-8")
    assert "def register_lighting_role_inspector_route" in source
    assert "from lighting_role_inspector import register_lighting_role_inspector_route" in httpd
    assert "register_lighting_role_inspector_route(app, _query_logicd_layers)" in httpd
    assert 'fetch("/api/lighting/role-inspector")' in lighting_js
    assert "function updateLightingRoleInspectorPanel(payload)" in lighting_js
    assert "lighting-role-inspector-list" in lighting_js
    assert ".lighting-role-inspector-row" in lighting_css

    asyncio.run(_assert_response_uses_logicd_layers())
    print("ok: lighting role inspector API")


if __name__ == "__main__":
    main()
