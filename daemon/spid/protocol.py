"""JSON Lines protocol helpers for spid -> logicd mouse motion events.

The first spid protocol is intentionally human-readable JSON Lines.  It is
simple to inspect during real-device tuning and does not affect the existing HID
report format.  If high-rate binary framing becomes necessary, decide that as a
separate protocol change.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MotionEvent:
    dx: int = 0
    dy: int = 0
    wheel: int = 0
    buttons: int = 0
    sensor: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "t": "motion",
            "dx": int(self.dx),
            "dy": int(self.dy),
            "wheel": int(self.wheel),
            "buttons": int(self.buttons),
            "sensor": self.sensor,
        }

    def is_zero(self) -> bool:
        return self.dx == 0 and self.dy == 0 and self.wheel == 0 and self.buttons == 0


@dataclass(frozen=True)
class StatusEvent:
    sensor: str
    ok: bool
    msg: str = ""
    cpi: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"t": "status", "sensor": self.sensor, "ok": bool(self.ok), "msg": self.msg}
        if self.cpi is not None:
            payload["cpi"] = int(self.cpi)
        return payload


def encode_event(event: MotionEvent | StatusEvent | dict[str, Any]) -> bytes:
    if hasattr(event, "to_dict"):
        payload = event.to_dict()  # type: ignore[union-attr]
    else:
        payload = dict(event)
    return (json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def decode_event(line: bytes | str) -> dict[str, Any]:
    text = line.decode("utf-8") if isinstance(line, bytes) else line
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("spid event must be a JSON object")
    return payload


def decode_motion(line: bytes | str) -> MotionEvent:
    payload = decode_event(line)
    if payload.get("t") != "motion":
        raise ValueError(f"expected motion event, got {payload.get('t')!r}")
    return MotionEvent(
        dx=int(payload.get("dx", 0)),
        dy=int(payload.get("dy", 0)),
        wheel=int(payload.get("wheel", 0)),
        buttons=int(payload.get("buttons", 0)),
        sensor=str(payload.get("sensor", "")),
    )
