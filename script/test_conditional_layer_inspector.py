#!/usr/bin/env python3
"""Regression tests for logicd.conditional_layer_inspector."""
from __future__ import annotations

import json
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "daemon" / "http"))

if "aiohttp" not in sys.modules:
    aiohttp_stub = types.ModuleType("aiohttp")
    web_stub = types.SimpleNamespace(Response=object, json_response=lambda *args, **kwargs: None)
    aiohttp_stub.web = web_stub
    sys.modules["aiohttp"] = aiohttp_stub
    sys.modules["aiohttp.web"] = web_stub

from logicd.conditional_layer_inspector import (  # noqa: E402
    conditional_layer_inspector_payload,
    conditional_layer_rule_warnings,
)
from conditional_layer_inspector_api import (  # noqa: E402
    CONDITIONAL_LAYER_INSPECTOR_ROUTE,
    conditional_layer_http_payload,
)


def messages(warnings):
    return [(warning.name, warning.severity, warning.message) for warning in warnings]


def test_inspector_separates_manual_and_conditional_active_layers() -> None:
    payload = conditional_layer_inspector_payload(
        [
            {"name": "lower_raise_adjust", "if_all": [1, 2], "then": 3},
        ],
        {
            "momentary": [1],
            "toggled": [2],
            "oneshot": [],
            "locked": [],
            "conditional": [3],
            "all": [3, 2, 1, 0],
        },
    )

    assert payload["schema"] == "conditional_layers.inspector.v1"
    assert payload["read_only"] is True
    assert payload["chain_activation_supported"] is False
    assert payload["manual_active"] == [0, 1, 2]
    assert payload["active_conditional"] == [3]
    assert payload["rules"] == [
        {
            "name": "lower_raise_adjust",
            "if_all": [1, 2],
            "then": 3,
            "active": True,
            "source_active": [1, 2],
            "source_missing": [],
            "chain_ignored": False,
        }
    ]


def test_inspector_reports_missing_sources() -> None:
    payload = conditional_layer_inspector_payload(
        [{"name": "tri", "if_all": [1, 2], "then": 3}],
        {"momentary": [1], "conditional": [], "all": [1, 0]},
    )

    rule = payload["rules"][0]
    assert rule["active"] is False
    assert rule["source_active"] == [1]
    assert rule["source_missing"] == [2]
    assert payload["active_conditional"] == []


def test_warnings_cover_invalid_and_attention_cases() -> None:
    warnings = conditional_layer_rule_warnings([
        {"name": "too_few", "if_all": [1], "then": 2},
        {"name": "dup", "if_all": [1, 1], "then": 2},
        {"name": "self", "if_all": [2, 3], "then": 2},
        {"name": "bad", "if_all": ["x", 1], "then": 4},
        {"name": "a", "if_all": [1, 2], "then": 5},
        {"name": "b", "if_all": [2, 3], "then": 5},
    ])
    text = messages(warnings)

    assert ("too_few", "warning", "if_all should contain at least two source layers") in text
    assert ("dup", "warning", "if_all contains duplicate source layers") in text
    assert ("self", "error", "then layer must not also be a source") in text
    assert ("bad", "error", "rule contains non-integer layer") in text
    assert ("a,b", "info", "multiple rules share target layer 5") in text


def test_chain_activation_is_marked_but_not_supported() -> None:
    payload = conditional_layer_inspector_payload(
        [
            {"name": "tri", "if_all": [1, 2], "then": 3},
            {"name": "chain", "if_all": [1, 3], "then": 4},
        ],
        {
            "momentary": [1, 2],
            "conditional": [3],
            "all": [3, 2, 1, 0],
        },
    )

    assert payload["chain_activation_supported"] is False
    chain = payload["rules"][1]
    assert chain["chain_ignored"] is True
    assert chain["source_active"] == [1]
    assert chain["source_missing"] == [3]
    warning_messages = [warning["message"] for warning in payload["warnings"]]
    assert "chain activation is not evaluated; conditional source(s) ignored: [3]" in warning_messages


def test_locked_layers_count_as_manual_sources() -> None:
    payload = conditional_layer_inspector_payload(
        [{"name": "locked_source", "if_all": [1, 2], "then": 3}],
        {
            "momentary": [1],
            "locked": [2],
            "conditional": [3],
            "all": [3, 2, 1, 0],
        },
    )

    assert payload["manual_active"] == [0, 1, 2]
    assert payload["rules"][0]["source_active"] == [1, 2]
    assert payload["rules"][0]["active"] is True


def test_http_payload_uses_saved_rules_and_active_source() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        config_json = Path(tmpdir) / "config.json"
        config_json.write_text(json.dumps({
            "settings": {
                "interaction": {
                    "conditional_layers": [
                        {"name": "tri", "if_all": [1, 2], "then": 3},
                    ],
                },
            },
        }), encoding="utf-8")

        payload = conditional_layer_http_payload(
            config_json,
            {"momentary": [1], "toggled": [2], "conditional": [3], "all": [3, 2, 1, 0]},
            logicd_available=True,
        )

    assert payload["result"] == "ok"
    assert payload["route"] == CONDITIONAL_LAYER_INSPECTOR_ROUTE
    assert payload["logicd_available"] is True
    assert payload["active_source"] == "logicd"
    assert payload["schema"] == "conditional_layers.inspector.v1"
    assert payload["rule_count"] == 1
    assert payload["rules"][0]["active"] is True


def test_httpd_registers_conditional_layer_inspector_route() -> None:
    httpd = (ROOT / "daemon/http/httpd.py").read_text(encoding="utf-8")
    assert "from conditional_layer_inspector_api import register_conditional_layer_inspector_route" in httpd
    assert "register_conditional_layer_inspector_route(app, CONFIG_JSON, _query_logicd_active_layers)" in httpd


def main() -> None:
    test_inspector_separates_manual_and_conditional_active_layers()
    test_inspector_reports_missing_sources()
    test_warnings_cover_invalid_and_attention_cases()
    test_chain_activation_is_marked_but_not_supported()
    test_locked_layers_count_as_manual_sources()
    test_http_payload_uses_saved_rules_and_active_source()
    test_httpd_registers_conditional_layer_inspector_route()
    print("ok: conditional layer inspector separates rules and runtime state")


if __name__ == "__main__":
    main()
