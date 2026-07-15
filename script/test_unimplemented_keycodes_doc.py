#!/usr/bin/env python3
"""Regression checks for the unsupported keycode boundary."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    doc_path = ROOT / "docs" / "keycode" / "unimplemented-keycodes.md"
    doc = doc_path.read_text(encoding="utf-8")
    keycode_readme = (ROOT / "docs" / "keycode" / "README.md").read_text(
        encoding="utf-8"
    )
    support = (ROOT / "docs" / "keycode" / "qmk-vial-keycode-support.md").read_text(
        encoding="utf-8"
    )

    for required in [
        "# Unsupported and Deferred Keycodes",
        "更新日: 2026-07-15",
        "## 運用ルール",
        "## 非対応・後送り項目",
        "KC_SYSTEM_SLEEP",
        "PDF(layer)",
        "LM(layer, mod)",
        "OSM(mod)",
        "MS_BTN6",
        "BL_TOGG",
        "DM_REC1",
        "UC(c)",
        "QK_BOOT",
        "config/default/keycodes.json",
        "script/test_http_remap_keycode_coverage.py",
    ]:
        assert required in doc, required

    for stale in (
        "private workspace reference",
        "設計TODOへ昇格",
        "runtime-only groundwork 完了",
        "対応済み first slice",
    ):
        assert stale not in doc, stale

    assert "unimplemented-keycodes.md" in keycode_readme
    assert "unimplemented-keycodes.md" in support
    assert "qmk-vial-keycode-support.md" in doc

    for optional_index in (
        ROOT / "docs" / "CURRENT_STATUS.md",
        ROOT / "docs" / "TODO_PRIORITY.md",
        ROOT / "docs" / "WISHLIST.md",
    ):
        if optional_index.is_file():
            assert "keycode/unimplemented-keycodes.md" in optional_index.read_text(
                encoding="utf-8"
            )

    print("ok: unsupported keycode boundary is public and self-contained")


if __name__ == "__main__":
    main()
