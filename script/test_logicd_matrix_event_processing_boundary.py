#!/usr/bin/env python3
"""Static checks for logicd matrix event processing boundaries."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _function_body(source: str, name: str) -> str:
    marker = f"async def {name}("
    start = source.index(marker)
    candidates = [
        pos for pos in (
            source.find("\nasync def ", start + len(marker)),
            source.find("\ndef ", start + len(marker)),
            source.find("\n@dataclass", start + len(marker)),
        )
        if pos != -1
    ]
    end = min(candidates) if candidates else len(source)
    return source[start:end]


def main() -> None:
    input_events = (ROOT / "daemon" / "logicd" / "input_events.py").read_text(encoding="utf-8")
    matrix_pipeline = (ROOT / "daemon" / "logicd" / "matrix_pipeline.py").read_text(encoding="utf-8")
    process_body = _function_body(input_events, "process_matrix_event")
    resolved_body = _function_body(input_events, "handle_resolved_action")
    pipeline_body = _function_body(matrix_pipeline, "event_processor")

    assert "ctx.pressed_matrix.add(key)" in process_body
    assert "ctx.pressed_matrix.discard(key)" in process_body
    assert "ctx.push_ledd_key_event(row, col, is_press)" in process_body
    assert "ctx.interactions.on_key" in process_body
    assert "ctx.interactions.on_tick" in process_body
    assert "_dispatch_interaction_events" in process_body

    # Keep direct matrix event processing free from blocking file/config writes.
    forbidden_process_terms = [
        "open(",
        "Path(",
        "write_text",
        "write_bytes",
        "json.dump",
        "save_runtime",
        "save_led_state",
        "schedule_led_state_save",
        "os.",
        "subprocess",
    ]
    for term in forbidden_process_terms:
        assert term not in process_body, f"process_matrix_event should not contain {term}"

    # Radio/output side effects are resolved-action responsibilities, not raw matrix bookkeeping.
    assert "ctx.bt_manager.handle_action" in resolved_body
    assert "ctx.wifi_manager.handle_action" in resolved_body
    assert "ctx.macros.handle" in resolved_body
    assert "handle_resolved_action" not in process_body.split("_dispatch_interaction_events", 1)[0]

    assert "runtime.queue.get" in pipeline_body
    assert "process_matrix_event(event, input_event_context())" in pipeline_body
    assert "LOGICD_MATRIX_INPUT_PATH_REVIEW" not in input_events

    print("ok: logicd matrix event processing boundary stays lightweight")


if __name__ == "__main__":
    main()
