#!/usr/bin/env python3
"""Smoke tests for KML / QMK macro integration groundwork helpers."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.macro_integration import (  # noqa: E402
    build_macro_runner_plan,
    parse_macro_runner_action,
    resolve_macro_file,
    validate_macro_text,
    vial_macro_boundary,
)


def main() -> None:
    assert parse_macro_runner_action("KML(layer_alpha)").kind == "kml"
    assert parse_macro_runner_action("QMK_MACRO(layer_alpha)").kind == "qmk"
    assert parse_macro_runner_action("KC_KML0") is None
    assert parse_macro_runner_action("KML(bad/name)") is None

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        runtime = base / "runtime"
        factory = base / "factory"
        (runtime / "kml").mkdir(parents=True)
        (runtime / "qmk").mkdir(parents=True)
        (factory / "kml").mkdir(parents=True)
        (factory / "qmk").mkdir(parents=True)
        legacy = base / "kml"
        legacy.mkdir()

        (factory / "kml" / "fallback.kml").write_text("tap KC_A\ndelay 10\ntext hello\n", encoding="utf-8")
        (runtime / "kml" / "preferred.kml").write_text("tap KC_B\n", encoding="utf-8")
        (factory / "kml" / "preferred.kml").write_text("tap KC_C\n", encoding="utf-8")
        (legacy / "legacy.kml").write_text("tap KC_Z\n", encoding="utf-8")
        (runtime / "qmk" / "layer_alpha.qmk").write_text(
            'SEND_STRING("ABC")\nTAP_CODE(KC_ENTER)\nWAIT_MS(25)\nTAP_CODE16(TO(1))\n',
            encoding="utf-8",
        )
        (runtime / "qmk" / "bad.qmk").write_text("#include <stdio.h>\nSYSTEM(KC_A)\n", encoding="utf-8")

        fallback = resolve_macro_file("kml", "fallback", runtime_root=runtime, factory_root=factory)
        assert fallback["found"]
        assert fallback["source"] == "factory"
        assert not fallback["legacy_paths_read"]

        preferred = resolve_macro_file("kml", "preferred", runtime_root=runtime, factory_root=factory)
        assert preferred["source"] == "runtime"

        missing_legacy = resolve_macro_file("kml", "legacy", runtime_root=runtime, factory_root=factory)
        assert not missing_legacy["found"]
        assert missing_legacy["error"] == "macro_file_not_found"
        assert str(legacy / "legacy.kml") not in missing_legacy["searched"]

        kml_plan = build_macro_runner_plan("KML(preferred)", runtime_root=runtime, factory_root=factory)
        assert not kml_plan["blocking_reasons"]
        assert kml_plan["validation"]["commands"] == ("tap KC_B",)
        assert kml_plan["dry_run"]
        assert not kml_plan["real_run_allowed"]
        assert not kml_plan["sends_hid_reports"]
        assert kml_plan["uses_logicd_output_path"]
        assert not kml_plan["direct_key_events_sock_write"]
        assert not kml_plan["fixed_slot_keycode_added"]

        qmk_plan = build_macro_runner_plan("QMK_MACRO(layer_alpha)", runtime_root=runtime, factory_root=factory)
        assert not qmk_plan["blocking_reasons"]
        assert qmk_plan["kind"] == "qmk"
        assert 'SEND_STRING("ABC")' in qmk_plan["validation"]["commands"]
        assert not qmk_plan["vial_macro_buffer_source"]

        bad_plan = build_macro_runner_plan("QMK_MACRO(bad)", runtime_root=runtime, factory_root=factory)
        assert "forbidden_action_or_code" in bad_plan["blocking_reasons"]

    invalid_kml = validate_macro_text("kml", "tap KC_A\nBT_POWER_OFF\n")
    assert not invalid_kml["valid"]
    assert "forbidden_action_or_code" in invalid_kml["errors"]
    assert "unsupported_command:BT_POWER_OFF" in invalid_kml["errors"]

    invalid_qmk = validate_macro_text("qmk", "TAP_CODE(KC_A)\nSCRIPT(foo)\n")
    assert not invalid_qmk["valid"]
    assert "forbidden_action_or_code" in invalid_qmk["errors"]

    boundary = vial_macro_boundary({
        "settings": {"vial_macro_buffer": "SGkA"},
        "macros": {"VIAL0": ["{KC:KC_A}"]},
    })
    assert boundary["raw_buffer_present"]
    assert boundary["expanded_macro_count"] == 1
    assert not boundary["raw_buffer_executable"]
    assert boundary["runtime_source"] == "expanded_local_macros"
    assert boundary["import_export_source"] == "settings.vial_macro_buffer"
    assert not boundary["auto_converts_system_actions"]

    print("ok: KML / QMK macro integration groundwork helpers")


if __name__ == "__main__":
    main()
