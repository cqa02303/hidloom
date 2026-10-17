#!/usr/bin/env python3
"""Actual WebSocket bridge -> companion session tunnel -> native input owner."""
import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "daemon"), str(ROOT / "script"), str(ROOT)]
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from logicd import logicd
from test_http_input_session import bridge
from test_native_owner_protocol import Fixture


async def main():
    async with Fixture([{"0,0":"KC_A","0,1":"MO(1)"}, {"0,0":"KC_C"}]) as fixture:
        prior = logicd.CORE_KEY_EVENT_CTRL_SOCKET
        logicd.CORE_KEY_EVENT_CTRL_SOCKET = str(fixture.ctrl)
        path = str(fixture.root / "companion.sock")
        companion = await asyncio.start_unix_server(logicd._handle_ctrl_client, path)
        clients, legacy = set(), []
        async def old_send(raw):
            legacy.append(raw)
        async def handler(request):
            return await bridge.handle_ws_response(request, ws_clients=clients, process_message=old_send,
                source_socket_path=path, log=logging.getLogger("fixture"))
        app = web.Application()
        app.router.add_get("/ws", handler)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            first = await client.ws_connect("/ws")
            second = await client.ws_connect("/ws")
            await fixture.event(True)
            assert (await fixture.report())[2] == 4
            await first.send_json({"type":"keydown","row":0,"col":0})
            await fixture.until(lambda state: state["pressed"] >= 2)
            # Physical MO changes the action at the same coordinate for web2.
            await fixture.event(True,1)
            await second.send_json({"type":"keydown","row":0,"col":0})
            report = await fixture.report()
            assert 4 in report[2:] and 6 in report[2:]
            await first.close()
            await fixture.quiet()
            # Abrupt HTTP-side IPC death releases web2 while physical A survives.
            for ws in list(clients):
                await ws.close()
            report = await fixture.report()
            assert 4 in report[2:] and 6 not in report[2:]
            await fixture.event(False,1)
            await fixture.event(False)
            assert await fixture.report() == bytes(8)
            assert legacy == []
            assert second.closed or (await second.receive()).type in {web.WSMsgType.CLOSE, web.WSMsgType.CLOSED}
        finally:
            await client.close()
            companion.close()
            await companion.wait_closed()
            logicd.CORE_KEY_EVENT_CTRL_SOCKET = prior
    print("HTTP native input session: ok")


if __name__ == "__main__":
    asyncio.run(main())
