#!/usr/bin/env python3
"""Regression tests for Vial .vil import warnings."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from vil_layout import parse_vil_import  # noqa: E402
from viald.keycode_codec import KeycodeCodec  # noqa: E402


def main() -> None:
    codec = KeycodeCodec(ROOT / "config" / "default" / "keycodes.json")
    kc_a = codec.action_to_vial("KC_A")
    kc_b = codec.action_to_vial("KC_B")
    policy_doc = (ROOT / "docs" / "vial" / "vil-import-policy.md").read_text(encoding="utf-8")

    document = {
        "version": 1,
        "uid": 999,
        "layout": [
            [
                [kc_a, -1, kc_a],
                [0x7FFF, kc_b, kc_a],
                [kc_a, kc_b, kc_a],
            ]
        ],
        "encoder_layout": [
            [
                [kc_a, kc_b, kc_a],
                [kc_b, kc_a],
            ]
        ],
        "settings": {
            "hidloom_export_warnings": ["previous export warning"],
            "unknown_setting": True,
        },
        "unknown_top": {"ignored": True},
    }

    plan = parse_vil_import(
        json.dumps(document),
        expected_uid=123,
        rows=2,
        cols=2,
        encoder_map=[((8, 0), (8, 1))],
        force_uid=True,
        codec=codec,
    )
    assert plan.uid == 999
    assert plan.uid_mismatch is True
    assert any("uid mismatch forced" in warning for warning in plan.warnings)
    assert any("unknown field 'unknown_top' ignored" in warning for warning in plan.warnings)
    assert any("unknown field 'unknown_setting' ignored" in warning for warning in plan.warnings)
    assert any("previous export warning" == warning for warning in plan.warnings)
    assert any("column(s) beyond matrix cols ignored" in warning for warning in plan.warnings)
    assert any("row(s) beyond matrix rows ignored" in warning for warning in plan.warnings)
    assert any("negative keycode" in warning for warning in plan.warnings)
    assert any("unsupported keycode" in warning for warning in plan.warnings)
    assert any("extra value(s) ignored" in warning for warning in plan.warnings)
    assert any("encoder(s) beyond config ignored" in warning for warning in plan.warnings)

    remap_pairs = {(r.layer, r.row, r.col, r.action) for r in plan.remaps}
    assert (0, 0, 0, "KC_A") in remap_pairs
    assert (0, 1, 1, "KC_B") in remap_pairs
    assert (0, 8, 0, "KC_A") in remap_pairs
    assert (0, 8, 1, "KC_B") in remap_pairs

    blocked = parse_vil_import(
        json.dumps({"version": 1, "uid": 999, "layout": [[[kc_a]]]}),
        expected_uid=123,
        rows=1,
        cols=1,
        encoder_map=[],
        force_uid=False,
        codec=codec,
    )
    assert blocked.uid_mismatch is True
    assert blocked.remaps == []
    assert blocked.warnings == []

    for phrase in [
        "UID mismatch かつ force import",
        "unknown top-level field",
        "settings.hidloom_export_warnings",
        "column(s) beyond matrix cols ignored",
        "encoder(s) beyond config ignored",
    ]:
        assert phrase in policy_doc

    print("ok: VIL import warnings")


if __name__ == "__main__":
    main()
