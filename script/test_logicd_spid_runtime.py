#!/usr/bin/env python3
"""Regression tests for logicd spid runtime settings."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.spid_runtime import spid_settings_from_config  # noqa: E402


def main() -> None:
    settings = spid_settings_from_config({})
    assert settings.mode == "mouse"
    assert settings.binding is None

    cfg = {
        "settings": {
            "spid": {
                "mode": "direction",
                "direction": {
                    "name": "ball",
                    "up": [2, 0],
                    "down": [2, 1],
                    "left": "2,2",
                    "right": "2,3",
                    "threshold": 12,
                    "max_taps_per_flush": 2,
                    "tap_hold_sec": 0.005,
                    "tap_gap_sec": 0.001,
                },
            }
        }
    }
    settings = spid_settings_from_config(cfg)
    assert settings.mode == "direction"
    assert settings.binding is not None
    assert settings.binding.name == "ball"
    assert settings.binding.up == (2, 0)
    assert settings.binding.down == (2, 1)
    assert settings.binding.left == (2, 2)
    assert settings.binding.right == (2, 3)
    assert settings.binding.threshold == 12
    assert settings.binding.max_taps_per_flush == 2
    assert settings.tap_hold_sec == 0.005
    assert settings.tap_gap_sec == 0.001

    os.environ["LOGICD_SPID_MODE"] = "mouse"
    try:
        settings = spid_settings_from_config(cfg)
        assert settings.mode == "mouse"
        assert settings.binding is None
    finally:
        os.environ.pop("LOGICD_SPID_MODE", None)

    try:
        spid_settings_from_config({"settings": {"spid": {"mode": "bad"}}})
    except ValueError as exc:
        assert "invalid settings.spid.mode" in str(exc)
    else:
        raise AssertionError("invalid mode should fail")

    print("ok: logicd spid runtime settings")


if __name__ == "__main__":
    main()
