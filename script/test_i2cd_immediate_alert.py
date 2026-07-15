#!/usr/bin/env python3
"""Regression tests for generic immediate OLED alert messages."""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

sys.modules.setdefault("luma", types.ModuleType("luma"))
sys.modules.setdefault("luma.core", types.ModuleType("luma.core"))
sys.modules["luma.core.interface"] = types.ModuleType("luma.core.interface")
sys.modules["luma.core.interface.serial"] = types.SimpleNamespace(i2c=lambda *args, **kwargs: object())
sys.modules["luma.oled"] = types.ModuleType("luma.oled")
sys.modules["luma.oled.device"] = types.SimpleNamespace(sh1107=lambda *args, **kwargs: object())
sys.modules["luma.core.render"] = types.SimpleNamespace(canvas=lambda *args, **kwargs: object())
sys.modules["luma.core.error"] = types.SimpleNamespace(DeviceNotFoundError=OSError)

from i2cd.i2cd import _alert_is_immediate  # noqa: E402


def main() -> None:
    assert _alert_is_immediate({"t": "alert", "msg": "MORSE practice", "immediate": True})
    assert _alert_is_immediate({"t": "warning", "msg": "HOT", "immediate": 1})
    assert not _alert_is_immediate({"t": "alert", "msg": "BT CONNECTED"})
    assert not _alert_is_immediate({"t": "alert", "msg": "BT CONNECTED", "immediate": False})
    print("ok: i2cd immediate alert flag")


if __name__ == "__main__":
    main()
