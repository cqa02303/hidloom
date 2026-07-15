#!/usr/bin/env python3
"""Regression tests for http.interaction_builder_ux."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "daemon" / "http"))

from interaction_builder_ux import (  # noqa: E402
    INTERACTION_BUILDER_UX_ROUTE,
    builder_subtitle,
    interaction_builder_ux_payload,
    interaction_builder_ux_specs,
)


def test_builder_specs_cover_existing_builders() -> None:
    specs = interaction_builder_ux_specs()

    assert set(specs) == {"combo", "tap_dance", "key_override", "timing"}
    assert specs["combo"]["title"] == "Combo builder"
    assert specs["tap_dance"]["title"] == "Tap Dance builder"
    assert specs["key_override"]["title"] == "Key Override builder"
    assert specs["timing"]["title"] == "Advanced Timing"


def test_combo_source_policy_prefers_matrix_position() -> None:
    combo = interaction_builder_ux_specs()["combo"]

    assert "matrix position" in combo["warnings"][0]
    assert "row/col" in combo["source_policy"]
    assert combo["save_scope"] == "settings.interaction.combos[]"
    assert "keycode" in combo["warnings"][0]


def test_tap_dance_and_override_policies_are_not_matrix_positions() -> None:
    specs = interaction_builder_ux_specs()

    tap = specs["tap_dance"]
    assert tap["save_scope"] == "settings.interaction.tap_dances{}"
    assert "TD(name)" in " ".join(tap["warnings"])
    assert "row/col" not in tap["source_policy"]

    override = specs["key_override"]
    assert override["save_scope"] == "settings.interaction.key_overrides[]"
    assert "Action picker" in override["source_policy"]
    assert "row/col" in " ".join(override["warnings"])


def test_payload_selection_modes_and_non_goals() -> None:
    payload = interaction_builder_ux_payload()

    assert payload["schema"] == "interaction.builder_ux.v1"
    assert payload["route"] == INTERACTION_BUILDER_UX_ROUTE
    assert payload["result"] == "ok"
    assert payload["read_only"] is True
    assert "matrix_position" in payload["selection_modes"]
    assert "action_picker" in payload["selection_modes"]
    assert payload["polish_status"]["schema"] == "interaction.builder_ux.polish.v1"
    assert payload["polish_status"]["status"] == "first_slice_complete"
    assert payload["polish_status"]["tap_dance"]["assignment_action"] == "TD(name)"
    assert payload["polish_status"]["tap_dance"]["rename_updates_existing_definition"] is True
    assert payload["polish_status"]["tap_dance"]["source_key_assignment"] == "keymap_remap_flow"
    assert payload["polish_status"]["key_override"]["source_key_assignment"] == "not_matrix_position"
    assert payload["polish_status"]["warning_display"]["dedupe_rule"].startswith("metadata helper text")
    assert payload["polish_status"]["next_local_todo"] == "runtime_feedback_or_real_device_touch_flick"
    assert "builder helper は設定を保存しない" in payload["non_goals"]
    assert "combo" in payload["builders"]


def test_builder_subtitle() -> None:
    assert builder_subtitle("combo").startswith("複数の物理キー")
    assert builder_subtitle("missing") == ""


def test_httpd_registers_builder_ux_route() -> None:
    httpd_py = (ROOT / "daemon/http/httpd.py").read_text(encoding="utf-8")
    assert "register_interaction_builder_ux_route(app)" in httpd_py
    assert "from interaction_builder_ux import register_interaction_builder_ux_route" in httpd_py


def main() -> None:
    test_builder_specs_cover_existing_builders()
    test_combo_source_policy_prefers_matrix_position()
    test_tap_dance_and_override_policies_are_not_matrix_positions()
    test_payload_selection_modes_and_non_goals()
    test_builder_subtitle()
    test_httpd_registers_builder_ux_route()
    print("ok: interaction builder UX metadata keeps source/action boundaries clear")


if __name__ == "__main__":
    main()
