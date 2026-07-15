#!/usr/bin/env python3
"""Static checks for Unicode / Send String safety design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "input" / "unicode-send-string-safety-design.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")

    assert "U+3042" in text
    assert "SEND_STRING(name)" in text
    assert "TEXT(name)" in text
    assert "UC_MODE(mode)" in text
    assert "mode=none" in text
    assert "text_send.safety.v2" in text
    assert "POST /api/interaction/text-send-safety/plan" in text
    assert "action-level preflight" in text
    assert "text_send.tap_dry_run.v1" in text
    assert "sends_hid_reports=false" in text
    assert "tap_dry_run.supported_modes" in text
    assert "unsupported_modes" in text
    assert "linux_ctrl_shift_u" in text
    assert "windows_ime_hex_f5" in text
    assert "KC_F5" in text
    assert "keyboard tap sequence" in text
    assert "explicit host profile" in text
    assert "settings.unicode.host_profile" in text
    assert "HTTP warning" in text
    assert "Interaction summary" in text
    assert "send_string_runner_not_connected" in text
    assert "TextSendRuntimeState" in text
    assert "TEXT_SEND_CANCEL" in text
    assert "daemon shutdown" in text
    assert "zero_report_sent" in text
    assert "null_report" in text
    assert "release_all()" in text
    assert "deadline_at" in text
    assert "runner_timeout" in text
    assert "text_send.real_send_plan.v1" in text
    assert "text_send.runner_connection.v1" in text
    assert "logicd_keyboard_tap_runner" in text
    assert "active_output_keyboard" in text
    assert "text_send_runtime_state" in text
    assert "zero_report_on_cancel=true" in text
    assert "runner_method_logicd_keyboard_tap_runner" in text
    assert "runner_zero_report_on_cancel" in text
    assert "emit_keyboard_taps_only" in text
    assert "shell_script" in text
    assert "direct_text_in_keymap" in text
    assert "newline_codepoint" in text
    assert "自動 OS 判定はしない" in text
    assert "keymap action に任意の長文を直接入れません" in text
    assert "Vial raw macro buffer" in text
    assert "output switch" in text
    assert "emergency release" in text
    assert "control character" in text
    assert "zero-width" in text
    assert "secret / password" in text
    assert "KML / QMK macro" in text
    assert "Autocorrect" in text
    assert "Windows 11 / Microsoft IME" in text
    assert "tools/matrix_action_runtime.py" in text
    assert "hex -> F5 -> Enter" in text
    assert "あいうえお、。ーがぱぁゃア日本語" in text
    assert "newline は Unicode code point 送信ではなく" in text
    assert "かな漢字変換 engine ではありません" in text
    assert "host IME は composition state" in text
    assert "candidate selection" in text
    assert "fixed phrase や固定 kanji" in text
    print("ok: Unicode / Send String safety design keeps host-mode and runner boundaries explicit")


if __name__ == "__main__":
    main()
