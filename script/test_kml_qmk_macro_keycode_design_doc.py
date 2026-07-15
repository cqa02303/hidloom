#!/usr/bin/env python3
"""Static checks for KML / QMK macro keycode design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "macro" / "kml-qmk-macro-keycode-design.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")

    assert "KC_KML0" in text
    assert "KC_QM0" in text
    assert "`KC_KML0`-`KC_KML10` / `KC_QM0`-`KC_QM10` を追加しません" in text
    assert "`0`-`7` の 8 slot / family" in text
    assert "KML(name)" in text
    assert "QMK_MACRO(name)" in text
    assert "KML と QMK macro syntax を混ぜない" in text
    assert "Vial custom keycode 64 枠" in text
    assert "first slice では keycode を Vial custom space に追加しない" in text
    assert "/mnt/p3/macros/kml/<name>.kml" in text
    assert "/mnt/p3/macros/qmk/<name>.qmk" in text
    assert "`/mnt/p3/kml/`、`config/default/kml/`、`/mnt/p3/qmk_macro/`、`config/default/qmk_macro/` は初期採用しない" in text
    assert "config/default/macros/kml/example.kml" in text
    assert "config/default/macros/qmk/example.qmk" in text
    assert "`SEND_STRING(\"...\")`" in text
    assert "`TAP_CODE(KC_*)`" in text
    assert "QMK C macro の compile / preprocessor / arbitrary C" in text
    assert "Dynamic Macro、Vial advanced macro command は対象外" in text
    assert "`dry_run=true`" in text
    assert "`key_events.sock` へ直接書かない" in text
    assert "`i2cd` 通知は開始 / 正常終了 / validation error / runtime error の summary" in text
    assert "初期 UI は read-only file picker" in text
    assert "`config/default/keycodes.json` / `config/default/vial.json` に `KC_KMLn` / `KC_QMn` 表示名を追加しない" in text
    assert "`KML 0`-`KML 7` / `QMK Macro 0`-`QMK Macro 7`" in text
    assert "parser test" in text
    assert "runner test" in text
    assert "keycode dispatch test" in text
    assert "lookup order test" in text
    assert "settings.vial_macro_buffer" in text
    assert "KC_SHn" in text
    assert "Shell script 実行機能ではない" in text
    assert "output switch / reload / emergency release" in text
    assert "script / system / connectivity action" in text
    print("ok: KML / QMK macro keycode design doc keeps runner boundaries explicit")


if __name__ == "__main__":
    main()
