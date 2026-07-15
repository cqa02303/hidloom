#!/usr/bin/env python3
"""Static regression checks for matrixd scan-loop tuning."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    source = (ROOT / "daemon" / "matrixd" / "matrixd.c").read_text(encoding="utf-8")
    service = (ROOT / "system" / "systemd" / "matrixd.service").read_text(encoding="utf-8")
    config = (ROOT / "config" / "default" / "matrixd.json").read_text(encoding="utf-8")
    board_configs = [
        (ROOT / "config" / "boards" / version / "conf" / "matrixd.json").read_text(encoding="utf-8")
        for version in ("ver0.1", "ver1.0")
    ]
    readme = (ROOT / "daemon" / "matrixd" / "README.md").read_text(encoding="utf-8")
    plan = (ROOT / "docs" / "ops" / "performance-tuning-plan.md").read_text(encoding="utf-8")
    matrixd_docs = ROOT / "docs" / "daemon" / "specs" / "matrixd"
    debounce_note = (matrixd_docs / "variable-scan-debounce-note.md").read_text(
        encoding="utf-8"
    )
    stability_plan = (matrixd_docs / "scan-stability-plan.md").read_text(encoding="utf-8")
    priority_ideal = (matrixd_docs / "runtime-priority-ideal.md").read_text(
        encoding="utf-8"
    )

    assert '#include "debounce.h"' in source
    assert "MatrixdDebounceKey key_state" in source
    assert "debounce_mode" in source
    assert 'json_str(buf, "debounce_mode"' in source
    assert "matrixd_debounce_step_count" in source
    assert "matrixd_debounce_step_time" in source
    assert "matrixd_debounce_commit_event(&key_state[r][c], event)" in source
    assert "key_state[r][c].state = (uint8_t)!new_raw" not in source
    assert "monotonic_us" in source
    assert "post_row_settle_us" in source
    assert 'json_int(buf, "post_row_settle_us", 2)' in source
    assert "usleep((useconds_t)cfg->post_row_settle_us)" in source
    assert "MIN_INTERVAL_US" in source
    assert "clamp_min_int(&cfg->interval_us" in source
    assert "clamp_nonnegative_int(&cfg->debounce_ms" in source
    assert "if (interval < MIN_INTERVAL_US)" in source
    assert "reapply_pull_each_scan" in source
    assert 'json_bool(buf, "reapply_pull_each_scan", 0)' in source
    assert "if (cfg->reapply_pull_each_scan)" in source
    assert "gpio_pullupdown(gpio_r, pud);" in source
    assert "idle_interval_us" in source
    assert "deep_idle_interval_us" in source
    assert "scan_sleep_us" in source
    assert "raw_changed || event_sent" in source
    assert "Nice=-20" in service
    assert "CPUSchedulingPolicy=fifo" in service
    assert "CPUSchedulingPriority=99" in service
    assert "IOSchedulingClass=realtime" in service
    assert "LimitRTPRIO=99" in service

    assert "reapply_pull_each_scan" in readme
    assert "idle_interval_us" in readme
    assert "deep_idle_interval_us" in readme
    assert "scan loop" in readme
    assert "CPUSchedulingPriority=99" in readme
    assert "matrixd" in plan
    assert "adaptive idle wait" in plan
    assert "debounce_mode=time" in debounce_note
    assert "stable raw duration" in debounce_note
    assert "debounce_mode" in stability_plan
    assert "post_row_settle_us" in stability_plan
    assert "busy loop" in priority_ideal
    assert '"reapply_pull_each_scan"' not in config
    assert '"idle_interval_us": 2000' in config
    assert '"deep_idle_interval_us": 4000' in config
    assert '"idle_after_ms": 100' in config
    assert '"deep_idle_after_ms": 500' in config
    assert '"debounce_mode": "time"' in config
    assert '"debounce_ms": 5' in config
    assert '"post_row_settle_us": 2' in config
    assert '"debounce_count": 3' not in config
    for board_config in board_configs:
        assert '"debounce_mode": "time"' in board_config
        assert '"debounce_ms": 5' in board_config
        assert '"post_row_settle_us": 2' in board_config
        assert '"debounce_count": 3' not in board_config

    print("ok: matrixd scan-loop tuning is documented")


if __name__ == "__main__":
    main()
