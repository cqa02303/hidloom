#!/usr/bin/env python3
"""Static checks for LED role preset sharing design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "lighting" / "led-role-preset-sharing-design.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")
    required_phrases = [
        "semantic_roles",
        "vialrgb_effect",
        "schema",
        "category",
        "manual override を上書きする場合は confirmation 必須",
        "import preview が settings を変更しない",
        "external URL import は初期対象外",
        "combined preset",
    ]
    for phrase in required_phrases:
        assert phrase in text, phrase
    assert '"schema": "hidloom.led_role_preset.v1"' in text
    retired_owner = "c" + "qa" + "02303"
    assert f'"schema": "{retired_owner}.' not in text
    print("ok: LED role preset sharing design keeps categories/import/apply boundaries explicit")


if __name__ == "__main__":
    main()
