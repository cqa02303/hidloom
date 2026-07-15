#!/usr/bin/env python3
"""Tests for the InteractionEngine physical runtime helper."""
from __future__ import annotations

import importlib.util
import json
import tempfile
from types import SimpleNamespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "interaction_physical_runtime.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("interaction_physical_runtime", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    tool = load_tool()
    native_calls: list[list[str]] = []

    def native_runner(command, **_kwargs):
        native_calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    tool.reload_logicd(enabled=True, run_command=native_runner)
    assert native_calls == [
        ["systemctl", "is-active", "--quiet", "logicd-companion"],
        ["systemctl", "reload", "logicd-companion"],
    ]

    legacy_calls: list[list[str]] = []

    def legacy_runner(command, **_kwargs):
        legacy_calls.append(command)
        return SimpleNamespace(
            returncode=3 if command[-1] == "logicd-companion" else 0,
            stdout="",
            stderr="",
        )

    tool.reload_logicd(enabled=True, run_command=legacy_runner)
    assert legacy_calls == [
        ["systemctl", "is-active", "--quiet", "logicd-companion"],
        ["systemctl", "is-active", "--quiet", "logicd"],
        ["systemctl", "reload", "logicd"],
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        config = tmp / "config.json"
        backup = tmp / "backup.json"
        original_interaction = {
            "tapping_term": 0.18,
            "combos": [{"keys": [[9, 9], [9, 8]], "action": "KC_TAB"}],
            "tap_dances": {"USER": {"1": "KC_B"}},
            "key_overrides": [{"trigger": "KC_LCTL", "key": "KC_2", "replacement": "KC_TAB"}],
        }
        write_json(config, {"settings": {"interaction": original_interaction}, "keep": {"value": 1}})

        missing = tool.definition_status(config)
        assert missing["ready"] is False
        assert missing["tap_dance"]["ready"] is False
        assert missing["combo"]["ready"] is False
        assert missing["key_override"]["ready"] is False

        tool.apply_test_definitions(config, backup)
        ready = tool.definition_status(config)
        assert ready["ready"] is True
        assert ready["tap_dance"]["ready"] is True
        assert ready["combo"]["ready"] is True
        assert ready["key_override"]["ready"] is True
        stored = json.loads(config.read_text(encoding="utf-8"))
        interaction = stored["settings"]["interaction"]
        assert interaction["tap_dances"]["TD0"]["1"] == "KC_A"
        assert interaction["tap_dances"]["TD0"]["2"] == "KC_ESC"
        assert interaction["tap_dances"]["TD0"]["3"] == "KC_TAB"
        assert "hold" not in interaction["tap_dances"]["TD0"]
        assert "tap_hold" not in interaction["tap_dances"]["TD0"]
        assert {"keys": [[0, 1], [0, 2]], "action": "KC_ESC"} in interaction["combos"]
        assert {"trigger": "KC_LSFT", "key": "KC_1", "replacement": "KC_ESC"} in interaction["key_overrides"]
        assert stored["keep"] == {"value": 1}

        # Re-applying must not duplicate list definitions or overwrite the original backup.
        tool.apply_test_definitions(config, backup)
        reapplied = json.loads(config.read_text(encoding="utf-8"))["settings"]["interaction"]
        assert reapplied["combos"].count({"keys": [[0, 1], [0, 2]], "action": "KC_ESC"}) == 1
        assert reapplied["key_overrides"].count(
            {"trigger": "KC_LSFT", "key": "KC_1", "replacement": "KC_ESC"},
        ) == 1

        tool.restore_test_definitions(config, backup)
        restored = json.loads(config.read_text(encoding="utf-8"))
        assert restored["settings"]["interaction"] == original_interaction
        assert restored["keep"] == {"value": 1}
        assert not backup.exists()

    print("ok: interaction physical runtime helper")


if __name__ == "__main__":
    main()
