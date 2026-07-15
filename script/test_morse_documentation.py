#!/usr/bin/env python3
"""Guard tests for MORSE behavior documentation consistency."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def read(path: str) -> str:
    return (DOCS / path).read_text(encoding="utf-8")


def test_current_reference_contains_canonical_terms() -> None:
    text = read("morse/behavior-current.md")
    required = [
        "MORSE(name)",
        "fallback_action",
        "force_commit",
        "terminal_sequences",
        "MorseFeedbackEvent",
        "MORSE_FEEDBACK",
        "/api/interaction/morse-feedback",
        "drain_morse_feedback()",
        "script/test_morse_behavior.py",
        "script/test_morse_interaction_config.py",
        "script/test_interaction_engine_morse.py",
        "script/test_morse_inspector.py",
        "script/test_morse_feedback.py",
        "script/test_morse_feedback_api.py",
        "script/test_morse_ctrl_feedback.py",
        "script/test_morse_oled_alert.py",
        "script/test_morse_led_feedback.py",
        "script/test_morse_browser_smoke_tool.py",
        "script/test_morse_browser_dom.py",
        "tools/morse_browser_smoke.py",
    ]
    missing = [item for item in required if item not in text]
    assert not missing, f"missing from morse/behavior-current.md: {missing}"


def test_morse_readme_links_current_reference() -> None:
    text = read("morse/README.md")
    assert "behavior-current.md" in text
    assert "archive/progress" not in text


def test_route_status_contains_feedback_and_browser_smoke() -> None:
    text = read("morse/http-route-status.md")
    assert "daemon/http/morse_feedback_api.py" in text
    assert "register_morse_feedback_route(app, _send_ctrl_command)" in text
    assert "script/test_morse_feedback_api.py" in text
    assert "script/test_morse_browser_smoke_tool.py" in text
    assert "tools/morse_browser_smoke.py" in text


def test_ctrl_feedback_wiring_is_present() -> None:
    ctrl_py = (ROOT / "daemon" / "logicd" / "ctrl.py").read_text(encoding="utf-8")
    logicd_py = (ROOT / "daemon" / "logicd" / "logicd.py").read_text(encoding="utf-8")
    httpd_py = (ROOT / "daemon" / "http" / "httpd.py").read_text(encoding="utf-8")
    assert "MORSE_FEEDBACK" in ctrl_py
    assert "process_morse_feedback_json" in ctrl_py
    assert "drain_morse_feedback" in ctrl_py
    assert "runtime = _require_runtime()" in logicd_py
    assert "drain_morse_feedback=runtime.interactions.drain_morse_feedback" in logicd_py
    assert "push_ledd_morse_feedback" in logicd_py
    assert "register_morse_feedback_route(app, _send_ctrl_command)" in httpd_py


def main() -> None:
    test_current_reference_contains_canonical_terms()
    test_morse_readme_links_current_reference()
    test_route_status_contains_feedback_and_browser_smoke()
    test_ctrl_feedback_wiring_is_present()
    print("ok: MORSE documentation")


if __name__ == "__main__":
    main()
