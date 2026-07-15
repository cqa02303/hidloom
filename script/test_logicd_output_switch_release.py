#!/usr/bin/env python3
"""Local smoke test for releasing held keys before output target switches."""
from __future__ import annotations

import glob
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.hid_report import HidState  # noqa: E402
from logicd.output import create_dynamic_write_fn  # noqa: E402


def main() -> None:
    state = HidState()
    uinput_reports: list[bytes] = []
    gadget_writes: list[tuple[int, bytes]] = []

    orig_glob = glob.glob
    orig_open = os.open
    orig_write = os.write
    orig_close = os.close

    try:
        glob.glob = lambda _pattern: []  # type: ignore[assignment]
        os.open = lambda _path, _flags: 101  # type: ignore[assignment]
        os.write = lambda fd, data: gadget_writes.append((fd, bytes(data))) or len(data)  # type: ignore[assignment]
        os.close = lambda _fd: None  # type: ignore[assignment]

        write = create_dynamic_write_fn(
            "/dev/hidg0",
            {},
            get_state=state.build,
            release_all=state.release_all,
            uinput_factory=lambda _cfg: (lambda data: uinput_reports.append(bytes(data))),
        )

        state.press(0x04)
        write(state.build())
        assert uinput_reports[-1] == bytes([0, 0, 0x04, 0, 0, 0, 0, 0])

        write.force_gadget()
        assert state.build() == HidState.null_report()
        assert uinput_reports[-1] == HidState.null_report()
        assert gadget_writes[-1] == (101, HidState.null_report())

        state.press(0x05)
        write(state.build())
        assert gadget_writes[-1] == (101, bytes([0, 0, 0x05, 0, 0, 0, 0, 0]))

        write.force_uinput()
        assert state.build() == HidState.null_report()
        assert gadget_writes[-1] == (101, HidState.null_report())

        gadget_writes.clear()
        uinput_reports.clear()
        write = create_dynamic_write_fn(
            "/dev/hidg0",
            {},
            get_state=state.build,
            release_all=state.release_all,
            uinput_factory=lambda _cfg: (lambda data: uinput_reports.append(bytes(data))),
            gadget_transform=lambda data: b"\x01" + bytes(data),
        )
        state.press(0x06)
        write(state.build())
        assert uinput_reports[-1] == bytes([0, 0, 0x06, 0, 0, 0, 0, 0])

        write.force_gadget()
        assert gadget_writes[-1] == (101, b"\x01" + HidState.null_report())

        state.press(0x07)
        write(state.build())
        assert gadget_writes[-1] == (101, bytes([0x01, 0, 0, 0x07, 0, 0, 0, 0, 0]))

        state.release_all()
        broker_reports: list[bytes] = []
        gadget_writes.clear()
        uinput_reports.clear()
        write = create_dynamic_write_fn(
            "/dev/hidg0",
            {},
            get_state=state.build,
            release_all=state.release_all,
            uinput_factory=lambda _cfg: (lambda data: uinput_reports.append(bytes(data))),
            gadget_write_fn=lambda data: broker_reports.append(bytes(data)),
        )
        state.press(0x08)
        write(state.build())
        assert uinput_reports[-1] == bytes([0, 0, 0x08, 0, 0, 0, 0, 0])

        write.force_gadget()
        assert state.build() == HidState.null_report()
        assert broker_reports[-1] == HidState.null_report()

        state.press(0x09)
        write(state.build())
        assert broker_reports[-1] == bytes([0, 0, 0x09, 0, 0, 0, 0, 0])

        write.force_uinput()
        assert state.build() == HidState.null_report()
        assert broker_reports[-1] == HidState.null_report()

    finally:
        glob.glob = orig_glob  # type: ignore[assignment]
        os.open = orig_open  # type: ignore[assignment]
        os.write = orig_write  # type: ignore[assignment]
        os.close = orig_close  # type: ignore[assignment]

    print("ok: logicd releases held keys before output target switches")


if __name__ == "__main__":
    main()
