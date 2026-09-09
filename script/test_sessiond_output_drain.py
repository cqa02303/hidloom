#!/usr/bin/env python3
"""PTY output completion regressions; synthetic local children and sockets only."""
from __future__ import annotations

import asyncio
import errno
import json
import os
from pathlib import Path
import shlex
import signal
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "daemon"), str(ROOT)]
from sessiond.pty_mirror import PtyMirrorSession
from sessiond.sessiond import SessiondService
from logicd.sessiond_client import SessiondPtyMirrorClient
from logicd.input_events import _handle_pty_mirror_background_stop


def command_for(payload: bytes, stderr: bytes = b"") -> str:
    source = f"import os; os.write(1, {payload!r}); os.write(2, {stderr!r})"
    return shlex.join([sys.executable, "-c", source])


class CaptureWriter:
    def __init__(self):
        self.messages = []

    def write(self, data):
        self.messages.append(json.loads(data))

    async def drain(self):
        pass


class OutputDrainTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="sessiond-drain-")
        self.service = SessiondService(str(Path(self.tmp.name) / "session.sock"))

    async def asyncTearDown(self):
        await self.service.close()
        self.tmp.cleanup()

    async def exited_session(self, payload=b"last stdout", stderr=b"last stderr"):
        session = PtyMirrorSession(command_for(payload, stderr))
        session.start()
        self.service.session = session
        self.service.seen_session = True
        assert await asyncio.to_thread(session.wait, timeout=2) == 0
        return session

    def assert_complete(self, messages, expected):
        text = "".join(m.get("text", "") for m in messages)
        self.assertEqual(text, expected)
        exits = [i for i, m in enumerate(messages) if m.get("active") is False]
        self.assertEqual(exits, [len(messages) - 1], messages)
        self.assertEqual(messages[-1]["reason"], "exit:0")
        self.assertIsNone(self.service.session)

    async def test_poll_after_child_exit(self):
        session = await self.exited_session()
        messages = []
        for _ in range(40):
            messages.extend(await self.service.process_message({"type": "poll_pty_output", "max_bytes": 4}))
            if messages[-1].get("active") is False:
                break
        self.assert_complete(messages, "last stdoutlast stderr")
        self.assertIsNone(session.master_fd)

    async def test_status_input_and_start_preserve_draining_output(self):
        session = await self.exited_session()
        status = (await self.service.process_message({"type": "pty_status"}))[0]
        self.assertTrue(status["active"])
        self.assertFalse(status["process_active"])
        self.assertTrue(status["draining"])
        denied = (await self.service.process_message({"type": "pty_key_input", "action": "KC_A"}))[0]
        self.assertTrue(denied["active"])
        self.assertEqual(denied["reason"], "draining")
        again = (await self.service.process_message({"type": "start_pty_mirror", "command": "false"}))[0]
        self.assertEqual(again["reason"], "already_active")
        self.assertIs(self.service.session, session)
        writer = CaptureWriter()
        await asyncio.wait_for(self.service.watch_output({"max_bytes": 3}, writer), 2)
        self.assert_complete(writer.messages, "last stdoutlast stderr")

    async def test_watch_large_output_and_utf8_boundaries(self):
        expected = "head:" + "aé漢🙂" * 5000 + ":stderr終"
        source = f"import os; os.write(1, b'head:' + {'aé漢🙂'.encode()!r} * 5000); os.write(2, {':stderr終'.encode()!r})"
        session = PtyMirrorSession(shlex.join([sys.executable, "-c", source]))
        session.start()
        self.service.session = session
        writer = CaptureWriter()
        await asyncio.wait_for(self.service.watch_output({"max_bytes": 127, "interval_ms": 5}, writer), 10)
        self.assert_complete(writer.messages, expected)

    async def test_legacy_client_receives_final_text_before_exit(self):
        expected = "tailé漢🙂"
        await self.exited_session(expected.encode(), b"")
        await self.service.start()
        client = SessiondPtyMirrorClient(socket_path=self.service.socket_path)
        seen = []
        await asyncio.wait_for(client.watch_output(lambda result: seen.extend(result["responses"]), max_bytes=1), 3)
        self.assert_complete(seen, expected)

    async def test_would_block_and_errors_are_distinct_from_eof(self):
        session = await self.exited_session(b"x", b"")
        with patch("sessiond.pty_mirror.select.select", return_value=([session.master_fd], [], [])):
            for code in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR):
                with patch("sessiond.pty_mirror.os.read", side_effect=OSError(code, "synthetic")):
                    result = session.read_available_result()
                    self.assertEqual(result.data, b"")
                    self.assertFalse(result.eof)
                    self.assertFalse(session.output_eof)
            with patch("sessiond.pty_mirror.os.read", side_effect=OSError(errno.EBADF, "synthetic")):
                with self.assertRaises(OSError):
                    session.read_available_result()
            with patch("sessiond.pty_mirror.os.read", side_effect=OSError(errno.EIO, "synthetic")):
                self.assertTrue(session.read_available_result().eof)

    async def test_stop_can_discard_pending_output(self):
        session = await self.exited_session()
        result = await self.service.process_message({"type": "stop_pty_mirror", "reason": "operator_escape"})
        self.assertFalse(result[0]["active"])
        self.assertEqual(result[0]["reason"], "operator_escape")
        self.assertIsNone(session.master_fd)

    async def test_status_preserves_partial_utf8_decoder_tail(self):
        await self.exited_session(b"\xe6", b"")
        result = await self.service.poll_output({"max_bytes": 1})
        self.assertTrue(result[0]["active"])
        status = await self.service.process_message({"type": "pty_status"})
        self.assertTrue(status[0]["active"])
        final = await self.service.poll_output({"max_bytes": 1})
        self.assert_complete(final, "\ufffd")

    async def test_parent_exit_with_open_slave_stays_draining_until_stop(self):
        source = """import os, signal, time
read_fd, write_fd = os.pipe()
pid = os.fork()
if pid == 0:
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    os.close(read_fd)
    os.write(write_fd, b'x')
    time.sleep(30)
    os._exit(0)
os.close(write_fd)
os.read(read_fd, 1)
"""
        session = PtyMirrorSession(shlex.join([sys.executable, "-c", source]))
        session.start()
        self.service.session = session
        pgid = session.process.pid
        try:
            self.assertEqual(await asyncio.to_thread(session.wait, timeout=2), 0)
            status = await self.service.process_message({"type": "pty_status"})
            self.assertTrue(status[0]["draining"])
            self.assertFalse(session.read_available_result().eof)
            self.service.stop_session("operator_escape")
            self.assertIsNone(session.master_fd)
        finally:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    async def test_natural_exit_drains_client_output_queue_before_cleanup(self):
        queue = asyncio.Queue()
        entered, release = asyncio.Event(), asyncio.Event()
        seen = []
        await queue.put("last text plan")

        async def dispatch():
            item = await queue.get()
            try:
                entered.set()
                await release.wait()
                seen.append(item)
            finally:
                queue.task_done()

        worker = asyncio.create_task(dispatch())
        mirror = SimpleNamespace(active=False, output_dispatch_queue=queue, output_dispatch_task=worker)
        ctx = SimpleNamespace(pty_mirror=mirror, pty_mirror_output_queue=queue, pty_mirror_output_task=worker,
                              pty_mirror_release_output=lambda: seen.append("released"), push_i2cd_alert=None)
        await entered.wait()
        finish = asyncio.create_task(_handle_pty_mirror_background_stop(ctx, mirror, {"reason": "exit:0"}))
        await asyncio.sleep(0)
        self.assertFalse(finish.done())
        self.assertFalse(worker.cancelled())
        release.set()
        await asyncio.wait_for(finish, 2)
        self.assertEqual(seen, ["last text plan", "released"])


if __name__ == "__main__":
    unittest.main()
