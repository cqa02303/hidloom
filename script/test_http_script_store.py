#!/usr/bin/env python3
"""Regression test for editable KC_SHn script store behavior."""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon" / "http"))

import script_store  # noqa: E402


def main() -> None:
    default_sh0 = (ROOT / "config" / "default" / "script" / "KC_SH0.sh").read_text(encoding="utf-8")
    default_sh1 = (ROOT / "config" / "default" / "script" / "KC_SH1.sh").read_text(encoding="utf-8")
    default_sh2 = (ROOT / "config" / "default" / "script" / "KC_SH2.sh").read_text(encoding="utf-8")
    default_sh3 = (ROOT / "config" / "default" / "script" / "KC_SH3.sh").read_text(encoding="utf-8")
    default_sh4 = (ROOT / "config" / "default" / "script" / "KC_SH4.sh").read_text(encoding="utf-8")
    default_sh7 = (ROOT / "config" / "default" / "script" / "KC_SH7.sh").read_text(encoding="utf-8")
    default_sh8 = (ROOT / "config" / "default" / "script" / "KC_SH8.sh").read_text(encoding="utf-8")
    default_sh10 = (ROOT / "config" / "default" / "script" / "KC_SH10.sh").read_text(encoding="utf-8")
    readme = (ROOT / "config" / "default" / "script" / "README.md").read_text(encoding="utf-8")
    assert "# @label 未割当" in default_sh0
    assert "systemctl reboot" not in default_sh0
    assert "command -v hidloom-notify" in default_sh1
    assert 'notify alert "LED video を停止します"' in default_sh1
    assert "command -v hidloom-notify" in default_sh2
    assert "bin/hidloom-notify" not in default_sh2
    assert 'notify warning "LED video demo が見つかりません"' in default_sh2
    assert "python3 -" not in default_sh3
    assert "hidloom-notify alert \"Node:" in default_sh3
    assert "SSID: ${SSID}" in default_sh3
    assert "IP: ${IP}" in default_sh3
    assert "hidloom-notify alert" in default_sh4
    assert "/usr/lib/hidloom/tools/sessiond_ctl.py" in default_sh7
    assert "/home/pi/hidloom" not in default_sh7
    assert "# @label matrixd診断" in default_sh8
    assert "tools/matrixd_diagnostics_snapshot.py" in default_sh8
    assert "/usr/lib/hidloom/tools/matrixd_diagnostics_snapshot.py" in default_sh8
    assert "/home/pi/hidloom" not in default_sh8
    assert "--duration \"$DURATION\"" in default_sh8
    assert "/mnt/p3/matrixd-diagnostics" in default_sh8
    assert "package-managed deployment" in readme
    assert "/usr/lib/hidloom" in readme
    assert "/home/pi/hidloom" in readme
    assert "# @label 再起動" in default_sh10
    assert "hidloom-notify warning" in default_sh10
    assert "systemctl reboot" in default_sh10

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        runtime = root / "runtime"
        fallback = root / "fallback"
        config_json = root / "config.json"
        keycodes_json = root / "keycodes.json"
        config_json.write_text(
            json.dumps({"settings": {"script_dir": str(runtime)}}) + "\n",
            encoding="utf-8",
        )
        keycodes_json.write_text(
            json.dumps({"KC_SH0": {}, "KC_SH1": {}, "KC_SH10": {}, "KC_SHUTDOWN": {}}) + "\n",
            encoding="utf-8",
        )
        fallback.mkdir()
        (fallback / "KC_SH0.sh").write_text("#!/bin/sh\n# @label default zero\n", encoding="utf-8")
        (fallback / "KC_SH10.sh").write_text(
            "#!/bin/sh\n"
            "# @label reboot\n"
            "# @danger reboot\n"
            "# @confirm Reboot now?\n"
            "systemctl reboot\n",
            encoding="utf-8",
        )

        old_config = script_store.CONFIG_JSON
        old_keycodes = script_store.KEYCODES_JSON
        old_default = script_store.DEFAULT_SCRIPT_DIR
        old_fallback = script_store.FALLBACK_SCRIPT_DIR
        try:
            script_store.CONFIG_JSON = config_json
            script_store.KEYCODES_JSON = keycodes_json
            script_store.DEFAULT_SCRIPT_DIR = root / "unused-default"
            script_store.FALLBACK_SCRIPT_DIR = fallback

            assert script_store.script_keycodes() == ["KC_SH0", "KC_SH1", "KC_SH10"]
            assert script_store.valid_script_keycode("KC_SH10")
            assert not script_store.valid_script_keycode("KC_SH2")
            assert not script_store.valid_script_keycode("KC_SHUTDOWN")

            entries = {entry["keycode"]: entry for entry in script_store.iter_script_entries()}
            assert entries["KC_SH0"]["source"] == "fallback"
            assert entries["KC_SH0"]["exists"] is True
            assert entries["KC_SH0"]["safety"]["dangerous"] is False
            assert entries["KC_SH1"]["source"] == "missing"
            assert entries["KC_SH1"]["exists"] is False
            assert entries["KC_SH1"]["safety"]["dangerous"] is False
            assert entries["KC_SH10"]["source"] == "fallback"
            assert entries["KC_SH10"]["safety"]["dangerous"] is True
            assert entries["KC_SH10"]["safety"]["dangers"] == ["reboot"]
            assert "reboot" in entries["KC_SH10"]["safety"]["auto_dangers"]
            assert entries["KC_SH10"]["safety"]["confirm_message"] == "Reboot now?"
            template = script_store.default_script_content("KC_SH1")
            assert template.startswith("#!/bin/bash\n# @label (コマンド説明)\n")
            assert 'hidloom-notify alert "message" 2' in template

            path = script_store.write_runtime_script("KC_SH10", "#!/bin/sh\necho added\n")
            assert path == runtime / "KC_SH10.sh"
            assert path.read_text(encoding="utf-8").endswith("echo added\n")
            if os.name != "nt":
                assert path.stat().st_mode & stat.S_IXUSR
            runtime_entry = script_store.script_entry("KC_SH10")
            assert runtime_entry["source"] == "runtime"
            assert runtime_entry["safety"]["dangerous"] is False
            assert script_store.delete_runtime_script("KC_SH10") is True
            assert script_store.delete_runtime_script("KC_SH10") is False
            assert script_store.script_entry("KC_SH10")["source"] == "fallback"
        finally:
            script_store.CONFIG_JSON = old_config
            script_store.KEYCODES_JSON = old_keycodes
            script_store.DEFAULT_SCRIPT_DIR = old_default
            script_store.FALLBACK_SCRIPT_DIR = old_fallback

    print("ok: HTTP script store supports editable KC_SHn range")


if __name__ == "__main__":
    main()
