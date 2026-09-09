#!/usr/bin/env python3
"""MCP guard/CAS through real Python ctrl coordinator and real native owner."""
import asyncio
import functools
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "daemon"), str(ROOT / "script"), str(ROOT)]
from dev.mcp.keyboard_write import server as mcp
from logicd.ctrl import process_ctrl_json
from logicd.keymap_coordinator import KeymapCoordinator
from test_native_owner_protocol import Fixture


async def main():
    async with Fixture([{"0,0":"KC_A","0,1":"KC_B"}], delegate=False) as f:
        keymap = f.root / "keymap.json"
        keymap.write_text(json.dumps({"_layout_def":{"matrix":[[0,0,"SW00"],[0,1,"SW01"]]},
                                     "layers":[{"matrix":["KC_A","KC_B"]}]}))
        default = f.root / "defaults.json"
        default.write_bytes(keymap.read_bytes())
        coordinator = KeymapCoordinator(f.ctx.layers, keymap, default,
            lambda r,c:r == 0 and 0 <= c < 2, native_request=f.request)
        context = SimpleNamespace(keymap_coordinator=coordinator, layers=f.ctx.layers,
            pressed_matrix=set(), current_hid_mode="usb",current_output_target="auto")
        async def handler(reader,writer):
            try:
                while line := await reader.readline():
                    await process_ctrl_json(line.decode(), context, writer)
            finally:
                writer.close()
                await writer.wait_closed()
        socket = f.root / "companion.sock"
        ctrl = await asyncio.start_unix_server(handler,path=str(socket))
        query = functools.partial(mcp._query_ctrl,socket_path=socket)
        async with ctrl:
            plan = await asyncio.to_thread(mcp.plan_key_tap,0,0,keymap_path=keymap,query_ctrl=query)
            assert plan["ok"], plan
            def dropped(command):
                result = query(command)
                if command["t"] == "GUARDED_TAP":
                    raise OSError("fixture response dropped after owner acceptance")
                return result
            result = await asyncio.to_thread(mcp.send_key_tap,0,0,expected_sha256=plan["keymap_sha256"],
                confirm=plan["confirmation_phrase"],keymap_path=keymap,query_ctrl=dropped)
            assert result["ok"], result
            assert (await f.report())[2] == 4
            assert await f.report() == bytes(8)
            retry = await asyncio.to_thread(mcp.send_key_tap,0,0,expected_sha256=plan["keymap_sha256"],
                confirm=plan["confirmation_phrase"],keymap_path=keymap,query_ctrl=query)
            assert retry["ok"] and retry["owner_result"]["state"] == "released", retry
            await f.quiet()
            # Fresh confirmation authorizes another tap; replaying one does not.
            fresh = await asyncio.to_thread(mcp.plan_key_tap,0,0,keymap_path=keymap,query_ctrl=query)
            assert fresh["confirmation_phrase"] != plan["confirmation_phrase"]
            async def drop_owner_ack(command):
                response = await f.request(command)
                if command["t"] == "guarded_tap":
                    raise OSError("fixture owner ACK lost inside coordinator")
                return response
            coordinator.native_request = drop_owner_ack
            second = await asyncio.to_thread(mcp.send_key_tap,0,0,expected_sha256=fresh["keymap_sha256"],
                confirm=fresh["confirmation_phrase"],keymap_path=keymap,query_ctrl=query)
            assert second["ok"], second
            assert (await f.report())[2] == 4
            assert await f.report() == bytes(8)
            async def unknown_owner_outcome(command):
                if command["t"] == "operation_status":
                    raise OSError("fixture owner result unavailable")
                return await drop_owner_ack(command)
            coordinator.native_request = unknown_owner_outcome
            uncertain_plan = await asyncio.to_thread(mcp.plan_key_tap,0,0,keymap_path=keymap,query_ctrl=query)
            unknown = await asyncio.to_thread(mcp.send_key_tap,0,0,expected_sha256=uncertain_plan["keymap_sha256"],
                confirm=uncertain_plan["confirmation_phrase"],keymap_path=keymap,query_ctrl=query)
            assert not unknown["ok"] and unknown["executed"] is None, unknown
            assert (await f.report())[2] == 4
            assert await f.report() == bytes(8)
            coordinator.native_request = f.request

            # One confirmed remap uses compare/apply/persist, no M+S race window.
            change = await asyncio.to_thread(mcp.plan_keymap_change,0,0,0,"KC_C",keymap_path=keymap,query_ctrl=query)
            assert change["ok"], change
            applied = await asyncio.to_thread(mcp.apply_keymap_change,0,0,0,"KC_C",expected_sha256=change["keymap_sha256"],
                confirm=change["confirmation_phrase"],keymap_path=keymap,query_ctrl=query)
            assert applied["ok"], applied
            await f.event(True)
            assert (await f.report())[2] == 6
            await f.event(False)
            assert await f.report() == bytes(8)
            # Confirmed old owner revisions cannot authorize a later map.
            stale = await asyncio.to_thread(mcp.send_key_tap,0,0,expected_sha256=plan["keymap_sha256"],
                confirm=plan["confirmation_phrase"],keymap_path=keymap,query_ctrl=query)
            assert not stale["ok"]
            await f.quiet()
            await coordinator.execute({"t":"M","l":0,"r":0,"c":0,"a":"KC_D"})
            pending = await asyncio.to_thread(mcp.plan_key_tap,0,0,keymap_path=keymap,query_ctrl=query)
            assert not pending["ok"] and "owner_save_pending" in pending["blockers"]
            assert (await coordinator.execute({"t":"S"}))["result"] == "ok"
            # Independent owner/companion disagreement is refused with no input.
            f.ctx.layers.set_action(0,0,0,"KC_A")
            mismatch = await asyncio.to_thread(mcp.plan_key_tap,0,0,keymap_path=keymap,query_ctrl=query)
            assert not mismatch["ok"] and "executing_owner_unavailable" in mismatch["blockers"]
            await f.quiet()
    print("MCP native owner: ok")


if __name__ == "__main__":
    asyncio.run(main())
