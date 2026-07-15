#!/usr/bin/env python3
"""Static/unit checks for led_direct_frame_metrics_watch.py."""
from __future__ import annotations

from pathlib import Path
import importlib.util
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "demo" / "led_direct_frame_metrics_watch.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("led_direct_frame_metrics_watch", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    source = TOOL.read_text(encoding="utf-8")
    assert "LEDD_DIRECT_FRAME_STATUS" in source
    assert "accepted_frames" in source
    assert "applied_frames" in source
    assert "ignored_frames" in source
    assert "rejected_frames" in source
    assert "bytes_received" in source
    assert "direct_frame_active" in source

    tool = _load_tool()
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "status.json"
        missing = tool._load_status(path)
        assert missing["metrics_source"] == "missing"
        path.write_text(
            '{"direct_frame_active":true,"accepted_frames":20,"applied_frames":18,'
            '"ignored_frames":1,"rejected_frames":1,"bytes_received":2000,'
            '"last_applied_frame_id":7}',
            encoding="utf-8",
        )
        current = tool._load_status(path)
    previous = {"accepted_frames": 10, "applied_frames": 8, "bytes_received": 1000}
    line = tool.format_metrics(current, previous, 2.0)
    assert "active=1" in line
    assert "accepted=20(5.0/s)" in line
    assert "applied=18(5.0/s)" in line
    assert "bytes=2000(500/s)" in line
    assert "ignored=1" in line
    assert "rejected=1" in line
    assert "last=7" in line
    print("ok: LED direct-frame metrics watch tool")


if __name__ == "__main__":
    main()
