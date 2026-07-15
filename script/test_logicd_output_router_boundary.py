#!/usr/bin/env python3
"""Static checks for logicd OutputRouter boundaries from matrix input."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _function_body(source: str, name: str) -> str:
    marker = f"def {name}("
    start = source.index(marker)
    candidates = [
        pos for pos in (
            source.find("\n    def ", start + len(marker)),
            source.find("\ndef ", start + len(marker)),
            source.find("\nclass ", start + len(marker)),
        )
        if pos != -1
    ]
    end = min(candidates) if candidates else len(source)
    return source[start:end]


def main() -> None:
    sockets = (ROOT / "daemon" / "logicd" / "sockets.py").read_text(encoding="utf-8")
    matrix_pipeline = (ROOT / "daemon" / "logicd" / "matrix_pipeline.py").read_text(encoding="utf-8")
    input_events = (ROOT / "daemon" / "logicd" / "input_events.py").read_text(encoding="utf-8")
    output_router = (ROOT / "daemon" / "logicd" / "output_router.py").read_text(encoding="utf-8")
    matrix_socket_body = sockets[sockets.index("async def handle_matrix_client") : sockets.index("async def handle_ctrl_client")]
    event_processor_body = matrix_pipeline[matrix_pipeline.index("async def event_processor") :]
    process_body = input_events[input_events.index("async def process_matrix_event") : input_events.index("async def handle_encoder_event")]
    resolved_body = input_events[input_events.index("async def handle_resolved_action") : input_events.index("def _handle_lock_led_overlay")]
    router_body = output_router[output_router.index("class OutputRouter") :]
    router_send_body = _function_body(router_body, "send")

    # Raw matrix socket intake must not know about OutputRouter or output targets.
    for term in ("OutputRouter", "output_router", "force_gadget", "force_bt", "force_uinput", "send(report"):
        assert term not in matrix_socket_body, f"matrix socket intake should not contain {term}"
        assert term not in event_processor_body, f"event_processor should not directly contain {term}"

    # Raw matrix bookkeeping should not directly call output-router target switching.
    for term in ("force_gadget", "force_bt", "force_uinput", "force_auto", "current_output_target"):
        assert term not in process_body, f"process_matrix_event should not contain {term}"

    # Output switching remains an action-level concern.
    assert "_OUTPUT_SWITCH_ACTIONS" in input_events
    assert "action in _OUTPUT_SWITCH_ACTIONS" in resolved_body
    assert "handle_output_target" not in process_body

    # OutputRouter remains a report fan-out component with injected backends.
    assert "class OutputRouter" in output_router
    assert "def send(self, report: bytes) -> dict[str, bool]" in output_router
    assert "backend.write(report)" in router_send_body
    assert "matrix" not in output_router.lower()
    assert "parse_matrix_event_packet" not in output_router
    assert "/tmp/matrix_events.sock" not in output_router

    print("ok: logicd OutputRouter stays decoupled from matrix socket intake")


if __name__ == "__main__":
    main()
