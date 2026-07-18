#!/usr/bin/env python3
"""Integration smoke for logicd PTY mirror routing through a real sessiond socket."""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.input_events import InputEventContext, handle_resolved_action  # noqa: E402
from logicd.logicd import _core_key_event_payload  # noqa: E402
from logicd.pty_mirror_runtime import PtyMirrorRuntime  # noqa: E402
from logicd.sessiond_client import SessiondPtyMirrorClient  # noqa: E402
from sessiond.sessiond import SessiondService  # noqa: E402


class RecordingMacros:
    def __init__(self) -> None:
        self.events: list[tuple[str, bool]] = []

    async def handle(self, action: str, is_press: bool) -> None:
        self.events.append((action, is_press))


def _ctx(mirror: PtyMirrorRuntime, macros: RecordingMacros) -> InputEventContext:
    return InputEventContext(
        layers=None,
        interactions=None,
        macros=macros,
        encoders=None,
        joysticks=None,
        pressed_matrix=set(),
        push_ledd_key_event=lambda *_args: None,
        push_ledd_status=lambda: None,
        push_i2cd_status=lambda: None,
        push_i2cd_alert=lambda *_args, **_kwargs: None,
        push_ledd_anim=lambda *_args: None,
        apply_lighting_key_action=lambda *_args: False,
        mouse_write_fn=lambda _report: None,
        pty_mirror=mirror,
    )


async def _drain_pty_output(ctx: InputEventContext) -> None:
    queue = ctx.pty_mirror_output_queue
    if queue is not None:
        await queue.join()


async def _wait_for_macro_event(
    ctx: InputEventContext,
    macros: RecordingMacros,
    event: tuple[str, bool],
    *,
    timeout: float = 3.0,
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        await _drain_pty_output(ctx)
        if event in macros.events:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"timed out waiting for PTY mirror event {event!r}: {macros.events!r}")


async def _wait_for_mirror_stop(mirror: PtyMirrorRuntime, *, timeout: float = 3.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if not mirror.active:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"timed out waiting for PTY mirror stop: {mirror.to_dict()!r}")


async def _run() -> None:
    with tempfile.TemporaryDirectory(prefix="logicd-sessiond-pty-mirror-") as tmpdir:
        socket_path = str(Path(tmpdir) / "sessiond.sock")
        service = SessiondService(socket_path)
        await service.start()
        server_task = asyncio.create_task(service.server.serve_forever())
        try:
            mirror = PtyMirrorRuntime(client=SessiondPtyMirrorClient(socket_path, read_timeout=1.5))
            macros = RecordingMacros()
            ctx = _ctx(mirror, macros)

            await handle_resolved_action("KC_SH7", True, ctx)
            assert mirror.active is True
            await _wait_for_macro_event(ctx, macros, ("KC_LANG2", True))

            for action in ("KC_P", "KC_W", "KC_D", "KC_ENTER"):
                await handle_resolved_action(action, True, ctx)
                await handle_resolved_action(action, False, ctx)
            await _drain_pty_output(ctx)
            assert mirror.text_plan_count >= 1
            assert any(action == "KC_ENTER" and is_press for action, is_press in macros.events)

            for action in ("KC_E", "KC_X", "KC_I", "KC_T", "KC_ENTER"):
                await handle_resolved_action(action, True, ctx)
                await handle_resolved_action(action, False, ctx)

            await _wait_for_mirror_stop(mirror)
            assert mirror.active is False
            assert mirror.last_reason == "exit:0"
            assert mirror.sent_key_actions >= 5
        finally:
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                pass
            await service.close()


def main() -> None:
    if sys.platform == "cygwin":
        print("skip: asyncio Unix socket client hangs on this Cygwin/MSYS runtime")
        return
    asyncio.run(_run())
    assert _core_key_event_payload("KC_A", True, None, "pty_terminal_mirror")["route"] == "us_sub_keyboard"
    assert "route" not in _core_key_event_payload("KC_A", True, None, "matrix")
    print("ok: logicd PTY mirror start/input/output path works through sessiond")


if __name__ == "__main__":
    main()
