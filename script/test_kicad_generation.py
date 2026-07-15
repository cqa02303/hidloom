#!/usr/bin/env python3
"""Regression checks for KiCad-derived generation helpers."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build" / "generators"))

import analyze_kicad_pcb_led as led_gen  # noqa: E402
import mkvial  # noqa: E402


GENERATED_OUTPUTS = (
    "build/generated/keymap_matrix_analysis.json",
    "build/generated/keymap_matrix_analysis_final_report.txt",
    "build/generated/pcb_analysis.json",
    "build/generated/pcb_analysis_sw_report.txt",
    "build/generated/vial_generation_report.txt",
    "config/default/vial.json",
)


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _assert_generated_outputs_are_fresh() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        fixture = Path(tmp)
        for source in (ROOT / "build" / "generators").glob("*.py"):
            _copy_file(source, fixture / source.relative_to(ROOT))
        for relative in (
            "kicad/cqa02303v5rpi/keymap.kicad_sch",
            "kicad/cqa02303v5rpi/cqa02303v5rpi.kicad_pcb",
            "config/default/keyboard-layout.json",
            "config/default/vial-layout-overrides.json",
            "config/default/vial.json",
        ):
            _copy_file(ROOT / relative, fixture / relative)

        command = ["python3", "build/generators/mkvial.py"]
        regenerated = subprocess.run(command, cwd=fixture, capture_output=True, text=True)
        assert regenerated.returncode == 0, regenerated.stdout + regenerated.stderr
        for relative in GENERATED_OUTPUTS:
            assert (fixture / relative).read_bytes() == (ROOT / relative).read_bytes(), relative

        (fixture / "kicad/cqa02303v5rpi/keymap.kicad_sch").unlink()
        missing_source = subprocess.run(command, cwd=fixture, capture_output=True, text=True)
        assert missing_source.returncode != 0
        assert "KiCad schematic source not found" in missing_source.stdout + missing_source.stderr


def _layout_labels(vial: dict) -> list[str]:
    return [
        item
        for row in vial["layouts"]["keymap"]
        for item in row
        if isinstance(item, str)
    ]


def main() -> None:
    pcb_analysis = json.loads((ROOT / "build" / "generated" / "pcb_analysis.json").read_text(encoding="utf-8"))
    keyboard_layout = json.loads((ROOT / "config" / "default" / "keyboard-layout.json").read_text(encoding="utf-8"))
    vial_template = json.loads((ROOT / "config" / "default" / "vial.json").read_text(encoding="utf-8"))
    overrides = mkvial._load_overrides(str(ROOT / "config" / "default" / "vial-layout-overrides.json"))
    ledd_config = json.loads((ROOT / "config" / "default" / "ledd.json").read_text(encoding="utf-8"))

    slots = mkvial._parse_kle_slots(keyboard_layout)
    points = mkvial._parse_switch_points(pcb_analysis, overrides.exclude_sources)
    assignment = mkvial._assign_switches_to_slots(slots, points, overrides)
    keymap = mkvial._build_vial_keymap(slots, assignment)
    generated_vial = mkvial._build_vial_json(keymap, points, vial_template)
    report = mkvial._assignment_report(slots, points, assignment, overrides)
    labels = _layout_labels(generated_vial)

    assert generated_vial["uid"] == vial_template["uid"]
    assert generated_vial["vial"] == vial_template["vial"]
    assert generated_vial["customKeycodes"] == vial_template["customKeycodes"]
    assert generated_vial["matrix"] == {"rows": 10, "cols": 10}
    assert len(assignment) == len(slots) == 90
    assert len(labels) == len(set(labels)) == 90
    assert "5,8" in labels
    assert "6,1" not in labels and "7,1" not in labels
    assert any(label.endswith("\ne") for label in labels)
    assert "encoder_pulse" in overrides.exclude_sources
    assert "row:9,order:2" in overrides.virtual_slots
    assert "Unassigned Slots\n- (none)" in report
    assert "Unassigned Switch Points\n- (none)" in report

    raw_leds = led_gen._extract_led_positions(str(ROOT / "kicad" / "cqa02303v5rpi" / "cqa02303v5rpi.kicad_pcb"))
    detected_leds = led_gen._sort_by_led_number(raw_leds)
    merged_leds = led_gen._merge_led_positions_with_existing_keys(ledd_config["leds"], detected_leds)
    led_keys = list(merged_leds)

    assert len(detected_leds) == 81
    assert len(merged_leds) == len(ledd_config["leds"]) == 81
    assert led_keys[:3] == ["7,0", "8,0", "8,1"]
    assert led_keys[-3:] == ["5,7", "5,8", "5,9"]
    assert not any(key.startswith("LED") for key in led_keys)
    assert "4,4" not in led_keys

    _assert_generated_outputs_are_fresh()

    print("ok: KiCad generated artifacts are fresh and fail closed without canonical input")


if __name__ == "__main__":
    main()
