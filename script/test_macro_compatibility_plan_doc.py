#!/usr/bin/env python3
"""Regression checks for macro compatibility policy docs."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    plan = (ROOT / "docs" / "macro" / "compatibility-plan.md").read_text(encoding="utf-8")
    overview = (ROOT / "docs" / "architecture" / "system-overview.md").read_text(encoding="utf-8")
    overview_svg = (ROOT / "docs" / "architecture" / "system-overview.svg").read_text(encoding="utf-8")
    spec = (ROOT / "docs" / "architecture" / "specification.md").read_text(encoding="utf-8")
    backlog = (ROOT / "docs" / "feature/design-todo-backlog.md").read_text(encoding="utf-8")
    current_path = ROOT / "docs" / "CURRENT_STATUS.md"
    current = current_path.read_text(encoding="utf-8") if current_path.is_file() else None

    assert "## 現時点の決定" in plan
    assert "`KC_SH0`-`KC_SH10` | 正規の script 実行経路" in plan
    assert "Vial Macro buffer / `M0`-`M7` | 対応済みの互換入口" in plan
    assert "KML | 実装前設計TODOへ昇格" in plan
    assert "QMK macro compatible subset | 実装前設計TODOへ昇格" in plan
    assert "Vial advanced macro 完全互換 | 実装前設計TODOへ昇格" in plan
    assert "`KC_KMLn` / `KC_QMn` は、実装前設計で runner / editor / test 境界を固定してから追加する" in plan
    assert "以下は未実装ですが、実装前設計TODOへ昇格済みの追加案です" in plan
    assert "以下は `KC_KMLn` / `KC_QMn` の実装前設計TODOで固定する配置案です" in plan

    assert "実装済み経路は、`KC_SHn` の shell script 実行" in overview
    assert "KML と QMK macro compatible runner は、`KC_KMLn` / `KC_QMn` の実装前設計TODO" in overview
    assert "KC_KMLn` / `KC_QMn` を解決し" not in overview
    assert "KC_SHn + Vial/local macro dispatch" in overview_svg
    assert "Shell scripts; KML/QMK design TODO" in overview_svg
    assert "KC_KMLn / KC_QMn dispatch" not in overview_svg
    assert "Shell / KML / QMK-compatible macro" not in overview_svg

    assert "KML / QMK macro keycode integration は実装前設計を固定済み" in spec
    assert "first slice では `KC_KMLn` / `KC_QMn` を追加せず" in spec
    assert "`KML(name)` / `QMK_MACRO(name)` の runtime action" in spec

    assert "### KML / QMK macro keycode integration design" in backlog
    assert "first slice は `KML(name)` / `QMK_MACRO(name)` の runtime action 名だけ" in backlog
    assert "macro/compatibility-plan.md" in backlog
    assert "parser test、runner test、keycode dispatch test、配置優先順位 test" in backlog
    if current is not None:
        assert "KML / QMK macro keycode integration は実装前設計を固定済み" in current
        assert "`/mnt/p3/macros/<kind>/` -> `config/default/macros/<kind>/` lookup" in current

    print("ok: macro compatibility policy docs are current")


if __name__ == "__main__":
    main()
