"""Direct-frame socket receiver for ledd.

This module listens for internal high-speed full-frame LED packets. Packets are
validated and then handed to ledd through callbacks. Producer connection changes
are also exposed through callbacks so ledd can apply a fallback policy when a
producer disconnects.
"""
from __future__ import annotations

import logging
import os
import socket
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .direct_frame import (
    BYTES_PER_LED,
    HEADER_SIZE,
    HEADER_STRUCT,
    MAGIC,
    DirectFrameError,
    DirectFrameFormat,
    DirectFramePacket,
    decode_direct_frame,
    validate_led_count,
)

log = logging.getLogger("ledd.direct_frame")

DEFAULT_DIRECT_FRAME_SOCKET = "/tmp/ledd_direct_frame.sock"
MAX_PACKET_BYTES = 128 * 1024


@dataclass
class DirectFrameReceiverStats:
    """Observable state for the direct-frame socket receiver."""

    accepted_frames: int = 0
    rejected_frames: int = 0
    bytes_received: int = 0
    last_frame_id: int | None = None
    last_error: str = ""
    producer_connects: int = 0
    producer_disconnects: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "accepted_frames": self.accepted_frames,
            "rejected_frames": self.rejected_frames,
            "bytes_received": self.bytes_received,
            "last_frame_id": self.last_frame_id,
            "last_error": self.last_error,
            "producer_connects": self.producer_connects,
            "producer_disconnects": self.producer_disconnects,
        }


def recv_exact(conn: socket.socket, size: int) -> bytes | None:
    """Receive exactly size bytes or None on clean EOF."""
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = conn.recv(remaining)
        if not chunk:
            return None if not chunks else b"".join(chunks)
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def expected_packet_size_from_header(header: bytes) -> int:
    """Return expected full packet size from a direct-frame header."""
    if len(header) != HEADER_SIZE:
        raise DirectFrameError(f"header length mismatch: got={len(header)} expected={HEADER_SIZE}")
    magic, _frame_id, led_count, raw_format, _flags = HEADER_STRUCT.unpack(header)
    if magic != MAGIC:
        raise DirectFrameError(f"invalid magic: {magic!r}")
    try:
        DirectFrameFormat(int(raw_format))
    except ValueError as exc:
        raise DirectFrameError(f"unsupported direct frame format: {raw_format!r}") from exc
    validate_led_count(int(led_count))
    expected = HEADER_SIZE + int(led_count) * BYTES_PER_LED
    if expected > MAX_PACKET_BYTES:
        raise DirectFrameError(f"packet too large: {expected} > {MAX_PACKET_BYTES}")
    return expected


def record_direct_frame_packet(
    packet: bytes,
    *,
    stats: DirectFrameReceiverStats,
    expected_led_count: int,
    on_frame: Callable[[DirectFramePacket], None] | None = None,
) -> bool:
    """Validate one full packet and update stats.

    Invalid packets are counted and ignored. This function does not raise for
    DirectFrameError so socket handling can keep running.
    """
    stats.bytes_received += len(packet)
    try:
        frame = decode_direct_frame(packet, expected_led_count=expected_led_count)
    except DirectFrameError as exc:
        stats.rejected_frames += 1
        stats.last_error = str(exc)
        log.warning("direct-frame packet rejected: %s", exc)
        return False
    stats.accepted_frames += 1
    stats.last_frame_id = frame.frame_id
    stats.last_error = ""
    log.debug("direct-frame packet accepted frame_id=%d led_count=%d", frame.frame_id, frame.led_count)
    if on_frame is not None:
        on_frame(frame)
    return True


def handle_direct_frame_client(
    conn: socket.socket,
    *,
    expected_led_count: int,
    stats: DirectFrameReceiverStats,
    stop_event: threading.Event,
    on_frame: Callable[[DirectFramePacket], None] | None = None,
) -> None:
    """Handle one connected direct-frame producer."""
    with conn:
        while not stop_event.is_set():
            header = recv_exact(conn, HEADER_SIZE)
            if header is None:
                return
            if len(header) != HEADER_SIZE:
                stats.rejected_frames += 1
                stats.last_error = f"short header: {len(header)}"
                log.warning("direct-frame short header: %d", len(header))
                return
            try:
                expected_size = expected_packet_size_from_header(header)
            except DirectFrameError as exc:
                stats.rejected_frames += 1
                stats.last_error = str(exc)
                log.warning("direct-frame header rejected: %s", exc)
                return
            payload_size = expected_size - HEADER_SIZE
            payload = recv_exact(conn, payload_size)
            if payload is None or len(payload) != payload_size:
                got = 0 if payload is None else len(payload)
                stats.rejected_frames += 1
                stats.last_error = f"short payload: got={got} expected={payload_size}"
                log.warning("direct-frame short payload: got=%d expected=%d", got, payload_size)
                return
            record_direct_frame_packet(
                header + payload,
                stats=stats,
                expected_led_count=expected_led_count,
                on_frame=on_frame,
            )


def direct_frame_receiver(
    socket_path: str,
    expected_led_count: int,
    stop_event: threading.Event,
    *,
    stats: DirectFrameReceiverStats | None = None,
    on_frame: Callable[[DirectFramePacket], None] | None = None,
    on_producer_connected: Callable[[], None] | None = None,
    on_producer_disconnected: Callable[[], None] | None = None,
) -> DirectFrameReceiverStats:
    """Listen for direct-frame packets until stop_event is set."""
    stats = stats or DirectFrameReceiverStats()
    path = Path(socket_path)
    try:
        if path.exists():
            path.unlink()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        with server:
            server.bind(str(path))
            os.chmod(path, 0o666)
            server.listen(1)
            server.settimeout(0.5)
            log.info("direct-frame socket listening on %s expected_led_count=%d", socket_path, expected_led_count)
            while not stop_event.is_set():
                try:
                    conn, _addr = server.accept()
                except socket.timeout:
                    continue
                except OSError as exc:
                    if stop_event.is_set():
                        break
                    log.warning("direct-frame accept failed: %s", exc)
                    continue
                stats.producer_connects += 1
                log.info("direct-frame producer connected")
                if on_producer_connected is not None:
                    on_producer_connected()
                try:
                    handle_direct_frame_client(
                        conn,
                        expected_led_count=expected_led_count,
                        stats=stats,
                        stop_event=stop_event,
                        on_frame=on_frame,
                    )
                finally:
                    stats.producer_disconnects += 1
                    log.info("direct-frame producer disconnected")
                    if on_producer_disconnected is not None:
                        on_producer_disconnected()
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    return stats
