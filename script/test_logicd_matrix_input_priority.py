#!/usr/bin/env python3
"""Static checks for logicd matrix input path priority boundaries."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _function_body(source: str, name: str) -> str:
    marker = f"async def {name}("
    start = source.index(marker)
    next_marker = source.find("\nasync def ", start + len(marker))
    if next_marker == -1:
        next_marker = len(source)
    return source[start:next_marker]


def main() -> None:
    sockets = (ROOT / "daemon" / "logicd" / "sockets.py").read_text(encoding="utf-8")
    matrix_pipeline = (ROOT / "daemon" / "logicd" / "matrix_pipeline.py").read_text(encoding="utf-8")
    logicd_main = (ROOT / "daemon" / "logicd" / "logicd.py").read_text(encoding="utf-8")
    readme = (ROOT / "daemon" / "logicd" / "README.md").read_text(encoding="utf-8")
    matrix_docs = (
        ROOT / "docs" / "daemon" / "specs" / "matrixd" / "stability-docs.md"
    ).read_text(encoding="utf-8")

    socket_body = _function_body(sockets, "handle_matrix_client")
    assert "reader.readexactly(4)" in socket_body
    assert "parse_matrix_event_packet" in socket_body
    assert "matrix_in_range" in socket_body
    assert "await queue.put((kind, row, col))" in socket_body
    assert "process_matrix_event" not in socket_body
    assert "writer.write" not in socket_body
    assert "push_ledd" not in socket_body
    assert "hid" not in socket_body.lower()

    pipeline_client_body = _function_body(matrix_pipeline, "handle_matrix_client")
    assert "socket_handle_matrix_client" in pipeline_client_body
    assert "queue=runtime.queue" in pipeline_client_body
    assert "process_matrix_event" not in pipeline_client_body

    event_processor_body = _function_body(matrix_pipeline, "event_processor")
    assert "runtime.queue.get" in event_processor_body
    assert "process_matrix_event(event, input_event_context())" in event_processor_body
    assert "process_interaction_tick" in event_processor_body

    assert "pipeline_handle_matrix_client" in logicd_main
    assert "pipeline_event_processor" in logicd_main
    assert "matrix input priority" in readme
    assert "matrixd >= logicd matrix input path" in readme
    assert "logicd" in matrix_docs

    print("ok: logicd matrix input path keeps socket intake lightweight")


if __name__ == "__main__":
    main()
