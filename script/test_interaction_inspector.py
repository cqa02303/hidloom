#!/usr/bin/env python3
"""Regression tests for the read-only Interaction inspector."""
from __future__ import annotations

import json
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon" / "http"))
sys.path.insert(0, str(ROOT))

if "aiohttp" not in sys.modules:
    aiohttp_stub = types.ModuleType("aiohttp")
    web_stub = types.SimpleNamespace(Response=object, json_response=lambda *args, **kwargs: None, Application=object)
    aiohttp_stub.web = web_stub
    sys.modules["aiohttp"] = aiohttp_stub
    sys.modules["aiohttp.web"] = web_stub

from interaction_inspector import (  # noqa: E402
    INTERACTION_INSPECTOR_ROUTE,
    build_interaction_inspector_payload,
)


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        config = tmp / "config.json"
        vial = tmp / "vial.json"
        write_json(vial, {"matrix": {"rows": 2, "cols": 3}})
        data = {
            "layers": [{"0,0": "KC_A"}, {"0,0": "KC_B"}],
            "settings": {
                "interaction": {
                    "combo_term": 0.3,
                    "tap_dance_term": 0.2,
                    "combos": [
                        {"keys": [[0, 0], [0, 1]], "action": "KC_ESC"},
                        {"keys": [[0, 1], [0, 0]], "action": "KC_TAB"},
                        {"keys": [[1, 1], [9, 9]], "action": "KC_A"},
                    ],
                    "tap_dances": {
                        "TD0": {"term": 1.0},
                        "td0": {"1": "KC_A"},
                    },
                    "key_overrides": [
                        {"trigger": "KC_LSFT", "key": "KC_1", "replacement": "KC_EXLM", "layers": 0},
                        {"trigger": "KC_LSFT", "key": "KC_1", "replacement": "KC_EXLM", "layers": 0},
                    ],
                }
            },
        }
        write_json(config, data)
        before = config.read_text(encoding="utf-8")

        payload = build_interaction_inspector_payload(config, vial)

        assert payload["result"] == "ok"
        assert payload["schema"] == {"route": INTERACTION_INSPECTOR_ROUTE, "version": 1}
        assert payload["summary"]["combos"] == 3
        assert payload["summary"]["tap_dances"] == 2
        assert payload["summary"]["key_overrides"] == 2
        assert payload["summary"]["mod_morphs"] == 1
        assert payload["summary"]["warnings"] > 0
        assert set(payload["sections"]) == {"combos", "tap_dances", "key_overrides", "mod_morphs"}
        assert payload["sections"]["mod_morphs"][0]["label"] == "GRAVE_ESCAPE"
        assert payload["sections"]["mod_morphs"][0]["details"]["built_in"] is True

        messages = [warning["message"] for warning in payload["warnings"]]
        assert any("same key set" in message for message in messages)
        assert any("outside matrix" in message for message in messages)
        assert any("source key 0,0 is shared" in message for message in messages)
        assert any("has no tap count actions" in message for message in messages)
        assert any("same condition" in message for message in messages)
        assert config.read_text(encoding="utf-8") == before

    httpd = (ROOT / "daemon" / "http" / "httpd.py").read_text(encoding="utf-8")
    interaction_js = (ROOT / "daemon" / "http" / "static" / "interaction_panel.js").read_text(encoding="utf-8")
    interaction_css = (ROOT / "daemon" / "http" / "static" / "interaction_panel.css").read_text(encoding="utf-8")
    assert "from interaction_inspector import register_interaction_inspector_route" in httpd
    assert "register_interaction_inspector_route(app, CONFIG_JSON, VIAL_JSON)" in httpd
    assert 'fetch("/api/interaction/inspector")' in interaction_js
    assert "flattenInteractionInspectorWarnings" in interaction_js
    assert "interaction-inspector-rows" in interaction_js
    assert ".interaction-inspector-row" in interaction_css
    assert ".interaction-inspector-error" in interaction_css

    print("ok: interaction inspector")


if __name__ == "__main__":
    main()
