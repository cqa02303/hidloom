#!/usr/bin/env python3
"""Saturated local observers cannot block native release; stop drops delayed work."""
from __future__ import annotations

import asyncio
from pathlib import Path
import socket
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "script"), str(ROOT / "daemon"), str(ROOT)]
import test_native_owner_protocol as protocol_test


async def saturated_accept_queue(*, observer=False):
    # Build before intercepting Popen; the mock applies only to the native child.
    protocol_test.ensure_native_built()
    listener = None
    fillers = []
    original_popen = protocol_test.subprocess.Popen

    def start_with_saturated_delegate(*args, **kwargs):
        nonlocal listener
        path = str(Path(kwargs["env"]["LOGICD_CORE_CTRL_SOCKET"]).parent / "full-delegate.sock")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(path)
        listener.listen(1)
        for _ in range(8):
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(0.02)
            try:
                client.connect(path)
            except (TimeoutError, BlockingIOError):
                client.close()
                break
            fillers.append(client)
        else:
            raise AssertionError("fixture did not saturate AF_UNIX accept queue")
        key = "LOGICD_CORE_MATRIX_TAP_SOCKET" if observer else "LOGICD_CORE_DELEGATE_SOCKET"
        kwargs["env"][key] = path
        return original_popen(*args, **kwargs)

    fixture = protocol_test.Fixture([{"0,0": "KC_A", "0,1": "LT(1,KC_B)"}, {}], delegate=False)
    try:
        with patch.object(protocol_test.subprocess, "Popen", side_effect=start_with_saturated_delegate):
            await fixture.__aenter__()
        try:
            await fixture.event(True)
            assert (await fixture.report(0.2))[2] == 4
            if not observer:
                await fixture.event(True, 1)
            await fixture.event(False)
            assert await fixture.report(0.2) == bytes(8), "full companion backlog blocked native release"
            state = await asyncio.wait_for(fixture.request({"t": "owner_state"}), 0.2)
            assert state["pressed"] == 0, state
            endpoint = "matrix observer" if observer else "companion"
            print(f"ok: saturated {endpoint} accept queue cannot block native release/control")
        finally:
            await fixture.__aexit__(None, None, None)
    finally:
        for client in fillers:
            client.close()
        if listener is not None:
            listener.close()


async def release_all_cancels_delayed_wrapper():
    async with protocol_test.Fixture([{"0,0": "LCTL(KC_A)"}]) as fixture:
        await fixture.event(True)
        assert await fixture.report() == bytes([1, 0, 0, 0, 0, 0, 0, 0])
        result = await fixture.request({"t": "release_all"})
        assert result["result"] == "ok", result
        assert await fixture.report() == bytes(8)
        try:
            report = await fixture.report(0.15)
        except TimeoutError:
            pass
        else:
            raise AssertionError(f"release_all resurrected delayed wrapper: {report.hex()}")
        state = await fixture.request({"t": "owner_state"})
        assert state["idle"] and state["delegate_transaction"]["scheduled_events"] == 0, state
        print("ok: release_all cancels delayed wrapper before stop returns")


async def main():
    await saturated_accept_queue()
    await saturated_accept_queue(observer=True)
    await release_all_cancels_delayed_wrapper()


if __name__ == "__main__":
    asyncio.run(main())
