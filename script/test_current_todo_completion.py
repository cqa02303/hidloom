#!/usr/bin/env python3
"""Regression checks that revived TODO items are visible after the archive audit."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    if not (ROOT / "docs" / "CURRENT_STATUS.md").is_file():
        print("ok: private TODO documentation is not shipped in the public source tree")
        return

    todo = (ROOT / "docs" / "TODO_PRIORITY.md").read_text(encoding="utf-8")
    status = (ROOT / "docs" / "CURRENT_STATUS.md").read_text(encoding="utf-8")
    checklist = (ROOT / "docs" / "ops" / "real-device-test-checklist.md").read_text(encoding="utf-8")
    design_todo = (ROOT / "docs" / "feature" / "design-todo-backlog.md").read_text(encoding="utf-8")
    sequence_design = (ROOT / "docs" / "feature" / "sequence-engine-design.md").read_text(encoding="utf-8")
    keycode_todo = (ROOT / "docs" / "keycode" / "unimplemented-keycodes.md").read_text(encoding="utf-8")

    assert "## 現在の未完了TODO" in todo
    assert "古い archive / progress / design backlog を再確認" in todo
    active_todo_section = todo.split("## 現在の未完了TODO", 1)[1].split("## 実機なしで進められる候補", 1)[0]
    assert "現在、実装または設計判断としてこの表へ残す未完了 TODO はありません。" in active_todo_section
    assert "package / device profile split M1-M3" not in active_todo_section
    completed_section = todo.split("## 最近完了した作業", 1)[1]
    assert "package / device profile split M1-M4 first target" in completed_section
    assert "hidloom-profile-touch-waveshare-8.8" in completed_section
    assert "native owner の `KC_CONSOLE` / `KC_USB` / `KC_CONNAUTO` 復旧" in completed_section
    assert "architecture/native-output-routing-uidd-design.md" in todo
    assert "| P1 |" not in active_todo_section
    assert "| P2 |" not in active_todo_section
    assert "## 直近の要点" in status
    assert "## 2026-06-09 自動で完了した作業" in todo
    assert "Bluetooth host local rename metadata first slice" in todo
    assert "## 進行中の判断" in status

    for revived_todo in [
        "Unicode / Send String real runner",
        "Bluetooth paired-host event source / last-connected writer",
        "OLED freeze recovery / I2C diagnostics",
        "Persistent Wi-Fi off implementation decision",
        "Bluetooth host rename / per-host forget runtime",
        "HTTP analog stick calibration 2D map",
    ]:
        assert revived_todo in todo
    for status_summary in [
        "Unicode / Send String",
        "Bluetooth host metadata",
        "OLED / analog stick",
    ]:
        assert status_summary in status

    for completed_gate in [
        "matrixd / splash brightness guard",
        "4.3 inch touch panel flick",
        "Touch flick IME composition",
        "BT paired host recovery boundary",
        "Unicode / Send String safety",
        "Interaction status / feedback owner",
        "Vial serial suffix smoke",
        "SequenceEngine timed interaction safety boundary",
        "Autocorrect runtime first slice",
    ]:
        assert completed_gate in todo

    assert "| P3 |" not in todo
    assert "package-profile-split-plan.md" in status
    assert "feature/design-todo-backlog.md" in todo
    assert "keycode/unimplemented-keycodes.md" in todo
    assert "- [ ]" not in todo
    assert "- [ ]" not in design_todo
    assert "- [ ]" not in sequence_design
    assert "現在、未完了の受け入れchecklistはありません。" in design_todo
    assert "公開実装へ追加しない境界" in design_todo
    assert "private workspace reference" not in design_todo
    for low_priority_keycode in [
        "Mouse buttons 6-8",
        "QMK Unicode",
    ]:
        assert low_priority_keycode in keycode_todo

    forbidden_todo_markers = [
        "| 1 | matrixd / splash brightness guard の物理確認 |",
        "| P1 | matrixd / LED brightness 実機安定化 |",
        "| P1 | package / device profile split M1-M3 |",
        "| 3 | Vial serial suffix |",
    ]
    for marker in forbidden_todo_markers:
        assert marker not in todo

    assert "外部 host / 肉眼観測が必要な追加検証" in checklist

    print("ok: current TODO and public design boundaries are explicit")


if __name__ == "__main__":
    main()
