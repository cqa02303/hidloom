#!/usr/bin/env python3
"""Malformed companion transactions cannot alter another native input owner."""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "script"), str(ROOT / "daemon"), str(ROOT)]
from test_native_owner_protocol import Fixture


async def conflicting_new_id_is_atomic():
    async with Fixture([{"0,0": "KC_C", "0,1": "LT(1,KC_B)"}, {}]) as fixture:
        await fixture.event(True)
        assert (await fixture.report())[2] == 6
        first, second = await fixture.open_source(), await fixture.open_source()
        await fixture.event(True, 1, first)
        await fixture.until(lambda state: not state["delegate_transaction"]["pending"])
        first_source = next(message["source"] for message in fixture.messages
                            if message["t"] == "delegate_event")

        def malformed(ack):
            message = fixture.messages[-1]
            if message["t"] != "delegate_event" or message["source"] == first_source:
                return ack
            second_source = message["source"]
            return dict(ack, context_active=False, next_tick_ms=None,
                layer_ops=[{"op": "tg", "layer": 1, "source": first_source,
                            "row": 0, "col": 1, "is_press": True}],
                key_events=[
                    {"id": "shared-new-id", "action": "KC_B", "source": first_source,
                     "is_press": True, "delay_before_ms": 0},
                    {"id": "shared-new-id", "action": "KC_B", "source": second_source,
                     "is_press": False, "delay_before_ms": 0},
                ])

        fixture.ack_override = malformed
        await fixture.event(True, 1, second)
        try:
            report = await fixture.report(0.15)
        except TimeoutError:
            pass
        else:
            raise AssertionError(f"conflicting ACK emitted output before rejection: {report.hex()}")
        state = await fixture.request({"t": "owner_state"})
        assert state["delegate_transaction"]["last_error"], state
        assert not state["layer_state"]["toggled"], "invalid key batch partially committed its layer operation"
        assert state["pressed"] == 1, state
        await fixture.event(False)
        assert await fixture.report() == bytes(8)
        first[1].close()
        second[1].close()
        print("ok: new-ID conflict is rejected atomically across authorized sources")


async def delegate_cannot_release_native_layer():
    async with Fixture([{"0,0": "MO(1)", "0,1": "LT(1,KC_B)", "0,2": "KC_C"}, {}]) as fixture:
        await fixture.event(True)
        await fixture.until(lambda state: state["layer_state"]["momentary"] == [1])
        await fixture.event(True, 2)
        assert (await fixture.report())[2] == 6
        fixture.ack_override = lambda ack: dict(ack, context_active=False, next_tick_ms=None,
            key_events=[], layer_ops=[{"op": "mo", "layer": 1, "source": 0,
                                      "row": 0, "col": 0, "is_press": False}])
        await fixture.event(True, 1)
        state = await fixture.until(lambda state: bool(state["delegate_transaction"]["last_error"]))
        assert state["layer_state"]["momentary"] == [1], "ACK removed a native-held MO contribution"
        assert state["delegate_transaction"]["last_error"], state
        await fixture.quiet()
        await fixture.event(False, 2)
        assert await fixture.report() == bytes(8)
        await fixture.event(False)
        state = await fixture.until(lambda state: state["idle"])
        assert not state["layer_state"]["momentary"], state
        print("ok: malformed delegate MO release preserves the native layer/key owner")


async def main():
    await conflicting_new_id_is_atomic()
    await delegate_cannot_release_native_layer()


if __name__ == "__main__":
    asyncio.run(main())
