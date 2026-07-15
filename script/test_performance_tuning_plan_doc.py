#!/usr/bin/env python3
"""Regression checks for the performance tuning planning docs."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    plan = (ROOT / "docs" / "ops" / "performance-tuning-plan.md").read_text(encoding="utf-8")
    ops_readme = (ROOT / "docs" / "ops" / "README.md").read_text(encoding="utf-8")
    current_path = ROOT / "docs" / "CURRENT_STATUS.md"
    current = current_path.read_text(encoding="utf-8") if current_path.is_file() else None

    for required in [
        "速度・メモリ使用量削減",
        "測定してから最適化",
        "baseline",
        "`ledd`",
        "`logicd`",
        "`httpd`",
        "python3 script/test_validation_suite.py",
        "ps -o pid,comm,rss,pcpu,args",
        "before/after",
        "HID report timing",
        "hidloom-logicd-core",
        "logicd-companion",
    ]:
        assert required in plan, required

    assert "systemctl status logicd " not in plan
    assert "journalctl -u logicd " not in plan

    assert "performance-tuning-plan.md" in ops_readme
    assert "performance tuning plan" in ops_readme
    if current is not None:
        assert "ops/performance-tuning-plan.md" in current
        assert "速度・メモリ使用量" in current

    assert "httpd status runtime query cache" in plan
    assert "httpd RSS watch" in plan
    assert "/tmp/hidloom-perf-httpd-rss-watch-3min.md" in plan
    assert "httpd browser polling watch" in plan
    assert "/tmp/hidloom-perf-httpd-active-layer-polling.md" in plan
    assert "/tmp/hidloom-perf-httpd-matrix-tester-polling.md" in plan
    assert "logicd event benchmark scenario" in plan
    assert "tools/logicd_event_benchmark.py" in plan
    assert "KC_CONNAUTO" in plan
    assert "KC_SH3" in plan
    assert "KC_SH10` は reboot script" in plan
    assert "restore_result=ok" in plan
    assert "/tmp/hidloom-perf-logicd-kc-a.md" in plan
    assert "/tmp/hidloom-perf-logicd-kc-connauto.md" in plan
    assert "/tmp/hidloom-perf-logicd-kc-sh3.md" in plan
    assert "/tmp/hidloom-perf-logicd-post-script-idle.md" in plan
    assert "_BTD_RUNTIME_STATUS_CACHE_TTL" in (ROOT / "daemon" / "http" / "system_api.py").read_text(encoding="utf-8")
    if current is not None:
        assert "実機 2秒/16fps" in current
        assert "10秒/24fps" in current

    print("ok: performance tuning plan docs are current")


if __name__ == "__main__":
    main()
