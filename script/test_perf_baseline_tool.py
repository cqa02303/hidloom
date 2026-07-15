#!/usr/bin/env python3
"""Regression checks for the performance baseline helper."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import perf_baseline  # noqa: E402


def main() -> None:
    assert "logicd" in perf_baseline.DEFAULT_UNITS
    assert "ledd" in perf_baseline.DEFAULT_UNITS
    assert "httpd" in perf_baseline.DEFAULT_UNITS
    assert "btd" in perf_baseline.DEFAULT_UNITS

    ps_cmd = perf_baseline.ps_command()
    assert ps_cmd[:3] == ["ps", "-o", "pid,comm,rss,pcpu,args"]
    assert "-C" in ps_cmd
    assert "python3" in ps_cmd
    assert "matrixd" in ps_cmd

    result = perf_baseline.CommandResult(
        title="sample",
        command=["ps", "-o", "pid,comm,rss,pcpu,args"],
        returncode=0,
        stdout="PID COMMAND RSS %CPU COMMAND\n",
        stderr="",
        elapsed_sec=0.01,
    )
    report = perf_baseline.render_report(
        [result],
        ps_samples=1,
        ps_interval=0.0,
        run_validation=False,
    )
    assert "# Performance Baseline" in report
    assert "validation: `skipped`" in report
    assert "### sample" in report
    assert "pid,comm,rss,pcpu,args" in report
    assert "stdout:" in report
    assert "stderr:" in report

    print("ok: performance baseline helper")


if __name__ == "__main__":
    main()
