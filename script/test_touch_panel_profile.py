#!/usr/bin/env python3
"""Regression checks for the touch-panel-only keymap profile."""
from __future__ import annotations

import json
import os
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon" / "http"))

from keymap_actions import is_valid_keymap_action  # noqa: E402

PROFILE_DIRS = [
    ROOT / "config" / "default" / "touch-panel",
    ROOT / "config" / "default" / "touch-panel" / "osoyoo-4.3",
]
TOUCH_PANEL_UID = 4850729948911186022


def _layout_coords(layout: list) -> set[str]:
    coords: set[str] = set()
    for row in layout:
        for item in row:
            if not isinstance(item, str):
                continue
            head = item.splitlines()[0].strip()
            if "," in head:
                coords.add(head)
    return coords


def _assert_no_legend_alignment(layout: list, label: str) -> None:
    """Touch-panel Vial layouts must not carry KLE `a` alignment hints.

    `a` is a legend alignment attribute, not a matrix mapping field. It was
    observed to make the Vial client hide the touch-panel Space bar, so the
    generated runtime Vial layout keeps large keys to geometry + row,col only.
    """
    for row_index, row in enumerate(layout):
        for item_index, item in enumerate(row):
            if not isinstance(item, dict):
                continue
            assert "a" not in item, f"{label}: unexpected `a` at {row_index}:{item_index}"


def main() -> None:
    keycodes = json.loads((ROOT / "config" / "default" / "keycodes.json").read_text(encoding="utf-8"))
    setup = (ROOT / "system" / "install" / "setup_fresh_rpi.sh").read_text(encoding="utf-8")
    touch_panel_service = (
        ROOT / "system" / "systemd" / "hidloom-touch-panel-profile.service"
    ).read_text(encoding="utf-8")
    layout_api = (ROOT / "daemon" / "http" / "layout_api.py").read_text(encoding="utf-8")
    selector = ROOT / "script" / "select_touch_panel_profile.py"
    selector_source = selector.read_text(encoding="utf-8")
    spec = importlib.util.spec_from_file_location("select_touch_panel_profile", selector)
    assert spec is not None and spec.loader is not None
    selector_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(selector_module)

    assert "HTTPD_LAYOUT_JSON" in layout_api
    assert "HTTPD_KEYMAP_JSON" in layout_api
    assert "HTTPD_VIAL_JSON" in layout_api
    assert "runtime_file" in layout_api
    protocol_defs = (ROOT / "daemon" / "viald" / "protocol_defs.py").read_text(encoding="utf-8")
    assert 'runtime_file("vial.json")' in protocol_defs
    assert 'default_config_file("vial.json")' in protocol_defs
    assert "install_touch_panel_profile" in setup
    assert "hidloom-touch-panel-profile.service" in setup
    assert "HIDLOOM_TOUCH_PANEL_PROFILE_DELAY_SEC" in touch_panel_service
    assert 'sleep "${HIDLOOM_TOUCH_PANEL_PROFILE_DELAY_SEC:-0}"' in touch_panel_service
    assert "HIDLOOM_TOUCH_PANEL_COMMAND_PROBES" in selector_source
    assert "waveshare-8.8" in selector_source
    assert "osoyoo-4.3" in selector_source

    original_env = os.environ.get("HIDLOOM_TOUCH_PANEL_COMMAND_PROBES")
    original_run = selector_module.subprocess.run
    try:
        os.environ["HIDLOOM_TOUCH_PANEL_COMMAND_PROBES"] = "0"

        def fail_run(*_args, **_kwargs):
            raise AssertionError("command probes must be opt-in")

        selector_module.subprocess.run = fail_run
        selector_module.display_sizes(Path("/sys"))

        os.environ["HIDLOOM_TOUCH_PANEL_COMMAND_PROBES"] = "1"

        def fake_run(command, **_kwargs):
            output = "HDMI-A-1 800x480 current\n" if command == ["wlr-randr"] else ""
            return subprocess.CompletedProcess(command, 0, output, "")

        selector_module.subprocess.run = fake_run
        assert (800, 480, "wlr-randr:current") in selector_module.display_sizes(Path("/sys"))
    finally:
        selector_module.subprocess.run = original_run
        if original_env is None:
            os.environ.pop("HIDLOOM_TOUCH_PANEL_COMMAND_PROBES", None)
        else:
            os.environ["HIDLOOM_TOUCH_PANEL_COMMAND_PROBES"] = original_env

    profile, reason = selector_module.select_profile(
        "auto",
        [
            (800, 480, "/sys/class/drm/card1-DSI-1/modes"),
            (480, 1920, "/sys/class/drm/card1-DSI-1/modes"),
            (480, 1920, "/sys/class/graphics/fb0/virtual_size"),
            (800, 480, "kmsprint:crtc"),
        ],
    )
    assert profile == "osoyoo-4.3"
    assert reason == "auto:800x480:kmsprint:crtc"
    profile, reason = selector_module.select_profile(
        "auto",
        [
            (800, 480, "/sys/class/drm/card1-DSI-1/modes"),
            (480, 1920, "/sys/class/drm/card1-DSI-1/modes"),
            (480, 1920, "/sys/class/graphics/fb0/virtual_size"),
        ],
    )
    assert profile == "osoyoo-4.3"
    assert reason == "auto:800x480:/sys/class/drm/card1-DSI-1/modes"

    for profile_dir in PROFILE_DIRS:
        keymap = json.loads((profile_dir / "keymap.json").read_text(encoding="utf-8"))
        layout = json.loads((profile_dir / "keyboard-layout.json").read_text(encoding="utf-8"))
        vial = json.loads((profile_dir / "vial.json").read_text(encoding="utf-8"))

        seen: set[str] = set()
        for group, entries in keymap["_layout_def"].items():
            layer_values = [layer[group] for layer in keymap["layers"]]
            for values in layer_values:
                assert len(values) == len(entries), f"{profile_dir}: {group}"
            for row, col, _label in entries:
                assert 0 <= row < 16 and 0 <= col < 16
                coord = f"{row},{col}"
                assert coord not in seen, f"{profile_dir}: {coord}"
                seen.add(coord)

        for layer in keymap["layers"]:
            for values in layer.values():
                for action in values:
                    if action == "" or action == "KC_TRNS" or action.startswith(("MO(", "TG(", "TO(")):
                        continue
                    assert action in keycodes or is_valid_keymap_action(action), f"{profile_dir}: {action}"

        flick_file = profile_dir / "flick.json"
        if profile_dir.name == "osoyoo-4.3":
            flick = json.loads(flick_file.read_text(encoding="utf-8"))
            assert len(flick["layers"]) == 3
            assert len(flick["layers"][0]["pads"]) == 12
            assert keymap["layers"][0]["flick"][3] == "KC_FLICK(0,0)"
            assert keymap["layers"][2]["flick"][19] == "KC_FLICK(2,11)"

        coords = _layout_coords(layout)
        assert {"0,0", "4,3"} <= coords
        assert coords <= seen, f"{profile_dir}: {coords - seen}"
        assert vial["uid"] == TOUCH_PANEL_UID
        assert vial["matrix"] == {"rows": 16, "cols": 16}
        assert _layout_coords(vial["layouts"]["keymap"]) == coords
        assert "CQA02303v5-40 Touch Panel" in vial["name"]
        _assert_no_legend_alignment(vial["layouts"]["keymap"], f"{profile_dir}/vial.json")
        vial_labels = [item for row in vial["layouts"]["keymap"] for item in row if isinstance(item, str)]
        assert any(item.splitlines()[-1] == "Space" for item in vial_labels), f"{profile_dir}: missing Space label"

    with tempfile.TemporaryDirectory() as tmp:
        runtime_dir = Path(tmp) / "runtime"
        env = {**os.environ, "HIDLOOM_TOUCH_PANEL_SIZE": "800x480"}
        subprocess.run(
            [
                "python3",
                str(selector),
                "--repo-root",
                str(ROOT),
                "--runtime-dir",
                str(runtime_dir),
                "--profile",
                "auto",
                "--sys-root",
                str(Path(tmp) / "sys"),
            ],
            check=True,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
        )
        metadata = json.loads((runtime_dir / "touch_panel_profile.json").read_text(encoding="utf-8"))
        assert metadata["profile"] == "osoyoo-4.3"
        assert (runtime_dir / "vial.json").exists()
        assert (runtime_dir / "flick.json").exists()
        runtime_flick = json.loads((runtime_dir / "flick.json").read_text(encoding="utf-8"))
        assert runtime_flick["layers"][0]["pads"][9]["label"] == "”゜小"
        runtime_vial = json.loads((runtime_dir / "vial.json").read_text(encoding="utf-8"))
        assert runtime_vial["name"].endswith("(osoyoo-4.3)")
        _assert_no_legend_alignment(runtime_vial["layouts"]["keymap"], "runtime/osoyoo-4.3/vial.json")

    with tempfile.TemporaryDirectory() as tmp:
        runtime_dir = Path(tmp) / "runtime"
        env = {**os.environ, "HIDLOOM_TOUCH_PANEL_SIZE": "1920x480"}
        subprocess.run(
            [
                "python3",
                str(selector),
                "--repo-root",
                str(ROOT),
                "--runtime-dir",
                str(runtime_dir),
                "--profile",
                "auto",
                "--sys-root",
                str(Path(tmp) / "sys"),
            ],
            check=True,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
        )
        metadata = json.loads((runtime_dir / "touch_panel_profile.json").read_text(encoding="utf-8"))
        assert metadata["profile"] == "waveshare-8.8"
        runtime_vial = json.loads((runtime_dir / "vial.json").read_text(encoding="utf-8"))
        assert runtime_vial["name"].endswith("(waveshare-8.8)")
        _assert_no_legend_alignment(runtime_vial["layouts"]["keymap"], "runtime/waveshare-8.8/vial.json")

    print("ok: touch panel profile is self-consistent")


if __name__ == "__main__":
    main()
