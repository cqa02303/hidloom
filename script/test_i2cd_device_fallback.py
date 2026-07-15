#!/usr/bin/env python3
"""Smoke-test i2cd keeps running when the OLED is absent."""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

if "luma" not in sys.modules:
    class DeviceNotFoundError(Exception):
        pass

    def fake_i2c(*args, **kwargs):
        return object()

    def fake_canvas(*args, **kwargs):
        raise AssertionError("canvas is not used by this smoke test")

    sys.modules["luma"] = types.ModuleType("luma")
    sys.modules["luma.core"] = types.ModuleType("luma.core")
    sys.modules["luma.core.interface"] = types.ModuleType("luma.core.interface")
    sys.modules["luma.core.interface.serial"] = types.SimpleNamespace(i2c=fake_i2c)
    sys.modules["luma.core.render"] = types.SimpleNamespace(canvas=fake_canvas)
    sys.modules["luma.core.error"] = types.SimpleNamespace(DeviceNotFoundError=DeviceNotFoundError)
    sys.modules["luma.oled"] = types.ModuleType("luma.oled")
    sys.modules["luma.oled.device"] = types.SimpleNamespace(sh1107=lambda *args, **kwargs: object())
else:
    from luma.core.error import DeviceNotFoundError  # type: ignore[no-redef]

from PIL import Image  # noqa: E402

from i2cd import i2cd  # noqa: E402


class _FakeDisplay:
    mode = "1"
    width = 64
    height = 128
    size = (64, 128)
    bounding_box = (0, 0, 63, 127)

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.display_count = 0
        self.cleanup_count = 0

    def display(self, _image) -> None:
        self.display_count += 1
        if self.fail:
            raise OSError("i2c write failed")

    def cleanup(self) -> None:
        self.cleanup_count += 1


def main() -> None:
    old_sh1107 = i2cd.sh1107
    try:
        i2cd.sh1107 = lambda *args, **kwargs: (_ for _ in ()).throw(DeviceNotFoundError("missing"))
        device = i2cd._init_device({"oled": {"width": 64, "height": 128, "address": "0x3C"}})
        assert device.width == 64
        assert device.height == 128
        assert device.size == (64, 128)
        device.display(Image.new(device.mode, device.size))
        device.cleanup()
    finally:
        i2cd.sh1107 = old_sh1107

    flaky = _FakeDisplay(fail=True)
    recovered = _FakeDisplay()
    factory_calls = []

    def factory():
        factory_calls.append(True)
        return recovered

    device = i2cd._RecoveringDisplay(flaky, factory, cooldown_sec=30.0)
    image = Image.new(device.mode, device.size)
    device.display(image)
    assert len(factory_calls) == 1
    assert flaky.display_count == 1
    assert flaky.cleanup_count == 1
    assert recovered.display_count == 1
    assert device.recovery_count == 1

    failing_again = _FakeDisplay(fail=True)
    factory_calls.clear()
    device = i2cd._RecoveringDisplay(failing_again, factory, cooldown_sec=30.0)
    device.display(image)
    device._device = failing_again
    device.display(image)
    assert len(factory_calls) == 1

    print("ok: i2cd falls back and retries OLED display after write failures")


if __name__ == "__main__":
    main()
