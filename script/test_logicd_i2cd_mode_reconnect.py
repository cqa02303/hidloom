#!/usr/bin/env python3
"""Regression test for preserving OLED auto output labels across reconnects."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.runtime_notifications import LogicdNotifier  # noqa: E402
from logicd.state import LogicdRuntime  # noqa: E402


def main() -> None:
    runtime = LogicdRuntime()
    notifier = LogicdNotifier(runtime)

    notifier.push_ledd_mode("gadget")
    notifier.push_i2cd_mode("auto:gadget")

    assert runtime.current_hid_mode == "gadget"
    assert runtime.current_i2cd_mode == "auto:gadget"

    print("ok: i2cd reconnect keeps auto output display mode")


if __name__ == "__main__":
    main()
