from __future__ import annotations

import asyncio
import unittest

from logicd.hid_report import HidState
from logicd.output import process_key_event_output


async def _run_processor_once(queue: asyncio.Queue, state: HidState, get_write_fn) -> None:
    task = asyncio.create_task(process_key_event_output(queue, state, get_write_fn))
    try:
        await queue.join()
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


class KeyEventOutputTest(unittest.IsolatedAsyncioTestCase):
    async def test_output_processor_builds_report_and_calls_writer(self) -> None:
        queue: asyncio.Queue = asyncio.Queue()
        state = HidState()
        writes: list[bytes] = []

        def get_write_fn():
            def write(report: bytes) -> None:
                writes.append(report)
            return write

        await queue.put((0x04, 0x00, True))

        await _run_processor_once(queue, state, get_write_fn)

        self.assertEqual(
            writes,
            [bytes([0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00])],
        )

    async def test_output_processor_updates_state_for_press_and_release(self) -> None:
        queue: asyncio.Queue = asyncio.Queue()
        state = HidState()
        writes: list[bytes] = []

        def get_write_fn():
            def write(report: bytes) -> None:
                writes.append(report)
            return write

        await queue.put((0x04, 0x02, True))
        await queue.put((0x04, 0x02, False))

        await _run_processor_once(queue, state, get_write_fn)

        self.assertEqual(
            writes,
            [
                bytes([0x02, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00]),
                HidState.null_report(),
            ],
        )
        self.assertEqual(state.build(), HidState.null_report())


if __name__ == "__main__":
    unittest.main()
