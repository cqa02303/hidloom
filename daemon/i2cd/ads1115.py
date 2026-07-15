"""ADS1115 analog-stick reader helpers for i2cd."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from typing import Any

try:
    from smbus2 import SMBus
except Exception:  # pragma: no cover - exercised on devices without smbus2
    SMBus = None  # type: ignore[assignment]

REG_CONVERSION = 0x00
REG_CONFIG = 0x01

PGA_4_096V = 0x0200
MODE_SINGLE_SHOT = 0x0100
DATA_RATE_860SPS = 0x00E0
COMPARATOR_DISABLED = 0x0003

MUX_SINGLE_ENDED = {
    0: 0x4000,
    1: 0x5000,
    2: 0x6000,
    3: 0x7000,
}

LSB_VOLTS_4_096 = 4.096 / 32768


@dataclass(frozen=True)
class AxisCalibration:
    channel: int
    center: float
    low: float
    high: float
    invert: bool = False

    def with_center(self, center: float) -> "AxisCalibration":
        return replace(self, center=float(center))

    def normalize(self, volts: float) -> int:
        if volts >= self.center:
            span = max(0.001, self.high - self.center)
            value = round((volts - self.center) * 100 / span)
        else:
            span = max(0.001, self.center - self.low)
            value = -round((self.center - volts) * 100 / span)
        value = max(-100, min(100, int(value)))
        return -value if self.invert else value


@dataclass(frozen=True)
class AnalogStickConfig:
    enabled: bool
    address: int
    bus: int
    stick_index: int
    poll_interval: float
    idle_poll_interval: float
    idle_after_sec: float
    deadzone: int
    auto_center_on_start: bool
    auto_center_duration: float
    x_axis: AxisCalibration
    y_axis: AxisCalibration
    ctrl_socket: str

    def with_centers(self, x_center: float, y_center: float) -> "AnalogStickConfig":
        return replace(
            self,
            x_axis=self.x_axis.with_center(x_center),
            y_axis=self.y_axis.with_center(y_center),
        )


def parse_analog_stick_config(cfg: dict[str, Any]) -> AnalogStickConfig | None:
    raw = cfg.get("analog_stick")
    if not isinstance(raw, dict) or not bool(raw.get("enabled", False)):
        return None

    def axis(name: str) -> AxisCalibration:
        item = raw.get(name)
        if not isinstance(item, dict):
            raise ValueError(f"analog_stick.{name} must be an object")
        return AxisCalibration(
            channel=int(item["channel"]),
            center=float(item["center"]),
            low=float(item["low"]),
            high=float(item["high"]),
            invert=bool(item.get("invert", False)),
        )

    ipc = cfg.get("ipc") if isinstance(cfg.get("ipc"), dict) else {}
    poll_interval = max(0.01, float(raw.get("poll_interval", 0.03)))
    idle_poll_interval = max(poll_interval, float(raw.get("idle_poll_interval", poll_interval)))
    return AnalogStickConfig(
        enabled=True,
        address=int(str(raw.get("address", "0x48")), 0),
        bus=int(raw.get("i2c_port", cfg.get("oled", {}).get("i2c_port", 1))),
        stick_index=int(raw.get("stick", 0)),
        poll_interval=poll_interval,
        idle_poll_interval=idle_poll_interval,
        idle_after_sec=max(0.0, float(raw.get("idle_after_sec", 0.5))),
        deadzone=max(0, min(100, int(raw.get("deadzone", 8)))),
        auto_center_on_start=bool(raw.get("auto_center_on_start", False)),
        auto_center_duration=max(0.0, float(raw.get("auto_center_duration", 2.0))),
        x_axis=axis("x"),
        y_axis=axis("y"),
        ctrl_socket=str(raw.get("ctrl_socket") or ipc.get("ctrl_socket") or "/tmp/ctrl_events.sock"),
    )


class ADS1115Reader:
    def __init__(self, *, bus: int, address: int) -> None:
        if SMBus is None:
            raise RuntimeError("smbus2 is not available")
        self._bus = SMBus(bus)
        self.address = address

    def close(self) -> None:
        self._bus.close()

    def read_single_ended(self, channel: int) -> float:
        if channel not in MUX_SINGLE_ENDED:
            raise ValueError(f"ADS1115 channel out of range: {channel}")
        config = (
            0x8000
            | MUX_SINGLE_ENDED[channel]
            | PGA_4_096V
            | MODE_SINGLE_SHOT
            | DATA_RATE_860SPS
            | COMPARATOR_DISABLED
        )
        self._write_word(REG_CONFIG, config)
        for _ in range(20):
            time.sleep(0.001)
            if self._read_word(REG_CONFIG) & 0x8000:
                break
        raw = self._signed16(self._read_word(REG_CONVERSION))
        return raw * LSB_VOLTS_4_096

    def _read_word(self, register: int) -> int:
        data = self._bus.read_i2c_block_data(self.address, register, 2)
        return (data[0] << 8) | data[1]

    def _write_word(self, register: int, value: int) -> None:
        self._bus.write_i2c_block_data(self.address, register, [(value >> 8) & 0xFF, value & 0xFF])

    @staticmethod
    def _signed16(value: int) -> int:
        return value - 0x10000 if value & 0x8000 else value


def normalize_stick(x_volts: float, y_volts: float, cfg: AnalogStickConfig) -> tuple[int, int]:
    x = cfg.x_axis.normalize(x_volts)
    y = cfg.y_axis.normalize(y_volts)
    if abs(x) < cfg.deadzone:
        x = 0
    if abs(y) < cfg.deadzone:
        y = 0
    return x, y


def read_stick_volts(reader: ADS1115Reader, cfg: AnalogStickConfig) -> tuple[float, float]:
    return (
        reader.read_single_ended(cfg.x_axis.channel),
        reader.read_single_ended(cfg.y_axis.channel),
    )


def build_ctrl_event(stick: int, x: int, y: int) -> bytes:
    return (json.dumps({"t": "A", "stick": stick, "x": x, "y": y}, separators=(",", ":")) + "\n").encode()
