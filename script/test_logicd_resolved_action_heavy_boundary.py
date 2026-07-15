#!/usr/bin/env python3
"""Static checks for heavy resolved-action boundaries in logicd."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _async_body(source: str, name: str) -> str:
    marker = f"async def {name}("
    start = source.index(marker)
    candidates = [
        pos for pos in (
            source.find("\nasync def ", start + len(marker)),
            source.find("\ndef ", start + len(marker)),
        )
        if pos != -1
    ]
    end = min(candidates) if candidates else len(source)
    return source[start:end]


def main() -> None:
    input_events = (ROOT / "daemon" / "logicd" / "input_events.py").read_text(encoding="utf-8")
    process_body = _async_body(input_events, "process_matrix_event")
    resolved_body = _async_body(input_events, "handle_resolved_action")

    # Raw matrix processing must remain generic; heavy side effects are action-level only.
    heavy_terms = [
        "bt_manager.handle_action",
        "wifi_manager.handle_action",
        "ctx.macros.handle",
        "ensure_powered_for_output",
        "get_status()",
        "_push_bt_alert",
        "_push_wifi_alert",
        "_prepare_bt_output",
    ]
    for term in heavy_terms:
        assert term not in process_body, f"process_matrix_event should not directly contain {term}"

    # Resolved action dispatch is the intentional boundary for heavyweight actions.
    assert "ctx.bt_manager.handle_action" in resolved_body
    assert "ctx.wifi_manager.handle_action" in resolved_body
    assert "ctx.macros.handle" in resolved_body
    assert "_prepare_bt_output" in resolved_body
    assert "_OUTPUT_SWITCH_ACTIONS" in input_events
    assert "action in _OUTPUT_SWITCH_ACTIONS" in resolved_body

    # Heavy alerts/status lookups should stay behind action-specific branches.
    assert "if handled:" in resolved_body
    assert "if is_press:" in resolved_body
    assert "_push_bt_alert" in resolved_body
    assert "_push_wifi_alert" in resolved_body

    # Do not let raw matrix handling grow direct file/process responsibilities.
    forbidden_process_terms = ["open(", "Path(", "write_text", "json.dump", "subprocess"]
    for term in forbidden_process_terms:
        assert term not in process_body, f"process_matrix_event should not contain {term}"

    print("ok: heavy resolved actions stay outside raw matrix processing")


if __name__ == "__main__":
    main()
