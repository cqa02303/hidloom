#!/usr/bin/env python3
"""Regression checks for the keycode expansion plan document."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    doc = (ROOT / "docs" / "keycode" / "expansion-plan.md").read_text(encoding="utf-8")

    for required in [
        "Basic HID command usage first slice",
        "`KC_SYSTEM_REQUEST` の単独 Keyboard Page usage `0x9A`",
        "`KC_LANG6`-`KC_LANG9`",
        "`KC_KP_EQUAL_AS400`",
        "`KC_LOCKING_CAPS_LOCK` / `KC_LOCKING_NUM_LOCK` / `KC_LOCKING_SCROLL_LOCK`",
        "`MS_BTN1`-`MS_BTN5`",
        "`MS_ACL0`-`MS_ACL2`",
        "host OS の SysRq modifier 組み合わせ動作",
        "../hid/mouse-hid-extension-design.md",
    ]:
        assert required in doc, required

    assert "優先度は低め" not in doc
    assert "候補:\n\n- `KC_LANG6`" not in doc
    assert "候補:\n\n- `KC_LOCKING_CAPS`" not in doc

    print("ok: keycode expansion plan reflects current HID completion state")


if __name__ == "__main__":
    main()
