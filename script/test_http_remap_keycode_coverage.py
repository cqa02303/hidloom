#!/usr/bin/env python3
"""Regression test for HTTP remap keycode coverage."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon" / "http"))

from layout_api import build_layout_payload  # noqa: E402


async def _no_logicd_layers():
    return None


def _configured_keycodes() -> list[str]:
    raw = json.loads((ROOT / "config" / "default" / "keycodes.json").read_text(encoding="utf-8"))
    return sorted(k for k in raw if isinstance(k, str) and not k.startswith("_"))


def main() -> None:
    payload = asyncio.run(build_layout_payload(_no_logicd_layers))
    assert payload["keycodes"] == _configured_keycodes()
    assert payload["default_layer0"]
    assert payload["default_layers"]
    assert payload["default_layers"][0] == payload["default_layer0"]

    remap_js = (ROOT / "daemon" / "http" / "static" / "remap_panel.js").read_text(encoding="utf-8")
    keyboard_js = (ROOT / "daemon" / "http" / "static" / "keyboard.js").read_text(encoding="utf-8")
    keyboard_css = (ROOT / "daemon" / "http" / "static" / "keyboard.css").read_text(encoding="utf-8")

    assert "let _availableKeycodes = [];" in remap_js
    assert "let _defaultLayers = [];" in remap_js
    assert "function setAvailableRemapKeycodes(keycodes)" in remap_js
    assert "function _systemDefaultKeycodeForRemapTarget()" in remap_js
    assert "function _decorateSystemDefaultRemapKey(keyEl, kc)" in remap_js
    assert 'keyEl.classList.add("system-default")' in remap_js
    assert 'keyEl.dataset.systemDefault = "1"' in remap_js
    assert "system default 初期配置 デフォルト" in remap_js
    assert 'label: "内部キーコード（未分類・別名）"' in remap_js
    assert 'const keys = _availableKeycodes.filter(kc => !explicit.has(kc));' in remap_js
    assert "return internalGroup ? [...groups, internalGroup] : groups;" in remap_js
    assert "_defaultLayers = Array.isArray(data.default_layers) ? data.default_layers : [];" in keyboard_js
    assert "setAvailableRemapKeycodes(data.keycodes || []);" in keyboard_js
    assert ".remap-key.system-default" in keyboard_css
    assert ".remap-key.system-default.current" in keyboard_css

    print("ok: HTTP remap exposes all configured internal keycodes")


if __name__ == "__main__":
    main()
