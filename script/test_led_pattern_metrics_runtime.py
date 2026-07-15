#!/usr/bin/env python3
"""Smoke tests for LED pattern editor / long-run metrics groundwork helpers."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from ledd.led_pattern_metrics import (  # noqa: E402
    build_led_pattern_preview_plan,
    summarize_long_run_metrics,
    validate_led_pattern_draft,
)


def main() -> None:
    valid = validate_led_pattern_draft({
        "name": "demo-rainbow",
        "kind": "pattern",
        "pattern": "rainbow",
        "brightness": 96,
        "fps": 24,
        "timeout_sec": 30,
        "hue": 80,
    })
    assert valid["valid"]
    assert valid["schema"] == "led_pattern_editor.draft.v1"
    assert valid["storage_owner"] == "/mnt/p3/led_pattern_editor.json"
    assert not valid["writes_conf_ledd_json"]
    assert valid["draft"].pattern == "rainbow"

    too_bright = validate_led_pattern_draft({
        "kind": "pattern",
        "pattern": "pulse",
        "brightness": 160,
        "fps": 24,
        "timeout_sec": 30,
    })
    assert too_bright["valid"]
    assert "brightness_requires_explicit_confirm" in too_bright["warnings"]

    invalid = validate_led_pattern_draft({
        "name": "",
        "kind": "role_editor",
        "pattern": "unknown",
        "brightness": 999,
        "fps": 0,
        "timeout_sec": 999,
        "speed": 999,
    })
    assert not invalid["valid"]
    assert "invalid_pattern_kind" in invalid["errors"]
    assert "invalid_pattern_name" in invalid["errors"]
    assert "brightness_out_of_range" in invalid["errors"]
    assert "fps_out_of_range" in invalid["errors"]
    assert "timeout_out_of_range" in invalid["errors"]
    assert "speed_out_of_range" in invalid["errors"]

    blocked_preview = build_led_pattern_preview_plan({
        "kind": "pattern",
        "pattern": "pulse",
        "brightness": 160,
        "fps": 20,
        "timeout_sec": 30,
    })
    assert not blocked_preview["preview_allowed"]
    assert "brightness_confirmation_required" in blocked_preview["blocking_reasons"]
    assert blocked_preview["save_current_effect_snapshot"]
    assert blocked_preview["restore_on_timeout"]
    assert blocked_preview["restore_on_disconnect"]
    assert blocked_preview["restore_on_http_error"]
    assert blocked_preview["restore_on_daemon_reload"]
    assert blocked_preview["uses_direct_frame_preview_path"]
    assert not blocked_preview["writes_conf_ledd_json"]

    confirmed_preview = build_led_pattern_preview_plan(
        {
            "kind": "reactive",
            "pattern": "solid",
            "brightness": 160,
            "fps": 20,
            "timeout_sec": 30,
        },
        current_effect={"mode": 31, "h": 80},
        confirmed_brightness=True,
    )
    assert confirmed_preview["preview_allowed"]
    assert confirmed_preview["brightness_ceiling"] == 192
    assert confirmed_preview["uses_vialrgb_preview_path"]
    assert confirmed_preview["current_effect_snapshot"] == {"mode": 31, "h": 80}

    metrics = summarize_long_run_metrics(
        [
            {"accepted_frames": 10, "applied_frames": 10, "rejected_frames": 0, "ignored_frames": 0, "bytes_received": 1000},
            {"accepted_frames": 70, "applied_frames": 64, "rejected_frames": 1, "ignored_frames": 2, "bytes_received": 7000},
        ],
        expected_fps=24,
        duration_sec=3,
    )
    assert metrics["schema"] == "led_long_run.metrics.v1"
    assert metrics["accepted_frames"] == 60
    assert metrics["applied_frames"] == 54
    assert metrics["dropped_frames"] == 6
    assert metrics["rejected_frames"] == 1
    assert metrics["ignored_frames"] == 2
    assert metrics["bytes_received"] == 6000
    assert metrics["accepted_fps"] == 20
    assert metrics["applied_fps"] == 18
    assert "rejected_frames_present" in metrics["warnings"]
    assert "dropped_frames_present" in metrics["warnings"]
    assert "applied_fps_below_expected" in metrics["warnings"]
    assert metrics["requires_real_led_visual_check"]

    print("ok: LED pattern editor / long-run metrics groundwork helpers")


if __name__ == "__main__":
    main()
