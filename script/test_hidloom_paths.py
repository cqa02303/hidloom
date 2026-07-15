#!/usr/bin/env python3
"""Regression checks for repository/runtime path helpers."""
from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hidloom_paths


def main() -> None:
    assert hidloom_paths.repo_root() == ROOT
    assert hidloom_paths.default_config_dir() == ROOT / "config" / "default"
    assert hidloom_paths.default_config_file("config.json") == ROOT / "config" / "default" / "config.json"
    assert hidloom_paths.board_profiles_dir() == ROOT / "config" / "boards"
    assert hidloom_paths.runtime_dir() == Path("/mnt/p3")
    assert hidloom_paths.runtime_file("keymap.json") == Path("/mnt/p3/keymap.json")
    assert hidloom_paths.runtime_script_dir() == Path("/mnt/p3/script")

    os.environ["HIDLOOM_DEFAULT_CONFIG_DIR"] = "/tmp/hidloom-default-conf"
    os.environ["HIDLOOM_BOARD_PROFILES_DIR"] = "/tmp/hidloom-boards"
    os.environ["HIDLOOM_RUNTIME_DIR"] = "/tmp/hidloom-runtime"
    os.environ["HIDLOOM_RUNTIME_SCRIPT_DIR"] = "/tmp/hidloom-script"
    try:
        assert hidloom_paths.default_config_dir() == Path("/tmp/hidloom-default-conf")
        assert hidloom_paths.default_config_file("keycodes.json") == Path("/tmp/hidloom-default-conf/keycodes.json")
        assert hidloom_paths.board_profiles_dir() == Path("/tmp/hidloom-boards")
        assert hidloom_paths.runtime_file("keymap.json") == Path("/tmp/hidloom-runtime/keymap.json")
        assert hidloom_paths.runtime_script_dir() == Path("/tmp/hidloom-script")
    finally:
        for name in ("HIDLOOM_DEFAULT_CONFIG_DIR", "HIDLOOM_BOARD_PROFILES_DIR", "HIDLOOM_RUNTIME_DIR", "HIDLOOM_RUNTIME_SCRIPT_DIR"):
            os.environ.pop(name, None)

    print("ok: repository path helpers")


if __name__ == "__main__":
    main()
