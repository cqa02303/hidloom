#!/usr/bin/env python3
"""Regression checks for logicd-core active-owner smoke helper."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import logicd_core_active_owner_smoke as smoke  # noqa: E402


def main() -> None:
    keymap = {
        "_layout_def": {
            "main": [[0, 0, "SW00"], [0, 1, "SW01"]],
            "_meta": [],
        },
        "layers": [
            {"_name": "base", "main": ["KC_LSFT", "KC_A"]},
        ],
    }
    assert smoke.flatten_keymap(keymap) == [{"0,0": "KC_LSFT", "0,1": "KC_A"}]
    assert smoke.packet("P", 0, 10) == b"P0A\x00"
    assert smoke.packet("R", 15, 0) == b"RF0\x00"

    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        config = repo / "config" / "default"
        config.mkdir(parents=True)
        (config / "keymap.json").write_text(json.dumps(keymap), encoding="utf-8")
        (config / "keycodes.json").write_text(
            json.dumps({"KC_LSFT": 225, "KC_A": 4}),
            encoding="utf-8",
        )
        assert smoke.choose_smoke_key(repo, prefer_runtime=False) == (0, 0, "KC_LSFT")

    source = (ROOT / "tools" / "logicd_core_active_owner_smoke.py").read_text(encoding="utf-8")
    assert "--apply" in source
    assert "LOGICD_CORE_OUTPUT_ENABLED=1" in source
    assert "LOGICD_CORE_MATRIX_SOCKET_MODE=0o666" in source
    assert "Before=\n\n[Service]" in source
    assert "Requires=\\nRequires=hidloom-logicd-core.service" not in source
    assert '"mask", "--runtime", LOGICD_UNIT' in source
    assert '"unmask", LOGICD_UNIT' in source
    assert "LOGICD_RUNTIME_MASK = RUN_SYSTEMD / LOGICD_UNIT" in source
    assert 'str(LOGICD_RUNTIME_MASK)' in source
    assert "logicd_core_owner_recovery" in source
    assert "remove_runtime_dropins" in source
    assert "and MATRIX_SOCKET.exists()" in source
    assert "and os.access(MATRIX_SOCKET, os.W_OK)" in source
    assert "time.sleep(max(hold_sec, 0.05))" in source
    assert source.index("unmask_logicd(sudo=sudo") < source.index("recovery.run_recovery(apply=True")
    assert source.index("remove_runtime_dropins(sudo=sudo") < source.index("recovery.run_recovery(apply=True")
    assert '"systemctl", "start", MATRIXD_UNIT' not in source

    readme = (ROOT / "tools" / "README.md").read_text(encoding="utf-8")
    assert "logicd_core_active_owner_smoke.py" in readme
    assert "sudo python3 tools/logicd_core_active_owner_smoke.py --apply --json" in readme
    assert "matrixd.service` は起動せず" in readme

    print("ok: logicd-core active-owner smoke helper")


if __name__ == "__main__":
    main()
