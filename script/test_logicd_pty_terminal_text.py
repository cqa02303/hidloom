#!/usr/bin/env python3
"""Regression tests for PTY terminal mirror text plans."""
from __future__ import annotations

import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.pty_terminal_text import (  # noqa: E402
    DEFAULT_PTY_TERMINAL_HOST_PROFILE,
    PTY_TERMINAL_RECEIVER_COMMAND,
    PTY_TERMINAL_SOURCE,
    WINDOWS_TEXT_EDITOR_PROFILE,
    WINDOWS_TERMINAL_WSL_CAT_PROFILE,
    build_pty_terminal_receiver_plan,
    build_pty_terminal_receiver_stop_plan,
    build_pty_terminal_startup_plan,
    build_pty_terminal_text_plan,
    build_pty_terminal_text_plans,
    pty_terminal_profile_uses_receiver,
    strip_text_editor_terminal_sequences,
    strip_unsupported_terminal_sequences,
    terminal_text_tap_sequence,
    text_editor_tap_sequence,
    us_ascii_tap_sequence,
    wsl_cat_base64_command,
)


def main() -> None:
    text = "\x1b[2J\x1b[HPTY TEST"
    command = wsl_cat_base64_command(text)
    assert command.startswith("wsl bash -lc ")
    assert "base64 -d" in command
    encoded = command.split("printf %s '", 1)[1].split("'", 1)[0]
    assert base64.b64decode(encoded).decode("utf-8") == text

    taps, blocking = us_ascii_tap_sequence("AZaz09[];'", append_enter=True)
    assert blocking == []
    assert taps[0]["key"] == "KC_A"
    assert taps[0]["modifiers"] == ["KC_LSHIFT"]
    assert taps[2]["key"] == "KC_A"
    assert taps[-1]["key"] == "KC_ENTER"

    assert DEFAULT_PTY_TERMINAL_HOST_PROFILE == WINDOWS_TEXT_EDITOR_PROFILE
    assert pty_terminal_profile_uses_receiver(WINDOWS_TEXT_EDITOR_PROFILE) is False
    assert pty_terminal_profile_uses_receiver(WINDOWS_TERMINAL_WSL_CAT_PROFILE) is True

    receiver = build_pty_terminal_receiver_plan()
    assert receiver["available"] is False
    assert receiver["receiver"] is False
    assert receiver["wrapper"] == "text_editor_direct_input_no_receiver"
    assert receiver["blocking_reasons"] == ["pty_receiver_not_required"]

    receiver = build_pty_terminal_receiver_plan(host_profile=WINDOWS_TERMINAL_WSL_CAT_PROFILE)
    assert receiver["available"] is True
    assert receiver["receiver"] is True
    assert receiver["wrapper"] == "wsl_cat_echo_off_receiver"
    assert receiver["command"] == PTY_TERMINAL_RECEIVER_COMMAND
    assert "stty -echo -icanon min 1 time 0" in receiver["command"]
    assert receiver["command"].endswith("; stty sane")
    assert receiver["taps"][-1]["key"] == "KC_ENTER"
    assert receiver["tap_hold_sec"] == 0.006
    assert receiver["tap_gap_sec"] == 0.020
    assert receiver["post_gap_sec"] >= 0.2

    receiver_stop = build_pty_terminal_receiver_stop_plan()
    assert receiver_stop["available"] is False
    assert receiver_stop["receiver"] is False
    assert receiver_stop["wrapper"] == "text_editor_direct_input_no_receiver_stop"
    assert receiver_stop["blocking_reasons"] == ["pty_receiver_not_required"]

    startup = build_pty_terminal_startup_plan()
    assert startup["available"] is True
    assert startup["wrapper"] == "text_editor_startup_ime_off"
    assert startup["ime_off"] is True
    assert startup["taps"] == [
        {
            "type": "tap",
            "key": "KC_LANG2",
            "modifiers": [],
            "char": "",
            "purpose": "ime_off",
            "post_gap_sec": 0.050,
        }
    ]

    startup_cat = build_pty_terminal_startup_plan(host_profile=WINDOWS_TERMINAL_WSL_CAT_PROFILE)
    assert startup_cat["available"] is False
    assert startup_cat["blocking_reasons"] == ["startup_ime_off_not_required"]

    receiver_stop = build_pty_terminal_receiver_stop_plan(host_profile=WINDOWS_TERMINAL_WSL_CAT_PROFILE)
    assert receiver_stop["available"] is True
    assert receiver_stop["receiver"] is True
    assert receiver_stop["receiver_stop"] is True
    assert receiver_stop["wrapper"] == "wsl_cat_echo_off_receiver_stop"
    assert receiver_stop["command"] == "stty sane"
    assert receiver_stop["taps"][0] == {
        "type": "tap",
        "key": "KC_C",
        "modifiers": ["KC_LCTRL"],
        "char": "\x03",
        "post_gap_sec": 0.350,
    }
    assert receiver_stop["taps"][1] == {
        "type": "tap",
        "key": "KC_C",
        "modifiers": ["KC_LCTRL"],
        "char": "\x03",
        "post_gap_sec": 0.350,
    }
    assert receiver_stop["taps"][2] == {
        "type": "tap",
        "key": "KC_ENTER",
        "modifiers": [],
        "char": "\r",
        "post_gap_sec": 0.350,
    }
    assert receiver_stop["taps"][-1]["key"] == "KC_ENTER"

    direct_taps, direct_blocking = terminal_text_tap_sequence("\x1b[31mRED\x1b[0m\r\n")
    assert direct_blocking == []
    assert direct_taps[0]["key"] == "KC_ESC"
    assert direct_taps[1]["key"] == "KC_LBRACKET"
    assert direct_taps[-1]["key"] == "KC_ENTER"
    assert direct_taps[-1]["char"] == "\r\n"
    assert [tap["key"] for tap in terminal_text_tap_sequence("a\r\nb")[0]] == ["KC_A", "KC_ENTER", "KC_B"]
    backspace_taps, backspace_blocking = terminal_text_tap_sequence("\x08 \x08")
    assert backspace_blocking == []
    assert backspace_taps == [
        {"type": "tap", "key": "KC_H", "modifiers": ["KC_LCTRL"], "char": "\\x08"},
        {"type": "tap", "key": "KC_SPACE", "modifiers": [], "char": " "},
        {"type": "tap", "key": "KC_H", "modifiers": ["KC_LCTRL"], "char": "\\x08"},
    ]
    space_taps, space_blocking = terminal_text_tap_sequence("A      B")
    assert space_blocking == []
    assert [tap["char"] for tap in space_taps] == ["A", "\\x1b", "[", "6", "C", "B"]
    editor_space_taps, editor_space_blocking = text_editor_tap_sequence("A      B")
    assert editor_space_blocking == []
    assert [tap["char"] for tap in editor_space_taps] == ["A", " ", " ", " ", " ", " ", " ", "B"]
    editor_backspace_taps, editor_backspace_blocking = text_editor_tap_sequence("\x08")
    assert editor_backspace_blocking == []
    assert editor_backspace_taps == [{"type": "tap", "key": "KC_BACKSPACE", "modifiers": [], "char": "\\x08"}]

    stripped, strip_reasons = strip_unsupported_terminal_sequences("\x1b]0;title\x07ok")
    assert stripped == "ok"
    assert strip_reasons == ["osc_sequence_stripped"]
    editor_stripped, editor_strip_reasons = strip_text_editor_terminal_sequences("\x1b]0;title\x07\x1b[2J\x1b[Hok")
    assert editor_stripped == "ok"
    assert editor_strip_reasons == ["osc_sequence_stripped", "csi_sequence_stripped"]
    osc_plan = build_pty_terminal_text_plan("\x1b]0;title\x07bash: nope: command not found\r\n")
    assert osc_plan["available"] is True
    assert osc_plan["blocking_reasons"] == []
    assert osc_plan["stripped_reasons"] == ["osc_sequence_stripped"]
    assert any(tap.get("char") == "b" for tap in osc_plan["taps"])

    plan = build_pty_terminal_text_plan(text)
    assert plan["schema"] == "pty_terminal.text_plan.v1"
    assert plan["available"] is True
    assert plan["source"] == PTY_TERMINAL_SOURCE
    assert plan["host_profile"] == WINDOWS_TEXT_EDITOR_PROFILE
    assert plan["route"] == "us_sub_keyboard"
    assert plan["wrapper"] == "text_editor_direct_input"
    assert plan["receiver"] is False
    assert plan["loop_guard"]["macro_recording_allowed"] is False
    assert plan["stripped_reasons"] == ["csi_sequence_stripped"]
    assert plan["taps"][0]["key"] == "KC_P"
    assert plan["tap_hold_sec"] == 0.002
    assert plan["tap_gap_sec"] == 0.002
    assert "command" not in plan
    assert plan["truncated"] is False

    cat_plan = build_pty_terminal_text_plan(text, host_profile=WINDOWS_TERMINAL_WSL_CAT_PROFILE)
    assert cat_plan["available"] is True
    assert cat_plan["host_profile"] == WINDOWS_TERMINAL_WSL_CAT_PROFILE
    assert cat_plan["wrapper"] == "direct_hid_ansi"
    assert cat_plan["taps"][0]["key"] == "KC_ESC"
    assert cat_plan["stripped_reasons"] == []

    long_text = "x" * 90 + "\r\noperator@host:~$ "
    long_plans = build_pty_terminal_text_plans(long_text, max_text_chars=80)
    assert len(long_plans) == 2
    assert all(plan["available"] is True for plan in long_plans)
    assert all(plan["truncated"] is False for plan in long_plans)
    assert [plan["chunk_index"] for plan in long_plans] == [0, 1]
    assert all(plan["chunk_count"] == 2 for plan in long_plans)
    assert all(plan["tap_hold_sec"] == 0.002 for plan in long_plans)
    assert all(plan["tap_gap_sec"] == 0.002 for plan in long_plans)
    assert all(plan["post_gap_sec"] == 0.002 for plan in long_plans)
    rebuilt = "".join(
        str(tap.get("char", ""))
        for plan in long_plans
        for tap in plan["taps"]
        if tap.get("char") != "\r\n"
    )
    assert "x" * 80 in rebuilt
    assert "operator@host:~$ " in rebuilt
    crlf_boundary_plans = build_pty_terminal_text_plans("a" * 63 + "\r\n" + "b" * 10, max_text_chars=64)
    assert len(crlf_boundary_plans) == 2
    assert crlf_boundary_plans[0]["text_length"] == 65
    assert crlf_boundary_plans[0]["taps"][-1]["char"] == "\r\n"

    bad_source = build_pty_terminal_text_plan("x", source="matrix")
    assert bad_source["available"] is False
    assert "invalid_pty_terminal_source" in bad_source["blocking_reasons"]

    print("ok: logicd PTY terminal text plan defaults to text editor output with cat compatibility")


if __name__ == "__main__":
    main()
