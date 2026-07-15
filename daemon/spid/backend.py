"""Mouse sensor backend interfaces for spid.

`spid` owns sensor-specific SPI details. Higher layers should only see a common
MotionEvent stream, regardless of whether the source is disabled, mock, or
PAW3805EK.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
import time
from typing import Any, Protocol

from .protocol import MotionEvent


class MouseSensorBackend(Protocol):
    name: str

    async def init(self) -> None:
        """Initialize the sensor backend."""

    async def read_motion(self) -> MotionEvent:
        """Read one motion sample."""

    async def set_cpi(self, cpi: int) -> None:
        """Set CPI/resolution when supported."""

    async def close(self) -> None:
        """Release resources."""


class SensorInitializationError(RuntimeError):
    """Raised when an implemented sensor backend cannot initialize hardware."""


@dataclass
class DisabledMouseSensorBackend:
    """No-op backend for keyboard builds without an SPI mouse sensor.

    Design intent:
    sensor-less hardware should not need spid at all. If spid is started by
    mistake, this backend provides an inert, non-fatal state rather than trying
    to open SPI or treating the missing sensor as an error.
    """

    name: str = "none"

    async def init(self) -> None:
        return None

    async def read_motion(self) -> MotionEvent:
        return MotionEvent(sensor=self.name)

    async def set_cpi(self, cpi: int) -> None:
        return None

    async def close(self) -> None:
        return None


@dataclass
class MockMouseSensorBackend:
    """Deterministic mock backend for tests and plumbing checks."""

    name: str = "mock"
    cpi: int = 800
    dx: int = 1
    dy: int = 0
    wheel: int = 0
    buttons: int = 0
    initialized: bool = False
    reads: int = 0

    async def init(self) -> None:
        self.initialized = True

    async def read_motion(self) -> MotionEvent:
        self.reads += 1
        return MotionEvent(dx=self.dx, dy=self.dy, wheel=self.wheel, buttons=self.buttons, sensor=self.name)

    async def set_cpi(self, cpi: int) -> None:
        self.cpi = int(cpi)

    async def close(self) -> None:
        self.initialized = False


# PAW3805EK register map used by the polling backend.  The values match the
# working QMK implementation in cqa02303/hfk/right/paw3805ek.c, but this Python
# backend is a fresh implementation for spid's MotionEvent interface.
PAW_REG_PRODUCT_ID = 0x00
PAW_REG_REVISION_ID = 0x01
PAW_REG_MOTION = 0x02
PAW_REG_DELTA_X_L = 0x03
PAW_REG_DELTA_Y_L = 0x04
PAW_REG_OPERATION_MODE = 0x05
PAW_REG_CONFIGURATION = 0x06
PAW_REG_WRITE_PROTECT = 0x09
PAW_REG_CPI_X = 0x0D
PAW_REG_CPI_Y = 0x0E
PAW_REG_DELTA_X_H = 0x11
PAW_REG_DELTA_Y_H = 0x12

PAW_PRODUCT_ID = 0x31
PAW_REVISION_ID = 0x61
PAW_MOTION_BIT = 0x80
PAW_WRITE_BIT = 0x80

PAW_MIN_CPI = 200
PAW_MAX_CPI = 3000
PAW_CPI_STEP = 200


def _clamp_cpi(cpi: int) -> int:
    return max(PAW_MIN_CPI, min(PAW_MAX_CPI, int(cpi)))


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return int(value, 0)


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return float(value)


@dataclass
class Paw3805EkBackend:
    """PAW3805EK polling backend.

    This backend is activated only when explicitly selected with
    ``SPID_BACKEND=PAW3805EK``.  It uses Linux spidev, leaves chip select to the
    SPI controller, polls ``REG_Motion``, and converts the 12-bit two's
    complement deltas into spid ``MotionEvent`` objects.

    Default settings can be overridden with environment variables:

    - ``SPID_SPI_BUS``: Linux SPI bus number, default ``0``
    - ``SPID_SPI_DEVICE``: Linux SPI device/chip-select, default ``0``
    - ``SPID_SPI_SPEED_HZ``: SPI speed, default ``2000000``
    - ``SPID_PAW3805EK_CPI``: initial CPI, default ``200``
    - ``SPID_PAW3805EK_SCALE``: dx/dy multiplier, default ``1.0``
    """

    name: str = "PAW3805EK"
    bus: int = field(default_factory=lambda: _env_int("SPID_SPI_BUS", 0))
    device: int = field(default_factory=lambda: _env_int("SPID_SPI_DEVICE", 0))
    speed_hz: int = field(default_factory=lambda: _env_int("SPID_SPI_SPEED_HZ", 2_000_000))
    mode: int = field(default_factory=lambda: _env_int("SPID_SPI_MODE", 0b11))
    cpi: int = field(default_factory=lambda: _clamp_cpi(_env_int("SPID_PAW3805EK_CPI", 200)))
    scale: float = field(default_factory=lambda: _env_float("SPID_PAW3805EK_SCALE", 1.0))
    spi: Any | None = None
    initialized: bool = False
    product_id: int | None = None
    revision_id: int | None = None

    async def init(self) -> None:
        if self.spi is None:
            try:
                import spidev  # type: ignore[import-not-found]
            except ModuleNotFoundError as exc:
                raise SensorInitializationError("python3-spidev is required for PAW3805EK backend") from exc
            self.spi = spidev.SpiDev()
            self.spi.open(self.bus, self.device)
        self.spi.max_speed_hz = int(self.speed_hz)
        self.spi.mode = int(self.mode)

        time.sleep(0.050)
        self._write(PAW_REG_CONFIGURATION, 0x80)
        time.sleep(0.050)
        time.sleep(0.010)

        detected = False
        for _ in range(5):
            self.product_id = self._read(PAW_REG_PRODUCT_ID)
            time.sleep(0.0005)
            self.revision_id = self._read(PAW_REG_REVISION_ID)
            time.sleep(0.0005)
            if self.product_id == PAW_PRODUCT_ID and self.revision_id == PAW_REVISION_ID:
                detected = True
                break
            time.sleep(0.010)
        if not detected:
            await self.close()
            raise SensorInitializationError(
                f"PAW3805EK not detected: product_id=0x{self.product_id or 0:02x} "
                f"revision_id=0x{self.revision_id or 0:02x}"
            )

        self._write(PAW_REG_WRITE_PROTECT, 0x5A)
        self._write(PAW_REG_OPERATION_MODE, 0x00)
        self._write_cpi_registers(self.cpi)
        self._write(PAW_REG_WRITE_PROTECT, 0x00)
        self._clear_motion_registers()
        time.sleep(0.010)
        self.initialized = True

    async def read_motion(self) -> MotionEvent:
        if self.spi is None or not self.initialized:
            return MotionEvent(sensor=self.name)
        motion = self._read(PAW_REG_MOTION)
        if not (motion & PAW_MOTION_BIT):
            return MotionEvent(sensor=self.name)
        dx_l = self._read(PAW_REG_DELTA_X_L)
        dy_l = self._read(PAW_REG_DELTA_Y_L)
        dx_h = self._read(PAW_REG_DELTA_X_H)
        dy_h = self._read(PAW_REG_DELTA_Y_H)
        dx = self._convert_12bit_delta(dx_h, dx_l)
        dy = self._convert_12bit_delta(dy_h, dy_l)
        if self.scale != 1.0:
            dx = int(round(dx * self.scale))
            dy = int(round(dy * self.scale))
        return MotionEvent(dx=dx, dy=dy, sensor=self.name)

    async def set_cpi(self, cpi: int) -> None:
        self.cpi = _clamp_cpi(cpi)
        if self.spi is None or not self.initialized:
            return None
        self._write(PAW_REG_WRITE_PROTECT, 0x5A)
        self._write_cpi_registers(self.cpi)
        self._write(PAW_REG_WRITE_PROTECT, 0x00)
        time.sleep(0.010)
        return None

    async def close(self) -> None:
        self.initialized = False
        if self.spi is not None:
            close = getattr(self.spi, "close", None)
            if callable(close):
                close()
            self.spi = None

    def _write_cpi_registers(self, cpi: int) -> None:
        value = (_clamp_cpi(cpi) // PAW_CPI_STEP) & 0xFF
        self._write(PAW_REG_CPI_X, value)
        self._write(PAW_REG_CPI_Y, value)

    def _clear_motion_registers(self) -> None:
        self._read(PAW_REG_MOTION)
        self._read(PAW_REG_DELTA_X_L)
        self._read(PAW_REG_DELTA_X_H)
        self._read(PAW_REG_DELTA_Y_L)
        self._read(PAW_REG_DELTA_Y_H)

    def _write(self, reg_addr: int, data: int) -> None:
        self._require_spi().xfer2([(reg_addr | PAW_WRITE_BIT) & 0xFF, data & 0xFF])
        time.sleep(0.000001)

    def _read(self, reg_addr: int) -> int:
        response = self._require_spi().xfer2([reg_addr & 0x7F, 0x00])
        time.sleep(0.000001)
        return int(response[-1]) & 0xFF

    def _require_spi(self) -> Any:
        if self.spi is None:
            raise SensorInitializationError("PAW3805EK SPI device is not open")
        return self.spi

    @staticmethod
    def _convert_12bit_delta(high: int, low: int) -> int:
        value = ((high & 0x0F) << 8) | (low & 0xFF)
        if value & 0x800:
            value -= 0x1000
        return value


def is_backend_disabled(name: str | None = None) -> bool:
    normalized = (name or "none").strip().lower().replace("_", "-")
    return normalized in {"", "none", "disabled", "off"}


def build_backend(name: str | None = None) -> MouseSensorBackend:
    normalized = (name or "none").strip().lower().replace("_", "-")
    if is_backend_disabled(normalized):
        return DisabledMouseSensorBackend()
    if normalized in {"mock", "dummy"}:
        return MockMouseSensorBackend()
    if normalized in {"paw3805ek", "paw-3805ek", "paw3805", "p3805ek"}:
        return Paw3805EkBackend()
    raise ValueError(f"unknown spid backend: {name}")
