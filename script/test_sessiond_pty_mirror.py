#!/usr/bin/env python3
"""Regression tests for sessiond PTY mirror pure helpers."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from sessiond.pty_mirror import (  # noqa: E402
    ESC,
    RowUpdate,
    diff_rows,
    key_action_to_pty_bytes,
    normalize_screen,
    render_cursor,
    render_initial_frame,
    render_row_updates,
)


def main() -> None:
    assert key_action_to_pty_bytes("KC_A") == b"a"
    assert key_action_to_pty_bytes("KC_A", active_modifiers={"KC_LSFT"}) == b"A"
    assert key_action_to_pty_bytes("KC_A", active_modifiers={"KC_LSHIFT"}) == b"A"
    assert key_action_to_pty_bytes("KC_1", active_modifiers={"KC_LSFT"}) == b"!"
    assert key_action_to_pty_bytes("KC_MINS", active_modifiers={"KC_LSFT"}) == b"_"
    assert key_action_to_pty_bytes("KC_SCLN", active_modifiers={"KC_LSFT"}) == b":"
    assert key_action_to_pty_bytes("KC_LBRACKET") == b"["
    assert key_action_to_pty_bytes("KC_SCOLON") == b";"
    assert key_action_to_pty_bytes("KC_ENTER") == b"\r"
    assert key_action_to_pty_bytes("KC_ENT") == b"\r"
    assert key_action_to_pty_bytes("KC_RETURN") == b"\r"
    assert key_action_to_pty_bytes("KC_SPACE") == b" "
    assert key_action_to_pty_bytes("KC_SPC") == b" "
    assert key_action_to_pty_bytes("KC_BSPC") == b"\x7f"
    assert key_action_to_pty_bytes("KC_BSPACE") == b"\x7f"
    assert key_action_to_pty_bytes("KC_BACKSPACE") == b"\x7f"
    assert key_action_to_pty_bytes("KC_LEFT") == b"\x1b[D"
    assert key_action_to_pty_bytes("KC_RGHT") == b"\x1b[C"
    assert key_action_to_pty_bytes("KC_UP") == b"\x1b[A"
    assert key_action_to_pty_bytes("KC_DOWN") == b"\x1b[B"
    assert key_action_to_pty_bytes("KC_HOME") == b"\x1b[H"
    assert key_action_to_pty_bytes("KC_END") == b"\x1b[F"
    assert key_action_to_pty_bytes("KC_DEL") == b"\x1b[3~"
    assert key_action_to_pty_bytes("KC_DELETE") == b"\x1b[3~"
    assert key_action_to_pty_bytes("C(KC_C)") == b"\x03"
    assert key_action_to_pty_bytes("KC_D", active_modifiers={"KC_LCTL"}) == b"\x04"
    assert key_action_to_pty_bytes("KC_C", active_modifiers={"KC_LCTRL"}) == b"\x03"
    assert key_action_to_pty_bytes("KC_A", is_press=False) == b""
    assert key_action_to_pty_bytes("KC_F1") == b""

    screen = normalize_screen(["abc", "long line"], rows=3, columns=4)
    assert screen == ("abc", "long", "")

    updates = diff_rows(["one", "two"], ["one", "TWO", "three"], rows=3, columns=120)
    assert updates == [RowUpdate(2, "TWO"), RowUpdate(3, "three")]
    assert render_row_updates(updates) == f"{ESC}[2;1HTWO{ESC}[K{ESC}[3;1Hthree{ESC}[K"

    initial = render_initial_frame(["ready", "PTY"], rows=3, columns=120)
    assert initial.startswith(f"{ESC}[2J{ESC}[Hready\r\nPTY")
    assert render_cursor(0, -2) == f"{ESC}[1;1H"

    print("ok: sessiond PTY mirror key mapping and row diff helpers")


if __name__ == "__main__":
    main()
