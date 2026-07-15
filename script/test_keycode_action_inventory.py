#!/usr/bin/env python3
"""Freshness checks for generated keycode action inventory docs."""

from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def main() -> None:
    inventory = ROOT / "docs" / "keycode" / "action-inventory.md"
    routing = ROOT / "docs" / "keycode" / "action-routing-matrix.md"
    patterns = ROOT / "docs" / "keycode" / "action-patterns.md"
    generator = ROOT / "tools" / "keycode_action_inventory.py"

    assert inventory.exists(), inventory
    assert routing.exists(), routing
    assert patterns.exists(), patterns
    assert generator.exists(), generator

    check = run(["python3", str(generator), "--check", "--document"])
    assert check.returncode == 0, check.stdout + check.stderr

    text = inventory.read_text(encoding="utf-8")
    routing_text = routing.read_text(encoding="utf-8")
    patterns_text = patterns.read_text(encoding="utf-8")
    for phrase in [
        "| action | canonical | category | hid_page | hid_usage | linux_code | logicd | logicd_core_rs | usb | uinput | bt | special_notes |",
        "| KC_A |",
        "| KC_ENTER |",
        "| KC_ENT | KC_ENTER |",
        "| KC_TRNS |",
        "| KC_VOLU | KC_AUDIO_VOL_UP | consumer | consumer |",
        "| KC_BTN1 |",
        "| KC_CONNAUTO |",
        "| KC_ZKHK |",
        "| KC_SHUTDOWN |",
    ]:
        assert phrase in text, phrase

    for phrase in [
        "手で全件を重複転記",
        "tools/keycode_action_inventory.py",
        "logicd-core-rs 投入時の対応範囲",
    ]:
        assert phrase in routing_text, phrase

    for phrase in [
        "`MO(n)`",
        "`LT(n,kc)`",
        "`MT(mod,kc)`",
        "`TD(name)`",
        "`MORSE(name)`",
        "`MACRO:name`",
        "`TEXT(name)`",
        "`U+XXXX`",
        "logicd-core-rs",
        "preview-only",
    ]:
        assert phrase in patterns_text, phrase

    print("ok: keycode action inventory is fresh")


if __name__ == "__main__":
    main()
