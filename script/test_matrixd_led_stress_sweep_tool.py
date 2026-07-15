#!/usr/bin/env python3
"""Static checks for the matrixd LED stress sweep helper."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import matrixd_led_stress_sweep as stress  # noqa: E402


def main() -> None:
    effects = stress.default_effects()
    labels = {effect.label for effect in effects}
    assert "default-multisplash" in labels
    assert "risky-multisplash" in labels
    assert "dummy-splash-60hz" in labels
    assert any(effect.dummy_rate_hz > 0 for effect in effects)
    assert stress.valid_key_packet(bytes([stress.PRESS, 1, 2, 0]))
    assert not stress.valid_key_packet(b"bad")

    custom = stress.parse_effect("custom:40:64:80:255:160:30")
    assert custom.label == "custom"
    assert custom.mode == 40
    assert custom.dummy_rate_hz == 30.0
    assert stress.parse_position("4,6") == (4, 6)

    key_result = stress.KeyMonitorResult()
    ledd_result = stress.LeddMonitorResult(key_messages=120)
    dummy_result = stress.DummySplashResult(sent_messages=120)
    assert stress.scenario_passed(
        key_result=key_result,
        ledd_result=ledd_result,
        dummy_result=dummy_result,
        allow_events=False,
        allow_monitor_errors=False,
    )
    key_result.packets = 1
    assert not stress.scenario_passed(
        key_result=key_result,
        ledd_result=ledd_result,
        dummy_result=dummy_result,
        allow_events=False,
        allow_monitor_errors=False,
    )

    scenario = stress.ScenarioResult(
        effect=custom,
        started_at=stress.datetime.now(stress.timezone.utc),
        elapsed_sec=1.25,
        apply_response={"result": "ok"},
        effective_led={"result": "ok", "mode": 40, "v": 160},
        key_result=stress.KeyMonitorResult(packets=0),
        ledd_result=stress.LeddMonitorResult(key_messages=60),
        dummy_result=stress.DummySplashResult(sent_messages=60),
        passed=True,
    )
    args = stress.parse_args(["--duration", "1", "--dummy-position", "0,1"])
    report = stress.render_report(
        args=args,
        started_at=stress.datetime.now(stress.timezone.utc),
        original_led={"result": "ok", "mode": 2, "speed": 32, "h": 0, "s": 0, "v": 64},
        restore_response={"result": "ok"},
        scenarios=[scenario],
        command_results=[
            stress.CommandResult("service active state", ["systemctl", "is-active"], 0, "active\n", ""),
        ],
        log_result=stress.CommandResult("recent daemon logs", ["journalctl"], 0, "", ""),
        interesting_logs=[],
        passed=True,
    )
    assert "# matrixd LED Stress Sweep" in report
    assert "custom" in report
    assert "dummy_ledd_key_messages_sent: `60`" in report
    assert "key_event_count: `0`" in report
    assert stress.send_ctrl_led_key_event.__name__ == "send_ctrl_led_key_event"

    readme = (ROOT / "tools" / "README.md").read_text(encoding="utf-8")
    assert "matrixd_led_stress_sweep.py" in readme
    assert "dummy splash" in readme
    print("ok: matrixd LED stress sweep helper")


if __name__ == "__main__":
    main()
