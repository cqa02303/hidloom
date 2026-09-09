#!/usr/bin/env python3
"""Real Python owner, explicit Unix session cleanup and ordered delegate ACKs."""
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "daemon"), str(ROOT)]
from logicd.hid_report import HidState
from logicd.macro import MacroExecutor
from logicd.keymap import LayerManager
from logicd.interaction_engine import InteractionEngine
from logicd.input_events import InputEventContext, process_matrix_event
from logicd.input_session import handle_source_session, invalidate_input_sessions, quiesce_input_sessions
from logicd.delegate_protocol import DelegateSession


def fixture():
    layers = LayerManager()
    layers.load([{"0,0": "KC_A", "0,1": "LT(1,KC_B)", "0,2": "MO(1)"},
                 {"0,0": "KC_C", "0,1": "LT(1,KC_B)", "0,2": "MO(1)"}])
    state, reports = HidState(), []
    context = InputEventContext(layers=layers, interactions=InteractionEngine(layers),
        macros=MacroExecutor(state, reports.append, {}),
        encoders=SimpleNamespace(handles=lambda *_: False), joysticks=None,
        pressed_matrix=set(), push_ledd_key_event=lambda *_: None,
        push_ledd_status=lambda: None, push_i2cd_status=lambda: None,
        push_i2cd_alert=lambda *_: None, push_ledd_anim=lambda *_: None,
        apply_lighting_key_action=lambda *_: False, mouse_write_fn=lambda *_: None,
        bt_manager=None, wifi_manager=None)
    return context, state, reports


async def main():
    ctx, state, reports = fixture()
    failures = []
    async def until(condition):
        for _ in range(50):
            if condition():
                return
            await asyncio.sleep(0.002)
        assert condition()
    async def accept(reader, writer):
        try:
            opening = json.loads(await reader.readline())
            assert opening == {"t": "source_open", "protocol": 1}
            await handle_source_session(reader, writer, context=lambda: ctx,
                matrix_in_range=lambda r,c: r == 0 and 0 <= c < 3, lease_seconds=0.15)
        except (asyncio.TimeoutError, ConnectionError, ValueError):
            pass
        except Exception as exc:
            failures.append(exc)
        finally:
            writer.close()
            await writer.wait_closed()
    async def request(reader, writer, message):
        writer.write(json.dumps(message).encode() + b"\n")
        await writer.drain()
        return json.loads(await reader.readline())
    with tempfile.TemporaryDirectory() as raw:
        path = str(Path(raw) / "ctrl.sock")
        server = await asyncio.start_unix_server(accept, path)
        async with server:
            first_r, first_w = await asyncio.open_unix_connection(path)
            second_r, second_w = await asyncio.open_unix_connection(path)
            first = await request(first_r, first_w, {"t":"source_open", "protocol":1})
            second = await request(second_r, second_w, {"t":"source_open", "protocol":1})
            assert first["source"] != second["source"]
            await process_matrix_event(("P",0,0), ctx)
            await request(first_r, first_w, {"t":"source_event", "row":0, "col":0, "is_press":True})
            ctx.layers.set_event_owner(None,None,None)
            ctx.layers.momentary_on(1)
            await request(second_r, second_w, {"t":"source_event", "row":0, "col":0, "is_press":True})
            await until(lambda:6 in state.build()[2:])
            assert 4 in state.build()[2:] and 6 in state.build()[2:]
            first_w.close()
            await first_w.wait_closed()
            for _ in range(20):
                if first["source"] not in ctx.pressed_matrix_owners:
                    break
                await asyncio.sleep(0.005)
            assert 4 in state.build()[2:] and 6 in state.build()[2:]
            await request(second_r, second_w, {"t":"source_close"})
            second_w.close()
            await second_w.wait_closed()
            assert 4 in state.build()[2:] and 6 not in state.build()[2:]
            await process_matrix_event(("R",0,0), ctx)
            assert state.build() == bytes(8)
            # Lease expiry owes release without a client close or R packet.
            reader, writer = await asyncio.open_unix_connection(path)
            await request(reader,writer,{"t":"source_open","protocol":1})
            await request(reader,writer,{"t":"source_event","row":0,"col":0,"is_press":True})
            await until(lambda:6 in state.build()[2:])
            assert 6 in state.build()[2:]
            await asyncio.sleep(0.20)
            assert state.build() == bytes(8)
            writer.close()
            await writer.wait_closed()
            # EOF is observed even while this source executes a long token macro.
            ctx.layers.set_event_owner(None,None,None)
            ctx.layers.momentary_off(1)
            await process_matrix_event(("P",0,0),ctx)
            ctx.layers.set_action(0,0,0,"MACRO:slow")
            ctx.macros._macros["slow"] = ["{KC_DOWN:KC_B}","{DELAY:60000}"]
            reader,writer = await asyncio.open_unix_connection(path)
            await request(reader,writer,{"t":"source_open","protocol":1})
            await request(reader,writer,{"t":"source_event","row":0,"col":0,"is_press":True})
            await until(lambda:5 in state.build()[2:])
            writer.close()
            await writer.wait_closed()
            await until(lambda:5 not in state.build()[2:])
            assert 4 in state.build()[2:]
            await process_matrix_event(("R",0,0),ctx)
            assert state.build() == bytes(8)
            # A context replacement invalidates old sessions before another P.
            reader,writer = await asyncio.open_unix_connection(path)
            await request(reader,writer,{"t":"source_open","protocol":1})
            old_state = state
            ctx,state,reports = fixture()
            ctx.layers.set_action(0,0,0,"KC_C")
            writer.write(b'{"t":"source_event","row":0,"col":0,"is_press":true}\n')
            await writer.drain()
            assert await reader.readline() == b""
            assert old_state.build() == state.build() == bytes(8)
            writer.close()
            await writer.wait_closed()
            reader,writer = await asyncio.open_unix_connection(path)
            await request(reader,writer,{"t":"source_open","protocol":1})
            await request(reader,writer,{"t":"source_event","row":0,"col":0,"is_press":True})
            await until(lambda:6 in state.build()[2:])
            invalidate_input_sessions()
            assert await reader.readline() == b""
            assert state.build() == bytes(8)
            writer.close()
            await writer.wait_closed()
            # Runtime replacement waits for old-source cleanup. Another physical
            # press made during that wait stays in the source-aware old state.
            reader,writer = await asyncio.open_unix_connection(path)
            await request(reader,writer,{"t":"source_open","protocol":1})
            await request(reader,writer,{"t":"source_event","row":0,"col":0,"is_press":True})
            await until(lambda:6 in state.build()[2:])
            releasing,allow_release,replaced = asyncio.Event(),asyncio.Event(),asyncio.Event()
            original_handle = ctx.macros.handle_owned
            async def gated_release(action,pressed,*,source):
                if action == "KC_C" and not pressed and str(source[0]).startswith("web:"):
                    releasing.set()
                    await allow_release.wait()
                await original_handle(action,pressed,source=source)
            ctx.macros.handle_owned = gated_release
            async def reload_owner():
                async with quiesce_input_sessions():
                    replaced.set()
            reload_task = asyncio.create_task(reload_owner())
            await releasing.wait()
            assert not replaced.is_set()
            ctx.layers.set_action(0,0,0,"KC_A")
            await process_matrix_event(("P",0,0),ctx)
            refused_r,refused_w = await asyncio.open_unix_connection(path)
            refusal = await request(refused_r,refused_w,{"t":"source_open","protocol":1})
            assert refusal["result"] == "error"
            refused_w.close()
            await refused_w.wait_closed()
            allow_release.set()
            await reload_task
            assert replaced.is_set() and 4 in state.build()[2:] and 6 not in state.build()[2:]
            assert await reader.readline() == b""
            writer.close()
            await writer.wait_closed()
            # A new source has no old finalizer left that could erase its press.
            reader,writer = await asyncio.open_unix_connection(path)
            await request(reader,writer,{"t":"source_open","protocol":1})
            await request(reader,writer,{"t":"source_event","row":0,"col":0,"is_press":True})
            await asyncio.sleep(0.01)
            assert 4 in state.build()[2:]
            await request(reader,writer,{"t":"source_close"})
            writer.close()
            await writer.wait_closed()
            assert 4 in state.build()[2:]
            await process_matrix_event(("R",0,0),ctx)
            assert state.build() == bytes(8)
    assert not failures, failures

    # Same layer holds from different sources: removing one retains the other.
    ctx, state, reports = fixture()
    await process_matrix_event(("P",0,2), ctx, owner="one")
    await process_matrix_event(("P",0,2), ctx, owner="two")
    await process_matrix_event(("R",0,2), ctx, owner="one")
    assert ctx.layers.active_snapshot()["momentary"] == [1]
    await process_matrix_event(("R",0,2), ctx, owner="two")
    assert ctx.layers.active_snapshot()["momentary"] == []

    # Real InteractionEngine LT is driven by native time and acknowledged ops.
    ctx, _, _ = fixture()
    delegate = DelegateSession(lambda: ctx)
    sequence = 0
    async def delegated(kind="delegate_event", **fields):
        nonlocal sequence
        sequence += 1
        return await delegate.process({"t":kind,"protocol":2,"event_id":sequence,
            "owner_epoch":"fixture", "keymap_revision":1,"layer_revision":1,
            "source":0,"row":0,"col":1,"is_press":True,"action":"LT(1,KC_B)",
            "layers":ctx.layers.layers_snapshot(),"layer_state":{"default":0,"momentary":[],"toggled":[],"oneshot":[]},
            "now_ms":0, **fields})
    ack = await delegated()
    assert ack["context_active"] and ack["key_events"] == []
    ack = await delegated("delegate_tick", now_ms=250)
    assert any(op["op"] == "mo" and op["source"] == 0 and op["col"] == 1 for op in ack["layer_ops"])
    assert ctx.core_key_event_owned_fn is None
    await delegated("delegate_source_end", now_ms=260)
    assert not ctx.interactions.pressed
    # Short LT produces a scheduled 60ms tap, no wall-time sleep in ACK creation.
    await delegated(now_ms=1000)
    ack = await delegated(is_press=False, now_ms=1010)
    assert [(e["action"], e["is_press"], e["delay_before_ms"]) for e in ack["key_events"]] == [("KC_B",True,0),("KC_B",False,60)]
    async def failed_macro(action, pressed):
        if pressed:
            raise RuntimeError("fixture rejected macro output")
    ctx.macros = SimpleNamespace(handle=failed_macro)
    await delegated(col=0, action="MACRO:failure", now_ms=2000)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    ack = await delegated("delegate_tick",now_ms=2010)
    assert ack["companion_error"] == "macro output failed: RuntimeError"
    await delegated(is_press=False,col=0,now_ms=2020)
    canceled = asyncio.Event()
    async def long_macro(action, pressed):
        if pressed:
            try:
                await asyncio.Event().wait()
            finally:
                canceled.set()
    ctx.macros = SimpleNamespace(handle=long_macro)
    await delegated(col=0,action="MACRO:long",now_ms=3000)
    await asyncio.sleep(0)
    await delegated(owner_epoch="new-owner",col=0,action="KC_A",now_ms=0)
    assert canceled.is_set(), "old epoch macro must terminate before new owner output"

    # A superseded stream's EOF cannot erase the newer stream's source state.
    ctx, _, _ = fixture()
    delegate = DelegateSession(lambda:ctx)
    with tempfile.TemporaryDirectory() as raw:
        socket = str(Path(raw)/"delegate.sock")
        listener = await asyncio.start_unix_server(delegate.handle_client,path=socket)
        async with listener:
            old_r,old_w = await asyncio.open_unix_connection(socket)
            envelope = {"t":"delegate_event","protocol":2,"event_id":1,"owner_epoch":"stream-owner",
                "keymap_revision":1,"layer_revision":1,"source":0,"row":0,"col":0,"is_press":True,
                "action":"KC_A","now_ms":0,"layers":ctx.layers.layers_snapshot(),
                "layer_state":{"default":0,"momentary":[],"toggled":[],"oneshot":[]}}
            await request(old_r,old_w,envelope)
            new_r,new_w = await asyncio.open_unix_connection(socket)
            await request(new_r,new_w,{**envelope,"event_id":2,"source":1})
            old_w.close()
            await old_w.wait_closed()
            await asyncio.sleep(0.01)
            assert ("1",0,0) in ctx.interactions.pressed
            new_w.close()
            await new_w.wait_closed()
            await asyncio.sleep(0.01)
            assert not ctx.interactions.pressed
    print("control owner sessions: ok")


if __name__ == "__main__":
    asyncio.run(main())
