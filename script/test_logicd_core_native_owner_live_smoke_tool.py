#!/usr/bin/env python3
"""Regression checks for native owner live smoke helper."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import logicd_core_native_owner_live_smoke as smoke  # noqa: E402


def main() -> None:
    assert smoke.packet("P", 0, 10) == b"P0A\x00"
    try:
        smoke.packet("P", 16, 0)
    except ValueError:
        pass
    else:
        raise AssertionError("expected coordinate validation failure")

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config = root / "config" / "default"
        config.mkdir(parents=True)
        (config / "keycodes.json").write_text(
            '{"KC_LSFT":{"hid":225},"KC_A":{"hid":4},"KC_B":{"hid":5},"KC_LANG1":{"hid":144}}',
            encoding="utf-8",
        )
        (config / "keymap.json").write_text(
            '{"layers":[{"0,0":"KC_LSFT","0,1":"KC_A","0,2":"KC_B","0,3":"KC_LANG1"}]}',
            encoding="utf-8",
        )
        sequences = smoke.choose_sequences(root)
    assert [label for label, _entries in sequences] == ["modifier-only", "overlap-basic", "us-sub-lang"]
    assert sequences[1][1] == [("KC_A", 0, 1), ("KC_B", 0, 2)]

    payload = smoke.run_smoke  # keep import surface checked by static test
    assert callable(payload)
    source = (ROOT / "tools" / "logicd_core_native_owner_live_smoke.py").read_text(encoding="utf-8")
    assert "core matrix_tap_errors changed" in source
    assert "cleanup_pressed_state" in source
    assert '{"t":"release_all"}' in source.replace(" ", "")

    print("ok: logicd-core native owner live smoke helper")


if __name__ == "__main__":
    main()
