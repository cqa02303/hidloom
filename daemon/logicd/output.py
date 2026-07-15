"""HID output queue helpers and compatibility exports for logicd.

``process_key_event_output`` owns the key state transition and builds the
8-byte keyboard HID report.  The actual destination is intentionally hidden
behind ``get_write_fn()`` so the writer can be the legacy auto switch or the
new OutputRouter fan-out writer.

Output selection policy:
- Do not add backend-specific branches here.
- Choose enabled outputs with ``LOGICD_OUTPUTS`` / ``settings.outputs``.
- Use ``LOGICD_OUTPUTS=debug`` for debug-only logging.
- Use ``LOGICD_OUTPUTS=gadget,uinput,debug,bt`` for simultaneous fan-out.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from .hid_report import HidState
from .output_switch import create_dynamic_write_fn, new_hid_write_fn, with_hid_report_id
from .uinput import create_uinput_write_fn, make_consumer_fn, make_consumer_report_fn

log = logging.getLogger(__name__)


async def process_key_event_output(
    queue: asyncio.Queue,
    state: HidState,
    get_write_fn: Callable[[], Callable[[bytes], None]],
) -> None:
    """Consume confirmed key events and send keyboard HID reports to writer.

    Design intent:
    this layer should only convert key events into the canonical keyboard HID
    report. Fan-out, debug logging, gadget/uinput/bt selection, and connection
    on/off handling belong to the writer behind ``get_write_fn()``.
    """
    while True:
        item = await queue.get()
        try:
            if item is None:
                report = state.build()
                get_write_fn()(report)
                log.debug("Output (internal): state=%s", report.hex())
            else:
                keycode, modifier, is_press = item
                if is_press:
                    state.press(keycode)
                    state.set_mod_bits(modifier)
                else:
                    state.release(keycode)
                    state.clear_mod_bits(modifier)
                report = state.build()
                get_write_fn()(report)
                log.debug(
                    "Output (external): keycode=0x%02x modifier=0x%02x press=%s",
                    keycode, modifier, is_press,
                )
        except Exception:
            log.exception("Error in output_processor: item=%r", item)
        finally:
            queue.task_done()


async def async_hid_init(hid_fd, write_fn: Callable[[bytes], None]) -> None:
    """Send an initial null report without blocking daemon startup."""
    try:
        log.info("Initializing HID device asynchronously...")
        await asyncio.sleep(0.1)
        if hid_fd is not None and write_fn is not None:
            write_fn(HidState.null_report())
            log.info("HID device initialized successfully")
    except Exception as exc:
        log.warning("HID initialization failed (non-critical): %s", exc)


async def usb_monitor_loop(get_write_fn: Callable[[], Callable[[bytes], None]], interval: float = 1.0) -> None:
    """Periodically ask the active writer to refresh connection state."""
    while True:
        await asyncio.sleep(interval)
        try:
            fn = getattr(get_write_fn(), "check_and_switch", None)
            if fn is not None:
                fn()
        except Exception as exc:
            log.debug("USB monitor error (non-critical): %s", exc)
