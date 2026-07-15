#!/usr/bin/env python3
"""Regression checks for the guarded text-send smoke helper."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "script" / "text_send_smoke_sequence.py"), *args],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_default_unicode_smoke_is_dry_run_only() -> None:
    result = _run()
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema"] == "text_send.smoke_sequence.v1"
    assert payload["dry_run"] is True
    assert payload["real_send_allowed"] is True
    assert payload["broker_kind"] == "us_sub_keyboard"
    assert [tap["action"] for tap in payload["taps"]] == [
        "KC_3",
        "KC_0",
        "KC_4",
        "KC_2",
        "KC_F5",
        "KC_ENTER",
    ]


def test_named_text_smoke_uses_same_sequence() -> None:
    result = _run("--action", "TEXT(kana_a)")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["real_send_allowed"] is True
    assert payload["blocking_reasons"] == []
    assert payload["tap_count"] == 6


def test_real_send_requires_confirmation_phrase() -> None:
    result = _run("--send")
    assert result.returncode != 0
    assert "SEND_TEXT_SMOKE_TO_FOCUSED_HOST" in result.stderr


if __name__ == "__main__":
    test_default_unicode_smoke_is_dry_run_only()
    test_named_text_smoke_uses_same_sequence()
    test_real_send_requires_confirmation_phrase()
