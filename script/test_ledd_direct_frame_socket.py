#!/usr/bin/env python3
"""Regression tests for the ledd direct-frame socket contract."""
from __future__ import annotations

import socket
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from ledd.direct_frame import DirectFrameError, encode_direct_frame, pack_rgb_triples  # noqa: E402
from ledd.direct_frame_socket import (  # noqa: E402
    DirectFrameReceiverStats,
    expected_packet_size_from_header,
    handle_direct_frame_client,
    record_direct_frame_packet,
)


def expect_error(fn, text: str) -> None:
    try:
        fn()
    except DirectFrameError as exc:
        assert text in str(exc), str(exc)
    else:
        raise AssertionError(f"expected DirectFrameError containing {text!r}")


def main() -> None:
    payload = pack_rgb_triples([(1, 2, 3), (4, 5, 6)])
    packet = encode_direct_frame(frame_id=10, led_count=2, payload=payload)
    stats = DirectFrameReceiverStats()
    seen: list[int] = []

    assert expected_packet_size_from_header(packet[:12]) == len(packet)
    expect_error(lambda: expected_packet_size_from_header(packet[:3]), "header length mismatch")

    ok = record_direct_frame_packet(packet, stats=stats, expected_led_count=2, on_frame=lambda frame: seen.append(frame.frame_id))
    assert ok is True
    assert stats.accepted_frames == 1
    assert stats.rejected_frames == 0
    assert stats.bytes_received == len(packet)
    assert stats.last_frame_id == 10
    assert stats.last_error == ""
    assert seen == [10]

    bad = packet[:-1]
    ok = record_direct_frame_packet(bad, stats=stats, expected_led_count=2)
    assert ok is False
    assert stats.accepted_frames == 1
    assert stats.rejected_frames == 1
    assert "packet length mismatch" in stats.last_error

    # Exercise stream handling with one good packet followed by EOF.
    left, right = socket.socketpair()
    stream_stats = DirectFrameReceiverStats()
    stream_seen: list[int] = []
    stop_event = threading.Event()
    thread = threading.Thread(
        target=handle_direct_frame_client,
        kwargs={
            "conn": left,
            "expected_led_count": 2,
            "stats": stream_stats,
            "stop_event": stop_event,
            "on_frame": lambda frame: stream_seen.append(frame.frame_id),
        },
    )
    thread.start()
    right.sendall(packet)
    right.close()
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    assert stream_stats.accepted_frames == 1
    assert stream_stats.rejected_frames == 0
    assert stream_stats.last_frame_id == 10
    assert stream_seen == [10]

    # Header-invalid stream should reject and close the client.
    left2, right2 = socket.socketpair()
    stream_stats2 = DirectFrameReceiverStats()
    thread2 = threading.Thread(
        target=handle_direct_frame_client,
        kwargs={
            "conn": left2,
            "expected_led_count": 2,
            "stats": stream_stats2,
            "stop_event": threading.Event(),
        },
    )
    thread2.start()
    right2.sendall(b"NOPE" + packet[4:12])
    right2.close()
    thread2.join(timeout=2.0)
    assert not thread2.is_alive()
    assert stream_stats2.accepted_frames == 0
    assert stream_stats2.rejected_frames == 1
    assert "invalid magic" in stream_stats2.last_error

    print("ok: ledd direct frame socket")


if __name__ == "__main__":
    main()
