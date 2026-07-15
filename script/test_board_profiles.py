#!/usr/bin/env python3
"""Regression checks for board profile versioning."""
from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "script" / "apply_board_profile.py"
PROFILE_FILES = {
    "matrixd.json",
    "keymap.json",
    "keyboard-layout.json",
    "vial.json",
    "ledd.json",
    "i2cd.json",
}


def run_cmd(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def main() -> None:
    board_doc = (ROOT / "docs" / "hardware" / "board-profiles.md").read_text(
        encoding="utf-8"
    )
    new_board_guide = (ROOT / "docs" / "hardware" / "new-board-config-guide.md").read_text(
        encoding="utf-8"
    )
    hardware_readme = (ROOT / "docs" / "hardware" / "README.md").read_text(
        encoding="utf-8"
    )
    setup = (ROOT / "system" / "install" / "setup_fresh_rpi.sh").read_text(encoding="utf-8")

    assert "marker がない実機は `ver1.0` とみなす。" in board_doc
    assert "`ver0.1` は試作基板なので、自動 fallback では選ばない。" in board_doc
    assert "--prototype" in board_doc
    assert "/mnt/p3/board_profile.json" in board_doc
    assert "<keyboard-host>" in board_doc and "ver0.1" in board_doc
    assert "<keyboard-host>" in board_doc and "ver1.0" in board_doc
    assert "--board-version ver0.1 --prototype" in setup
    assert "new-board-config-guide.md" in hardware_readme
    assert "config/boards/<board-version>/" in new_board_guide
    assert "matrixd.json" in new_board_guide and "keyboard-layout.json" in new_board_guide
    assert "実機なしでのレビュー" in new_board_guide
    assert "実機待ち checklist" in new_board_guide

    for version in ("ver0.1", "ver1.0"):
        board_dir = ROOT / "config" / "boards" / version
        manifest = json.loads((board_dir / "board.json").read_text(encoding="utf-8"))
        assert manifest["board_version"] == version
        conf_files = {path.name for path in (board_dir / "conf").iterdir()}
        assert PROFILE_FILES <= conf_files
        keymap = json.loads((board_dir / "conf" / "keymap.json").read_text(encoding="utf-8"))
        assert keymap["layers"][0]["rmod"][2] == "LT(2,KC_LANG1)"
        assert keymap["layers"][2]["fn"][2:] == [
            "KC_F13",
            "KC_F14",
            "KC_F15",
            "KC_F16",
            "KC_F17",
            "KC_F18",
            "KC_F19",
            "KC_F20",
            "KC_F21",
            "KC_F22",
            "KC_F23",
            "KC_F24",
        ]

    assert json.loads((ROOT / "config" / "boards" / "ver0.1" / "board.json").read_text())["prototype"] is True
    assert json.loads((ROOT / "config" / "boards" / "ver1.0" / "board.json").read_text())["default"] is True

    with tempfile.TemporaryDirectory() as tmp:
        marker = Path(tmp) / "board_profile.json"
        status = run_cmd("--status", "--marker-path", str(marker)).stdout
        payload = json.loads(status)
        assert payload["board_version"] == "ver1.0"
        assert payload["source"] == "fallback"

        failed = run_cmd("ver0.1", "--write-marker", "--marker-path", str(marker), check=False)
        assert failed.returncode != 0
        assert "prototype hardware" in failed.stderr or "prototype hardware" in failed.stdout
        assert not marker.exists()

        run_cmd(
            "ver0.1",
            "--prototype",
            "--write-marker",
            "--marker-path",
            str(marker),
            "--device-name",
            "<keyboard-host>",
        )
        data = json.loads(marker.read_text(encoding="utf-8"))
        assert data["board_version"] == "ver0.1"
        assert data["prototype"] is True
        assert data["device_name"] == "<keyboard-host>"

    print("ok: board profiles are explicit and default to ver1.0")


if __name__ == "__main__":
    main()
