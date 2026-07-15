#!/usr/bin/env python3
"""Regression tests for read-only MORSE inspector."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "daemon" / "http"))

from morse_inspector import (  # noqa: E402
    MORSE_INSPECTOR_ROUTE,
    build_morse_inspector_payload,
    inspect_morse_behavior,
)


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def test_inspect_morse_behavior_tree_states() -> None:
    inspected = inspect_morse_behavior(
        "main",
        {
            "dot_threshold": 0.18,
            "sequence_timeout": 0.7,
            "max_depth": 3,
            "force_commit": [".-"],
            "map": {
                ".": "KC_E",
                ".-": "KC_A",
                ".-.": "KC_R",
                "-": "KC_T",
            },
        },
    )

    assert inspected["name"] == "main"
    assert inspected["summary"]["mapped_sequences"] == 4
    assert inspected["summary"]["force_commit_sequences"] == 1
    assert any("force_commit .- hides deeper" in warning for warning in inspected["warnings"])

    root = inspected["tree"]
    assert root["state"] == "root"
    dot = next(child for child in root["children"] if child["sequence"] == ".")
    dash = next(child for child in root["children"] if child["sequence"] == "-")
    assert dot["state"] == "prefix"
    assert dash["state"] == "leaf"
    forced = next(child for child in dot["children"] if child["sequence"] == ".-")
    assert forced["state"] == "force_commit"
    hidden = next(child for child in forced["children"] if child["sequence"] == ".-.")
    assert hidden["reachable"] is False
    assert hidden["hidden_by_force_commit"] == ".-"


def test_build_payload_from_config() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        config = Path(tmp) / "config.json"
        vial = Path(tmp) / "vial.json"
        write_json(vial, {"matrix": {"rows": 2, "cols": 3}})
        write_json(config, {
            "settings": {
                "interaction": {
                    "morse_behaviors": {
                        "main": {
                            "dot_threshold": 0.2,
                            "sequence_timeout": 0.8,
                            "max_depth": 3,
                            "force_commit": [".-"],
                            "map": {".": "KC_E", ".-": "KC_A", ".-.": "KC_R"},
                        }
                    }
                }
            }
        })

        payload = build_morse_inspector_payload(config, vial)

    assert payload["result"] == "ok"
    assert payload["schema"]["route"] == MORSE_INSPECTOR_ROUTE
    assert payload["schema"]["editor"] == "read_only"
    assert payload["schema"]["force_commit_name"] == "force_commit"
    assert payload["summary"]["behaviors"] == 1
    assert payload["summary"]["mapped_sequences"] == 3
    assert payload["summary"]["force_commit_sequences"] == 1
    assert payload["behaviors"][0]["name"] == "main"


def test_static_assets_are_wired() -> None:
    tabs_js = (ROOT / "daemon" / "http" / "static" / "tabs.js").read_text(encoding="utf-8")
    morse_js = (ROOT / "daemon" / "http" / "static" / "morse_inspector_panel.js").read_text(encoding="utf-8")
    interaction_js = (ROOT / "daemon" / "http" / "static" / "interaction_panel.js").read_text(encoding="utf-8")
    css = (ROOT / "daemon" / "http" / "static" / "interaction_panel.css").read_text(encoding="utf-8")
    httpd_py = (ROOT / "daemon" / "http" / "httpd.py").read_text(encoding="utf-8")

    assert "ensureMorseInspectorPanelScript" in tabs_js
    assert "/static/morse_inspector_panel.js" in tabs_js
    assert "renderMorseInspectorFromEditor" in morse_js
    assert "insertMorseBehaviorSnippet" in morse_js
    assert "interaction-morse-snippet-btn" in morse_js
    assert "MORSE_SNIPPET" in morse_js
    assert '"force_commit": [".-"]' in morse_js
    assert '"fallback_action": "KC_ESC"' in morse_js
    assert "const MORSE_DEFAULT_MAP_TEXT = `.=KC_NO\n-=KC_NO`" in morse_js
    assert 'id="interaction-morse-force" type="hidden" value=""' in morse_js
    assert "interaction-morse-fallback" in morse_js
    assert 'id="interaction-morse-fallback" class="interaction-action-input" type="text" value=""' in morse_js
    assert 'input.setAttribute("list", "interaction-action-datalist")' not in morse_js
    assert "sequence.length > 1 && !actions[sequence]" in morse_js
    assert "<span>Name</span>" not in morse_js
    assert "Load by name" not in morse_js
    assert "Morseを追加" in morse_js
    assert "promptAddMorseBehavior" in morse_js
    assert "addMorseBehaviorByName" in morse_js
    assert "interaction-morse-top-actions" in morse_js
    assert "Morseを保存してreload" in morse_js
    assert "interaction-morse-depth" not in morse_js
    assert "Max depth" not in morse_js
    assert "inferredMorseMaxDepth" in morse_js
    assert "MORSE_EDITOR_MAX_DEPTH" in morse_js
    assert "morseFallbackAction" in morse_js
    assert "fallback_action" in morse_js
    assert "ensureMorseEditorPanel" in morse_js
    assert "interaction-morse-builder" in morse_js
    assert "interaction-morse-accordion" in morse_js
    assert "interaction-gui-editors" in morse_js
    assert "interaction-morse-tree-editor" in morse_js
    assert "renderMorseTreeEditorFromBuilder" in morse_js
    assert "addMorseTreeSequence" in morse_js
    assert "toggleMorseTreeSequence" in morse_js
    assert "expandMorseTreeSequence" in morse_js
    assert "ensureMorseTreeChildren" in morse_js
    assert "deleteMorseBehaviorBuilder" in morse_js
    assert "interaction-morse-existing" in morse_js
    assert "interaction-morse-hidden-state" in morse_js
    assert "force_commit CSV" not in morse_js
    assert "Map: sequence=action" not in morse_js
    assert "pickMorseFallbackAction" in morse_js
    assert "pickMorseTreeAction" in morse_js
    assert "openInteractionActionPicker" in morse_js
    assert "force_commit ${sequence} hides deeper sequence" in morse_js
    assert "applyMorseBehaviorBuilder" in morse_js
    assert "flushMorseBehaviorBuilderToEditor" in morse_js
    assert "saveMorseBehaviorBuilder" in morse_js
    assert "flushMorseBehaviorBuilderToEditor" in interaction_js
    assert "loadMorseBehaviorIntoBuilder" not in morse_js
    assert "insertMorseActionForBuilder" not in morse_js
    assert "copyMorseActionForBuilder" in morse_js
    assert "Copy MORSE(name)" in morse_js
    assert ".interaction-icon-btn" in css
    assert "morseMapTextToObject" in morse_js
    assert "MORSE(${name})" in morse_js
    assert "force_commit" in morse_js
    assert "interaction-morse-inspector" in morse_js
    assert ".interaction-morse-inspector" in css
    assert ".interaction-morse-builder-actions" in css
    assert ".interaction-accordion" in css
    assert ".interaction-morse-tree-editor" in css
    assert ".interaction-morse-tree-warning" in css
    assert ".interaction-morse-tree-toggle" in css
    assert ".interaction-morse-sequence-cell" in css
    assert ".interaction-morse-action-field" in css
    assert ".interaction-morse-hidden-state" in css
    assert ".interaction-morse-row.morse-force_commit" in css
    assert "from morse_inspector import register_morse_inspector_route" in httpd_py
    assert "register_morse_inspector_route(app, CONFIG_JSON, VIAL_JSON)" in httpd_py


def main() -> None:
    assert MORSE_INSPECTOR_ROUTE == "/api/interaction/morse-inspector"
    test_inspect_morse_behavior_tree_states()
    test_build_payload_from_config()
    test_static_assets_are_wired()
    print("ok: MORSE inspector")


if __name__ == "__main__":
    main()
