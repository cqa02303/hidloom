#!/usr/bin/env python3
"""Real WebSocket/Unix-stream source lifetime checks without HID output."""
import asyncio
import contextlib
import importlib.util
import json
import logging
from pathlib import Path
import tempfile
import unittest

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("http_input_bridge", ROOT / "daemon/http/socket_bridge.py")
assert spec and spec.loader
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class WebInputLifetime(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="http-source-")
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "ctrl.sock")
        self.calls = []
        self.connections = []
        self.disconnected = asyncio.Event()
        self.reject_event = False
        self.drop_event_ack = False
        self.bad_open_ack = False
        self.lease_ms = 30000
        self.legacy = []

        async def owner(reader, writer):
            source = f"web-{len(self.connections)}"
            self.connections.append(writer)
            try:
                while line := await reader.readline():
                    value = json.loads(line)
                    self.calls.append((source, value))
                    response = {"result": "ok", "owner_epoch": "fixture-epoch"}
                    if value["t"] == "source_open":
                        response.update(source=source, lease_ms=self.lease_ms)
                        if self.bad_open_ack:
                            response.pop("owner_epoch")
                    if value["t"] == "source_event" and self.reject_event:
                        response = {"result": "error", "error": "fixture refusal"}
                    if value["t"] == "source_event" and self.drop_event_ack:
                        continue
                    writer.write(json.dumps(response).encode() + b"\n")
                    await writer.drain()
                    if value["t"] == "source_close":
                        break
            finally:
                writer.close()
                await writer.wait_closed()
                self.disconnected.set()

        self.owner = await asyncio.start_unix_server(owner, path=self.path)
        clients = set()
        async def legacy(raw):
            self.legacy.append(raw)
        async def handler(request):
            return await bridge.handle_ws_response(request, ws_clients=clients,
                process_message=legacy, source_socket_path=self.path, log=logging.getLogger("fixture"))
        app = web.Application()
        app.router.add_get("/ws", handler)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        for writer in self.connections:
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()
        self.owner.close()
        await self.owner.wait_closed()

    async def wait_calls(self, count):
        async with asyncio.timeout(2):
            while len(self.calls) < count:
                await asyncio.sleep(0.005)

    async def test_each_websocket_owns_connection_and_close(self):
        first = await self.client.ws_connect("/ws")
        second = await self.client.ws_connect("/ws")
        await first.send_str("P12")
        await second.send_json({"type": "keydown", "row": 1, "col": 2, "source": "physical", "action": "untrusted"})
        await self.wait_calls(4)
        await first.close()
        await self.wait_calls(5)
        self.assertFalse(second.closed)
        await second.send_str("R12")
        await self.wait_calls(6)
        await second.close()
        await self.wait_calls(7)
        events = [(source, value) for source, value in self.calls if value["t"] == "source_event"]
        self.assertEqual(len(events), 3)
        self.assertNotEqual(events[0][0], events[1][0])
        self.assertTrue(all(set(value) == {"t", "row", "col", "is_press"} for _, value in events))
        self.assertEqual(sum(v["t"] == "source_close" for _, v in self.calls), 2)
        self.assertEqual(self.legacy, [])

    async def test_owner_eof_closes_websocket_without_reconnect(self):
        ws = await self.client.ws_connect("/ws")
        await self.wait_calls(1)
        self.connections[0].close()
        await asyncio.wait_for(ws.receive(), 2)
        self.assertTrue(ws.closed)
        self.assertEqual(len(self.connections), 1)
        self.assertEqual(self.legacy, [])

    async def test_rejected_event_closes_and_never_replays(self):
        self.reject_event = True
        ws = await self.client.ws_connect("/ws")
        await ws.send_str("P12")
        await asyncio.wait_for(ws.receive(), 2)
        self.assertTrue(ws.closed)
        self.assertEqual(sum(v["t"] == "source_event" for _, v in self.calls), 1)
        self.assertEqual(len(self.connections), 1)

    async def test_idle_connection_renews_owner_lease(self):
        self.lease_ms = 3000
        ws = await self.client.ws_connect("/ws")
        await self.wait_calls(2)
        self.assertEqual([v["t"] for _, v in self.calls], ["source_open", "source_ping"])
        self.assertFalse(ws.closed)
        await ws.close()
        await self.wait_calls(3)
        self.assertEqual(self.calls[-1][1]["t"], "source_close")

    async def test_uncertain_event_ack_closes_without_replay(self):
        self.drop_event_ack = True
        ws = await self.client.ws_connect("/ws")
        await ws.send_str("P12")
        await asyncio.wait_for(ws.receive(), 5)
        self.assertTrue(ws.closed)
        await asyncio.wait_for(self.disconnected.wait(), 3)
        self.assertEqual(sum(v["t"] == "source_event" for _, v in self.calls), 1)
        self.assertEqual(len(self.connections), 1)

    async def test_invalid_open_ack_never_admits_input(self):
        self.bad_open_ack = True
        ws = await self.client.ws_connect("/ws")
        await ws.send_str("P12")
        await asyncio.wait_for(ws.receive(), 2)
        self.assertTrue(ws.closed)
        self.assertEqual([v["t"] for _, v in self.calls], ["source_open"])
        self.assertEqual(self.legacy, [])


if __name__ == "__main__":
    unittest.main()
