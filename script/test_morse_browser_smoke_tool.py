#!/usr/bin/env python3
"""Static guard for the Morse browser smoke helper."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "morse_browser_smoke.py"


def main() -> None:
    text = TOOL.read_text(encoding="utf-8")
    required = [
        "setActiveTab('interaction')",
        "interaction-morse-name",
        "applyMorseBehaviorBuilder()",
        "copyMorseActionForBuilder()",
        "ui_smoke",
        "MORSE(ui_smoke)",
        "hasDefinition",
        "mapDot",
        "mapDash",
        "mapA",
        "fallback",
        "copyStatus",
        "prefixRows",
        "leafRows",
        "forceRows",
        "cancelRows",
        "Page.captureScreenshot",
        "LOW_MEMORY_DEVICE_LIMIT_MIB",
        "allow_low_memory_device",
        "refusing to start Chromium on a low-memory device",
        "shutil.rmtree(user_data, ignore_errors=True)",
    ]
    missing = [item for item in required if item not in text]
    assert not missing, f"missing browser smoke guard term: {missing}"
    assert "Network.setExtraHTTPHeaders" in text
    assert "Authorization" in text
    assert "document.readyState === 'complete'" in text
    print("ok: Morse browser smoke helper")


if __name__ == "__main__":
    main()
