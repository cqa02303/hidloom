"""Small binary protocol helpers used by logicd sockets."""
from __future__ import annotations

PRESS = 0x50
RELEASE = 0x52


def make_key_event_packet(keycode: int, modifier: int, is_press: bool) -> bytes:
    event_type = PRESS if is_press else RELEASE
    return bytes([event_type, keycode & 0xFF, modifier & 0xFF, 0x00])


def parse_key_event_packet(pkt: bytes) -> tuple[int, int, bool] | None:
    if len(pkt) != 4:
        return None
    event_type = pkt[0]
    if event_type not in (PRESS, RELEASE):
        return None
    return pkt[1], pkt[2], event_type == PRESS


def parse_matrix_event_packet(pkt: bytes) -> tuple[str, int, int] | None:
    if len(pkt) != 4:
        return None
    kind_b = pkt[0]
    if kind_b not in (PRESS, RELEASE):
        return None
    try:
        row = int(chr(pkt[1]), 16)
        col = int(chr(pkt[2]), 16)
    except ValueError:
        return None
    return chr(kind_b), row, col
