#!/usr/bin/env python3
"""Regression tests for i2cd ADS1115 analog-stick normalization."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from i2cd.ads1115 import build_ctrl_event, normalize_stick, parse_analog_stick_config, read_stick_volts  # noqa: E402
from tools.calibrate_ads1115_stick import (  # noqa: E402
    apply_calibration,
    apply_phase_calibration,
    build_calibration,
    build_center_calibration,
    build_range_calibration,
    validate_saved_calibration,
)


class FakeReader:
    def __init__(self) -> None:
        self.channels: list[int] = []

    def read_single_ended(self, channel: int) -> float:
        self.channels.append(channel)
        return {1: 1.23, 0: 2.34}[channel]


def main() -> None:
    cfg = json.loads((ROOT / "config" / "default" / "i2cd.json").read_text())
    stick = parse_analog_stick_config(cfg)
    assert stick is not None
    assert stick.address == 0x48
    assert stick.bus == 1
    assert stick.x_axis.channel == 0
    assert stick.x_axis.invert is True
    assert stick.y_axis.channel == 1
    assert stick.y_axis.invert is True
    assert stick.poll_interval == 0.02
    assert stick.idle_poll_interval == 0.08
    assert stick.idle_after_sec == 0.5
    assert stick.auto_center_on_start is True
    assert stick.auto_center_duration == 2.0

    assert stick.deadzone == 20
    assert normalize_stick(1.6949, 1.6079, stick) == (0, 0)
    assert normalize_stick(1.2972, 1.6079, stick)[0] > 0
    assert normalize_stick(2.1202, 1.6079, stick)[0] < 0
    assert normalize_stick(1.6949, 2.5037, stick)[1] < 0
    assert normalize_stick(1.6949, 0.9987, stick)[1] > 0

    event = json.loads(build_ctrl_event(0, 12, -34).decode())
    assert event == {"t": "A", "stick": 0, "x": 12, "y": -34}

    reader = FakeReader()
    assert read_stick_volts(reader, stick) == (2.34, 1.23)
    assert reader.channels == [0, 1]

    stats = build_calibration(
        center_samples=[(1.50, 1.60), (1.52, 1.58), (1.51, 1.59)],
        sweep_samples=[(0.30, 1.10), (2.70, 2.80), (1.60, 0.40)],
        margin=0.0,
    )
    assert stats.x.center == 1.51
    assert stats.x.low == 0.3
    assert stats.x.high == 2.7
    assert stats.y.center == 1.59
    assert stats.y.low == 0.4
    assert stats.y.high == 2.8

    updated = apply_calibration(json.loads(json.dumps(cfg)), stats)
    assert updated["analog_stick"]["x"]["center"] == 1.51
    assert updated["analog_stick"]["x"]["low"] == 0.3
    assert updated["analog_stick"]["x"]["high"] == 2.7
    assert updated["analog_stick"]["y"]["center"] == 1.59
    assert updated["analog_stick"]["y"]["low"] == 0.4
    assert updated["analog_stick"]["y"]["high"] == 2.8

    centered = build_center_calibration([(1.0, 1.4), (1.2, 1.6), (1.1, 1.5)])
    assert centered.x == {"center": 1.1}
    assert centered.y == {"center": 1.5}
    center_cfg = apply_phase_calibration(json.loads(json.dumps(cfg)), centered)
    assert center_cfg["analog_stick"]["x"]["center"] == 1.1
    assert center_cfg["analog_stick"]["x"]["low"] == cfg["analog_stick"]["x"]["low"]

    ranged = build_range_calibration([(0.2, 0.3), (2.8, 2.9)], margin=0.0)
    assert ranged.x == {"low": 0.2, "high": 2.8}
    range_cfg = apply_phase_calibration(json.loads(json.dumps(cfg)), ranged)
    assert range_cfg["analog_stick"]["x"]["center"] == cfg["analog_stick"]["x"]["center"]
    assert range_cfg["analog_stick"]["x"]["low"] == 0.2
    assert range_cfg["analog_stick"]["x"]["high"] == 2.8

    validation = validate_saved_calibration(range_cfg)
    assert validation["valid"] is True
    assert validation["x"]["center_valid"] is True
    assert validation["x"]["span_valid"] is True
    assert validation["x"]["span"] == 2.6

    bad_center_cfg = json.loads(json.dumps(range_cfg))
    bad_center_cfg["analog_stick"]["x"]["center"] = 3.0
    bad_center = validate_saved_calibration(bad_center_cfg)
    assert bad_center["valid"] is False
    assert bad_center["x"]["center_valid"] is False
    assert "x.center must be between low and high" in bad_center["errors"]

    small_span_cfg = json.loads(json.dumps(range_cfg))
    small_span_cfg["analog_stick"]["y"]["low"] = 1.5
    small_span_cfg["analog_stick"]["y"]["high"] = 1.55
    small_span = validate_saved_calibration(small_span_cfg, min_range_volts=0.1)
    assert small_span["valid"] is False
    assert small_span["y"]["span_valid"] is False

    print("ok: i2cd ADS1115 analog stick calibration")


if __name__ == "__main__":
    main()
