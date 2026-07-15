#!/usr/bin/env python3
"""Regression tests for tools/hid_release_roll_analyzer.py."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "hid_release_roll_analyzer.py"


def load_tool_module():
    spec = importlib.util.spec_from_file_location("hid_release_roll_analyzer", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_log(path: Path) -> None:
    events = [
        {"t": "hidd_keyboard_write", "unix_us": 1_000_000, "endpoint": "hidg2", "report": "0000040000000000"},
        {"t": "hidd_keyboard_release_pending", "unix_us": 1_010_000, "endpoint": "hidg2", "report": "0000000000000000"},
        {"t": "hidd_keyboard_release_flush", "unix_us": 1_026_000, "endpoint": "hidg2", "report": "0000000000000000"},
        {"t": "hidd_keyboard_write", "unix_us": 1_026_000, "endpoint": "hidg2", "report": "0000000000000000"},
        {"t": "hidd_keyboard_write", "unix_us": 1_032_500, "endpoint": "hidg2", "report": "0000050000000000"},
        {"t": "hidd_keyboard_release_merged", "unix_us": 1_040_000, "endpoint": "hidg2", "next_report": "0000060000000000"},
        {"t": "hidd_keyboard_release_preserved", "unix_us": 1_050_000, "endpoint": "hidg2", "next_report": "0000060000000000"},
    ]
    path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")


def test_analyzer_counts_close_zero_to_next_press() -> None:
    module = load_tool_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "hidd.ndjson"
        write_log(log_path)
        payload = module.analyze(log_path, [5.0, 10.0])
    assert payload["events"] == 7
    assert payload["keyboard_writes"] == 3
    assert len(payload["zero_to_next_press"]["5.0"]) == 0
    assert len(payload["zero_to_next_press"]["10.0"]) == 1
    assert payload["zero_to_next_press"]["10.0"][0]["dt_ms"] == 6.5
    assert payload["release_summary"]["hidd_keyboard_release_pending"] == 1
    assert payload["release_summary"]["hidd_keyboard_release_flush"] == 1
    assert payload["release_summary"]["hidd_keyboard_release_merged"] == 1
    assert payload["release_summary"]["hidd_keyboard_release_preserved"] == 1


def test_analyzer_json_cli() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "hidd.ndjson"
        write_log(log_path)
        result = subprocess.run(
            [sys.executable, str(TOOL), str(log_path), "--threshold-ms", "10", "--json"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        )
    payload = json.loads(result.stdout)
    assert payload["schema"] == "hid-release-roll-analysis.v1"
    assert len(payload["zero_to_next_press"]["10.0"]) == 1


def main() -> None:
    test_analyzer_counts_close_zero_to_next_press()
    test_analyzer_json_cli()
    print("ok: hid release roll analyzer")


if __name__ == "__main__":
    main()
