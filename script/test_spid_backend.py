#!/usr/bin/env python3
"""Regression tests for spid sensor backend selection."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from spid.backend import (  # noqa: E402
    DisabledMouseSensorBackend,
    MockMouseSensorBackend,
    Paw3805EkBackend,
    build_backend,
    is_backend_disabled,
)


class FakeSpi:
    def __init__(self) -> None:
        self.max_speed_hz = 0
        self.mode = 0
        self.closed = False
        self.registers: dict[int, int] = {
            0x00: 0x31,  # Product ID
            0x01: 0x61,  # Revision ID
            0x02: 0x00,  # Motion
        }
        self.writes: list[tuple[int, int]] = []

    def xfer2(self, data: list[int]) -> list[int]:
        addr = data[0]
        if addr & 0x80:
            reg = addr & 0x7F
            value = data[1] & 0xFF
            self.registers[reg] = value
            self.writes.append((reg, value))
            if reg == 0x06 and value == 0x80:
                # Simulate reset bit clearing after software reset.
                self.registers[0x06] = 0x00
            return [0, 0]
        reg = addr & 0x7F
        return [0, self.registers.get(reg, 0)]

    def close(self) -> None:
        self.closed = True


async def main_async() -> None:
    disabled = build_backend("none")
    assert isinstance(disabled, DisabledMouseSensorBackend)
    await disabled.init()
    assert (await disabled.read_motion()).is_zero()
    await disabled.set_cpi(1200)
    await disabled.close()

    assert is_backend_disabled(None) is True
    assert is_backend_disabled("none") is True
    assert is_backend_disabled("off") is True
    assert is_backend_disabled("PAW3805EK") is False

    default = build_backend(None)
    assert isinstance(default, DisabledMouseSensorBackend)

    mock = build_backend("mock")
    assert isinstance(mock, MockMouseSensorBackend)
    await mock.init()
    await mock.set_cpi(1200)
    event = await mock.read_motion()
    assert event.sensor == "mock"
    assert event.dx == 1
    assert event.dy == 0
    assert mock.cpi == 1200
    await mock.close()
    assert mock.initialized is False

    paw = build_backend("PAW3805EK")
    assert isinstance(paw, Paw3805EkBackend)
    fake_spi = FakeSpi()
    paw.spi = fake_spi
    await paw.init()
    assert paw.initialized is True
    assert paw.product_id == 0x31
    assert paw.revision_id == 0x61
    assert fake_spi.max_speed_hz == 2_000_000
    assert fake_spi.mode == 0b11
    assert (0x05, 0x00) in fake_spi.writes  # normal operation mode
    assert (0x0D, 1) in fake_spi.writes     # 200 CPI / 200 step
    assert (0x0E, 1) in fake_spi.writes

    fake_spi.registers[0x02] = 0x80  # motion bit
    fake_spi.registers[0x03] = 0x05  # dx low
    fake_spi.registers[0x11] = 0x00  # dx high => +5
    fake_spi.registers[0x04] = 0xFE  # dy low
    fake_spi.registers[0x12] = 0x0F  # dy high => -2 in 12-bit two's complement
    event = await paw.read_motion()
    assert event.sensor == "PAW3805EK"
    assert event.dx == 5
    assert event.dy == -2

    await paw.set_cpi(1200)
    assert paw.cpi == 1200
    assert (0x0D, 6) in fake_spi.writes
    assert (0x0E, 6) in fake_spi.writes
    await paw.close()
    assert fake_spi.closed is True

    try:
        build_backend("ADNS-3530")
    except ValueError as exc:
        assert "unknown spid backend" in str(exc)
    else:
        raise AssertionError("unsupported sensor backend should fail")

    try:
        build_backend("unknown")
    except ValueError as exc:
        assert "unknown spid backend" in str(exc)
    else:
        raise AssertionError("unknown backend should fail")

    print("ok: spid backend")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
