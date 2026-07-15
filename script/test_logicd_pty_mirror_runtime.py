#!/usr/bin/env python3
"""Regression tests for logicd PTY mirror runtime routing."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.input_events import InputEventContext, handle_resolved_action  # noqa: E402
import logicd.pty_mirror_output_runner as output_runner  # noqa: E402
from logicd.pty_mirror_output_runner import (  # noqa: E402
    PTY_MIRROR_OUTPUT_YIELD_EVERY_TAPS,
    _dispatch_tap,
    dispatch_pty_mirror_text_plans,
)
from logicd.pty_mirror_runtime import PtyMirrorRuntime  # noqa: E402
from logicd.pty_terminal_text import key_action_to_text_char  # noqa: E402


class FakeClient:
    def __init__(self) -> None:
        self.actions: list[tuple[str, bool, tuple[str, ...]]] = []
        self.starts: list[dict] = []
        self.stops: list[dict] = []

    async def start(self, **_kwargs):
        self.starts.append(dict(_kwargs))
        return {
            "ok": True,
            "responses": [{"type": "pty_status", "active": True}],
            "text_plans": [
                {
                    "available": True,
                    "taps": [{"type": "tap", "key": "KC_C", "modifiers": []}],
                    "command": "wsl bash -lc prompt",
                }
            ],
        }

    async def stop(self, **_kwargs):
        self.stops.append(dict(_kwargs))
        return {"ok": True, "responses": [{"type": "pty_status", "active": False}], "text_plans": []}

    async def poll_output(self, **_kwargs):
        return {"ok": True, "responses": [{"type": "pty_status", "active": True, "reason": "poll"}], "text_plans": []}

    def build_text_plans_for_stream(self, text: str):
        return [{"available": True, "taps": [{"type": "tap", "key": "KC_T", "modifiers": []}], "text": text}]

    async def send_key_action(self, action: str, *, is_press: bool = True, modifiers=None):
        self.actions.append((action, is_press, tuple(modifiers or ())))
        responses = [{"type": "pty_status", "active": False, "reason": "exit:0"}] if action == "KC_ENTER" else []
        if action == "KC_C" and "KC_LCTRL" in tuple(modifiers or ()):
            responses = [
                {
                    "type": "pty_status",
                    "active": True,
                    "reason": "interrupt",
                    "clear_output_queue": True,
                    "output_discarded": True,
                }
            ]
        text_plans = []
        if action == "KC_A":
            text_plans = [
                {
                    "available": True,
                    "taps": [{"type": "tap", "key": "KC_B", "modifiers": []}],
                    "command": "wsl bash -lc test",
                }
            ]
        if action == "KC_U":
            text_plans = [
                {
                    "available": False,
                    "blocking_reasons": ["unsupported_pty_terminal_host_profile"],
                    "taps": [],
                }
            ]
        return {
            "ok": True,
            "responses": responses,
            "text_plans": text_plans,
        }


class WatchOutputClient(FakeClient):
    async def watch_output(self, on_result, **_kwargs):
        await asyncio.sleep(0)
        result = {
            "ok": True,
            "responses": [{"type": "pty_text_stream"}],
            "text_plans": [
                {
                    "available": True,
                    "taps": [{"type": "tap", "key": "KC_P", "modifiers": []}],
                    "command": "watch prompt",
                }
            ],
        }
        callback_result = on_result(result)
        if asyncio.iscoroutine(callback_result):
            await callback_result
        while True:
            await asyncio.sleep(1.0)


class WatchExitClient(FakeClient):
    async def watch_output(self, on_result, **_kwargs):
        await asyncio.sleep(0)
        result = {
            "ok": True,
            "responses": [{"type": "pty_status", "active": False, "reason": "exit:130"}],
            "text_plans": [],
        }
        callback_result = on_result(result)
        if asyncio.iscoroutine(callback_result):
            await callback_result


class DisplayFakeClient(FakeClient):
    host_profile = "windows_text_editor_us_sub_keyboard"


class RecordingMacros:
    def __init__(self) -> None:
        self.events: list[tuple[str, bool]] = []
        self.alerts: list[tuple] = []

    async def handle(self, action: str, is_press: bool) -> None:
        self.events.append((action, is_press))


class FailingMacros(RecordingMacros):
    async def handle(self, action: str, is_press: bool) -> None:
        self.events.append((action, is_press))
        if action == "KC_A" and is_press:
            raise RuntimeError("synthetic press failed")


class FailingKeyMacros(RecordingMacros):
    def __init__(self, failing_action: str) -> None:
        super().__init__()
        self.failing_action = failing_action

    async def handle(self, action: str, is_press: bool) -> None:
        self.events.append((action, is_press))
        if action == self.failing_action and is_press:
            raise RuntimeError(f"synthetic {action} press failed")


class RaisingClient:
    async def start(self, **_kwargs):
        raise RuntimeError("start exploded")

    async def stop(self, **_kwargs):
        raise RuntimeError("stop exploded")

    async def send_key_action(self, *_args, **_kwargs):
        raise RuntimeError("send exploded")


class InterruptStatusOnlyClient(FakeClient):
    async def send_key_action(self, action: str, *, is_press: bool = True, modifiers=None):
        self.actions.append((action, is_press, tuple(modifiers or ())))
        if action == "KC_C" and "KC_LCTRL" in tuple(modifiers or ()):
            return {
                "ok": True,
                "responses": [{"type": "pty_status", "active": True, "reason": "interrupt"}],
                "text_plans": [],
            }
        return await super().send_key_action(action, is_press=is_press, modifiers=modifiers)


class ExitWithTextPlanClient(FakeClient):
    async def send_key_action(self, action: str, *, is_press: bool = True, modifiers=None):
        self.actions.append((action, is_press, tuple(modifiers or ())))
        if action == "KC_ENTER":
            return {
                "ok": True,
                "responses": [{"type": "pty_status", "active": False, "reason": "exit:0"}],
                "text_plans": [
                    {
                        "available": True,
                        "taps": [{"type": "tap", "key": "KC_D", "modifiers": []}],
                        "command": "final prompt tail",
                    }
                ],
            }
        return await super().send_key_action(action, is_press=is_press, modifiers=modifiers)


class ClearQueueResponseClient(FakeClient):
    async def send_key_action(self, action: str, *, is_press: bool = True, modifiers=None):
        self.actions.append((action, is_press, tuple(modifiers or ())))
        if action == "KC_L":
            return {
                "ok": True,
                "responses": [{"type": "pty_text_stream", "clear_output_queue": True}],
                "text_plans": [
                    {
                        "available": True,
                        "taps": [{"type": "tap", "key": "KC_E", "modifiers": []}],
                        "command": "clear and redraw",
                    }
                ],
            }
        return await super().send_key_action(action, is_press=is_press, modifiers=modifiers)


class PreCancelInspectingInterruptClient(FakeClient):
    def __init__(self, ctx: InputEventContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.output_was_cleared_before_send = False

    async def send_key_action(self, action: str, *, is_press: bool = True, modifiers=None):
        if action == "KC_C" and "KC_LCTRL" in tuple(modifiers or ()):
            queue = getattr(self.ctx.pty_mirror, "output_dispatch_queue", None) or self.ctx.pty_mirror_output_queue
            task = getattr(self.ctx.pty_mirror, "output_dispatch_task", None) or self.ctx.pty_mirror_output_task
            self.output_was_cleared_before_send = (
                task is None
                and (queue is None or queue.empty())
            )
        return await super().send_key_action(action, is_press=is_press, modifiers=modifiers)


class InterruptWithPromptClient(FakeClient):
    async def send_key_action(self, action: str, *, is_press: bool = True, modifiers=None):
        self.actions.append((action, is_press, tuple(modifiers or ())))
        if action == "KC_C" and "KC_LCTRL" in tuple(modifiers or ()):
            return {
                "ok": True,
                "responses": [
                    {
                        "type": "pty_text_stream",
                        "text": "\r\npi@<keyboard-host>:~/hidloom $ ",
                    },
                    {
                        "type": "pty_status",
                        "active": True,
                        "reason": "interrupt",
                        "clear_output_queue": True,
                        "output_discarded": True,
                    },
                ],
                "text_plans": [
                    {
                        "available": True,
                        "taps": [{"type": "tap", "key": "KC_P", "modifiers": []}],
                        "text": "\r\npi@<keyboard-host>:~/hidloom $ ",
                    }
                ],
            }
        return await super().send_key_action(action, is_press=is_press, modifiers=modifiers)


def _ctx(
    mirror: PtyMirrorRuntime,
    macros: RecordingMacros,
    *,
    prepare_output=None,
    set_capture=None,
    release_output=None,
) -> InputEventContext:
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
        push_i2cd_alert=lambda *args, **kwargs: macros.alerts.append((*args, kwargs)),
        push_ledd_anim=lambda *_args: None,
        apply_lighting_key_action=lambda *_args: False,
        mouse_write_fn=lambda _report: None,
        pty_mirror=mirror,
        pty_mirror_prepare_output=prepare_output,
        pty_mirror_set_capture=set_capture,
        pty_mirror_release_output=release_output,
    )


async def _drain_pty_output(ctx: InputEventContext) -> None:
    queue = getattr(ctx.pty_mirror, "output_dispatch_queue", None) or ctx.pty_mirror_output_queue
    if queue is not None:
        await queue.join()


async def _cancel_pty_output_for_test(ctx: InputEventContext) -> None:
    task = getattr(ctx.pty_mirror, "output_dispatch_task", None) or ctx.pty_mirror_output_task
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    ctx.pty_mirror.output_dispatch_task = None
    ctx.pty_mirror.output_dispatch_queue = None
    ctx.pty_mirror_output_task = None
    ctx.pty_mirror_output_queue = None


def _seed_pending_pty_output(ctx: InputEventContext, key: str = "KC_A") -> None:
    queue = asyncio.Queue()
    queue.put_nowait([{"available": True, "taps": [{"key": key}]}])
    task = asyncio.create_task(asyncio.sleep(60))
    ctx.pty_mirror.output_dispatch_queue = queue
    ctx.pty_mirror.output_dispatch_task = task
    ctx.pty_mirror_output_queue = queue
    ctx.pty_mirror_output_task = task


async def _run() -> None:
    client = FakeClient()
    mirror = PtyMirrorRuntime(client=client)
    macros = RecordingMacros()
    prepare_calls: list[str] = []
    capture_calls: list[bool] = []
    ctx = _ctx(
        mirror,
        macros,
        prepare_output=lambda: prepare_calls.append("usb"),
        set_capture=lambda enabled: capture_calls.append(bool(enabled)),
    )

    await handle_resolved_action("KC_A", True, ctx)
    assert macros.events == [("KC_A", True)]
    assert client.actions == []

    await handle_resolved_action("KC_SH7", True, ctx)
    assert prepare_calls == ["usb"]
    assert capture_calls == [True]
    assert mirror.active is True
    assert client.starts == [{"command": "bash", "columns": 120, "rows": 35, "source": "KC_SH7"}]
    assert macros.events == [("KC_A", True), ("KC_C", True), ("KC_C", False)]
    assert macros.alerts[-1] == ("PTY START", 1.5, {"immediate": True})

    watch_client = WatchOutputClient()
    watch_mirror = PtyMirrorRuntime(client=watch_client)
    watch_macros = RecordingMacros()
    watch_ctx = _ctx(watch_mirror, watch_macros)
    await handle_resolved_action("KC_SH7", True, watch_ctx)
    await asyncio.sleep(0.05)
    await _drain_pty_output(watch_ctx)
    assert watch_client.actions == []
    assert ("KC_P", True) in watch_macros.events
    await watch_mirror.stop(reason="watch_test_done")
    await _cancel_pty_output_for_test(watch_ctx)

    watch_exit_client = WatchExitClient()
    watch_exit_mirror = PtyMirrorRuntime(client=watch_exit_client)
    watch_exit_macros = RecordingMacros()
    watch_exit_capture_calls: list[bool] = []
    watch_exit_ctx = _ctx(
        watch_exit_mirror,
        watch_exit_macros,
        set_capture=lambda enabled: watch_exit_capture_calls.append(bool(enabled)),
    )
    await handle_resolved_action("KC_SH7", True, watch_exit_ctx)
    await asyncio.sleep(0.05)
    assert watch_exit_mirror.active is False
    assert watch_exit_capture_calls == [True, False]
    assert watch_exit_ctx.pty_mirror_output_task is None
    assert watch_exit_ctx.pty_mirror_output_queue is None
    assert watch_exit_macros.alerts[-1] == ("PTY EXIT\nexit:130", 2.0, {"immediate": True})

    ephemeral_client = FakeClient()
    ephemeral_mirror = PtyMirrorRuntime(client=ephemeral_client)
    ephemeral_macros = RecordingMacros()
    first_ctx = _ctx(ephemeral_mirror, ephemeral_macros)
    await handle_resolved_action("KC_SH7", True, first_ctx)
    first_task = ephemeral_mirror.output_dispatch_task
    first_queue = ephemeral_mirror.output_dispatch_queue
    assert first_task is not None
    assert first_queue is not None
    second_ctx = _ctx(ephemeral_mirror, ephemeral_macros)
    await handle_resolved_action("KC_A", True, second_ctx)
    assert ephemeral_mirror.output_dispatch_task is first_task
    assert ephemeral_mirror.output_dispatch_queue is first_queue
    assert second_ctx.pty_mirror_output_task is first_task
    assert second_ctx.pty_mirror_output_queue is first_queue
    await _drain_pty_output(second_ctx)
    await ephemeral_mirror.stop(reason="ephemeral_context_test_done")
    await _cancel_pty_output_for_test(second_ctx)

    await handle_resolved_action("KC_A", True, ctx)
    await handle_resolved_action("KC_A", False, ctx)
    assert client.actions == [("KC_A", True, ())]
    assert macros.events == [
        ("KC_A", True),
        ("KC_C", True),
        ("KC_C", False),
    ]
    await _drain_pty_output(ctx)
    assert macros.events == [
        ("KC_A", True),
        ("KC_C", True),
        ("KC_C", False),
        ("KC_B", True),
        ("KC_B", False),
    ]
    assert mirror.text_plan_count == 2
    assert mirror.last_text_plans

    await handle_resolved_action("KC_B", True, ctx)
    assert client.actions == [("KC_A", True, ()), ("KC_B", True, ())]
    assert mirror.last_text_plans == []
    assert macros.events == [
        ("KC_A", True),
        ("KC_C", True),
        ("KC_C", False),
        ("KC_B", True),
        ("KC_B", False),
    ]

    await handle_resolved_action("KC_U", True, ctx)
    assert client.actions[-1] == ("KC_U", True, ())
    assert mirror.text_plan_count == 2
    assert mirror.last_text_plans == []

    await handle_resolved_action("KC_ENTER", True, ctx)
    assert mirror.active is False
    assert mirror.last_reason == "exit:0"
    assert capture_calls == [True, False]
    assert ctx.pty_mirror_output_task is None
    assert ctx.pty_mirror_output_queue is None or ctx.pty_mirror_output_queue.empty()
    assert macros.alerts[-1] == ("PTY EXIT\nexit:0", 2.0, {"immediate": True})

    failing_client = FakeClient()
    failing_mirror = PtyMirrorRuntime(client=failing_client)
    failing_macros = RecordingMacros()
    failing_ctx = _ctx(
        failing_mirror,
        failing_macros,
        prepare_output=lambda: (_ for _ in ()).throw(RuntimeError("outputd target unavailable")),
    )
    await handle_resolved_action("KC_SH7", True, failing_ctx)
    assert failing_mirror.active is False
    assert failing_mirror.last_reason == "output_prepare_failed"
    assert failing_client.starts == []
    assert failing_macros.alerts[-1] == ("PTY ERROR", 3.0, {"immediate": True})

    client = ExitWithTextPlanClient()
    mirror = PtyMirrorRuntime(client=client, active=True)
    macros = RecordingMacros()
    ctx = _ctx(mirror, macros)
    _seed_pending_pty_output(ctx)
    await handle_resolved_action("KC_ENTER", True, ctx)
    assert client.actions[-1] == ("KC_ENTER", True, ())
    assert mirror.active is False
    assert mirror.last_reason == "exit:0"
    assert ctx.pty_mirror_output_task is None
    assert ctx.pty_mirror_output_queue is None or ctx.pty_mirror_output_queue.empty()
    assert macros.events == [("KC_D", True), ("KC_D", False)]
    assert macros.alerts[-1] == ("PTY EXIT\nexit:0", 2.0, {"immediate": True})

    client = ExitWithTextPlanClient()
    mirror = PtyMirrorRuntime(client=client, active=True)
    macros = FailingKeyMacros("KC_D")
    ctx = _ctx(mirror, macros)
    _seed_pending_pty_output(ctx)
    await handle_resolved_action("KC_ENTER", True, ctx)
    assert mirror.active is False
    assert mirror.last_reason == "output_dispatch_failed"
    assert "synthetic KC_D press failed" in str(mirror.last_error)
    assert ctx.pty_mirror_output_task is None
    assert ctx.pty_mirror_output_queue is None or ctx.pty_mirror_output_queue.empty()
    assert client.stops == [{"reason": "output_dispatch_failed"}]
    assert macros.alerts[-1] == ("PTY ERROR", 3.0, {"immediate": True})

    mirror = PtyMirrorRuntime(client=RaisingClient(), active=True, active_modifiers={"KC_LSFT"})
    macros = RecordingMacros()
    ctx = _ctx(mirror, macros)
    _seed_pending_pty_output(ctx)
    await handle_resolved_action("KC_A", True, ctx)
    assert mirror.active is False
    assert mirror.last_reason == "sessiond_unavailable"
    assert mirror.active_modifiers == set()
    assert ctx.pty_mirror_output_task is None
    assert ctx.pty_mirror_output_queue is None or ctx.pty_mirror_output_queue.empty()
    assert "send exploded" in str(mirror.last_error)
    assert macros.alerts[-1] == ("PTY ERROR", 3.0, {"immediate": True})

    client = FakeClient()
    mirror = PtyMirrorRuntime(client=client)
    restarted = await mirror.start(source="KC_SH7")
    assert restarted["active"] is True
    assert mirror.sent_key_actions == 0
    assert mirror.text_plan_count == 1
    assert mirror.last_text_plans
    assert mirror.display_ready is True

    assert mirror._input_display_plans("KC_P", []) == []
    assert mirror._input_display_plans("KC_W", []) == []
    assert mirror._input_display_plans("KC_D", []) == []
    assert mirror.typeahead_text == ""
    assert mirror._input_display_plans("KC_ENTER", []) == []
    assert mirror.display_ready is False
    mirror._handle_output_result(
        {
            "ok": True,
            "responses": [{"type": "pty_text_stream", "text": "/home/USERNAME/hidloom\r\noperator@<keyboard-host>:~/hidloom $ "}],
            "text_plans": [{"available": True, "taps": [{"type": "tap", "key": "KC_T", "modifiers": []}]}],
        },
        lambda _plans: None,
    )
    assert mirror.display_ready is True
    assert mirror.typeahead_text == ""

    client = FakeClient()
    mirror = PtyMirrorRuntime(client=client)
    macros = RecordingMacros()
    capture_calls = []
    ctx = _ctx(mirror, macros, set_capture=lambda enabled: capture_calls.append(bool(enabled)))
    await handle_resolved_action("KC_SH7", True, ctx)
    await handle_resolved_action("KC_LSFT", True, ctx)
    await handle_resolved_action("KC_LCTRL", True, ctx)
    await handle_resolved_action("KC_1", True, ctx)
    await handle_resolved_action("KC_2", True, ctx)
    await handle_resolved_action("KC_2", False, ctx)
    await handle_resolved_action("KC_LSFT", False, ctx)
    await handle_resolved_action("KC_LCTRL", False, ctx)
    assert client.actions[-2:] == [
        ("KC_1", True, ("KC_LCTRL", "KC_LSFT")),
        ("KC_2", True, ("KC_LCTRL", "KC_LSFT")),
    ]
    assert mirror.active_modifiers == set()

    await handle_resolved_action("KC_A", False, ctx)
    assert client.actions[-2:] == [
        ("KC_1", True, ("KC_LCTRL", "KC_LSFT")),
        ("KC_2", True, ("KC_LCTRL", "KC_LSFT")),
    ]
    assert macros.events == [("KC_C", True), ("KC_C", False)]

    await handle_resolved_action("KC_LCTRL", True, ctx)
    await handle_resolved_action("KC_C", True, ctx)
    await handle_resolved_action("KC_LCTRL", False, ctx)
    assert client.actions[-1] == ("KC_C", True, ("KC_LCTRL",))
    assert mirror.clear_output_queue_requests == 1
    assert mirror.active_modifiers == set()

    mirror = PtyMirrorRuntime(active=True, active_modifiers={"KC_LCTRL"})
    macros = RecordingMacros()
    release_calls = []
    ctx = _ctx(mirror, macros, release_output=lambda: release_calls.append("release"))
    client = PreCancelInspectingInterruptClient(ctx)
    mirror.bind_client(client)
    _seed_pending_pty_output(ctx)
    await handle_resolved_action("KC_C", True, ctx)
    assert client.output_was_cleared_before_send is True
    assert release_calls == ["release"]
    assert client.actions[-1] == ("KC_C", True, ("KC_LCTRL",))

    mirror = PtyMirrorRuntime(active=True, active_modifiers={"KC_LCTRL"})
    macros = RecordingMacros()
    release_calls = []
    ctx = _ctx(mirror, macros, release_output=lambda: release_calls.append("release"))
    client = InterruptWithPromptClient()
    mirror.bind_client(client)
    _seed_pending_pty_output(ctx, key="KC_Z")
    await handle_resolved_action("KC_C", True, ctx)
    await _drain_pty_output(ctx)
    assert client.actions[-1] == ("KC_C", True, ("KC_LCTRL",))
    assert release_calls == ["release"]
    assert ("KC_Z", True) not in macros.events
    assert ("KC_P", True) in macros.events

    client = InterruptStatusOnlyClient()
    mirror = PtyMirrorRuntime(client=client, active=True, active_modifiers={"KC_LCTRL"})
    forced_clear = await mirror.route_action("KC_C", True)
    assert client.actions[-1] == ("KC_C", True, ("KC_LCTRL",))
    assert forced_clear["clear_output_queue"] is True
    assert forced_clear["active"] is True

    client = ClearQueueResponseClient()
    mirror = PtyMirrorRuntime(client=client, active=True)
    macros = RecordingMacros()
    ctx = _ctx(mirror, macros)
    _seed_pending_pty_output(ctx)
    await handle_resolved_action("KC_L", True, ctx)
    assert ctx.pty_mirror_output_task is not None
    assert ctx.pty_mirror_output_queue is not None
    assert ctx.pty_mirror_output_queue.qsize() == 1
    await _drain_pty_output(ctx)
    assert macros.events == [("KC_E", True), ("KC_E", False)]
    assert client.actions == [("KC_L", True, ())]
    await handle_resolved_action("KC_SH7", True, ctx)
    assert mirror.active is False
    assert ctx.pty_mirror_output_task is None
    assert ctx.pty_mirror_output_queue is None or ctx.pty_mirror_output_queue.empty()

    client = FakeClient()
    mirror = PtyMirrorRuntime(client=client)
    macros = RecordingMacros()
    capture_calls = []
    ctx = _ctx(mirror, macros, set_capture=lambda enabled: capture_calls.append(bool(enabled)))
    await handle_resolved_action("KC_SH7", True, ctx)
    assert mirror.last_text_plans
    _seed_pending_pty_output(ctx)
    await handle_resolved_action("KC_USB", True, ctx)
    assert mirror.active is False
    assert mirror.last_reason == "output_switch"
    assert capture_calls == [True, False]
    assert mirror.last_error is None
    assert mirror.last_text_plans == []
    assert ctx.pty_mirror_output_task is None
    assert ctx.pty_mirror_output_queue is None or ctx.pty_mirror_output_queue.empty()
    assert client.stops == [{"reason": "output_switch"}]
    assert all(action != "KC_USB" for action, _is_press, _mods in client.actions)
    assert all(action != "KC_A" for action, _is_press in macros.events)
    assert macros.events[-1] == ("KC_USB", True)
    assert macros.alerts[-1] == ("PTY EXIT\noutput_switch", 2.0, {"immediate": True})

    client = DisplayFakeClient()
    mirror = PtyMirrorRuntime(client=client, active=True, display_ready=True)
    enqueued_typeahead: list[list[dict]] = []
    enter_plans = mirror._input_display_plans("KC_ENTER", [])
    assert enter_plans
    for action in ("KC_E", "KC_C", "KC_H", "KC_O", "KC_SPACE", "KC_O", "KC_K", "KC_ENTER"):
        assert mirror._input_display_plans(action, []) == []
    assert mirror.display_ready is False
    assert mirror.typeahead_text == "echo ok\r\n"
    assert mirror._handle_output_result(
        {
            "ok": True,
            "responses": [{"type": "pty_text_stream", "text": "operator@<keyboard-host>:~/hidloom $ "}],
            "text_plans": [],
        },
        enqueued_typeahead.append,
    ) is False
    assert enqueued_typeahead[-1][0]["text"] == "operator@<keyboard-host>:~/hidloom $ echo ok\r\n"
    assert mirror.typeahead_text == ""

    client = FakeClient()
    mirror = PtyMirrorRuntime(client=client)
    macros = RecordingMacros()
    capture_calls = []
    ctx = _ctx(mirror, macros, set_capture=lambda enabled: capture_calls.append(bool(enabled)))
    await handle_resolved_action("KC_SH7", True, ctx)
    await handle_resolved_action("KC_SH7", False, ctx)
    assert mirror.active is True
    events_before_escape = list(macros.events)
    _seed_pending_pty_output(ctx)
    await handle_resolved_action("KC_SH7", True, ctx)
    await handle_resolved_action("KC_SH7", False, ctx)
    assert mirror.active is False
    assert mirror.last_reason == "operator_escape"
    assert capture_calls == [True, False]
    assert ctx.pty_mirror_output_task is None
    assert ctx.pty_mirror_output_queue is None or ctx.pty_mirror_output_queue.empty()
    assert client.stops == [{"reason": "operator_escape"}]
    assert all(action != "KC_SH7" for action, _is_press, _mods in client.actions)
    assert macros.events == events_before_escape
    assert macros.alerts[-1] == ("PTY EXIT\noperator_escape", 2.0, {"immediate": True})

    mirror = PtyMirrorRuntime()
    macros = FailingMacros()
    ctx = _ctx(mirror, macros)
    try:
        await _dispatch_tap({"key": "KC_A", "modifiers": ["KC_LSHIFT"]}, ctx, hold_sec=0)
    except RuntimeError as exc:
        assert "synthetic press failed" in str(exc)
    else:
        raise AssertionError("synthetic tap failure should propagate")
    assert macros.events == [
        ("KC_LSHIFT", True),
        ("KC_A", True),
        ("KC_A", False),
        ("KC_LSHIFT", False),
    ]

    blocked = await dispatch_pty_mirror_text_plans([{"available": False, "blocking_reasons": ["x"]}], ctx)
    assert blocked["result"] == "blocked"
    assert blocked["blocking_reasons"] == ["no_available_pty_text_plan"]
    assert blocked["events"] == 0
    assert blocked["taps"] == 0

    invalid = await dispatch_pty_mirror_text_plans([{"available": True, "taps": []}], ctx)
    assert invalid["result"] == "blocked"
    assert invalid["blocking_reasons"] == ["pty_text_plan_taps_unavailable"]

    invalid_key = await dispatch_pty_mirror_text_plans([{"available": True, "taps": [{"type": "tap", "key": ""}]}], ctx)
    assert invalid_key["result"] == "blocked"
    assert invalid_key["blocking_reasons"] == ["invalid_pty_text_tap_key"]
    assert invalid_key["events"] == 0
    assert invalid_key["taps"] == 0

    invalid_modifier = await dispatch_pty_mirror_text_plans(
        [{"available": True, "taps": [{"type": "tap", "key": "KC_A", "modifiers": "KC_LSHIFT"}]}],
        ctx,
    )
    assert invalid_modifier["result"] == "blocked"
    assert invalid_modifier["blocking_reasons"] == ["invalid_pty_text_tap_modifier"]
    assert invalid_modifier["events"] == 0
    assert invalid_modifier["taps"] == 0

    empty_modifier = await dispatch_pty_mirror_text_plans(
        [{"available": True, "taps": [{"type": "tap", "key": "KC_A", "modifiers": [""]}]}],
        ctx,
    )
    assert empty_modifier["result"] == "blocked"
    assert empty_modifier["blocking_reasons"] == ["invalid_pty_text_tap_modifier"]
    assert empty_modifier["events"] == 0
    assert empty_modifier["taps"] == 0

    mirror = PtyMirrorRuntime()
    macros = RecordingMacros()
    ctx = _ctx(mirror, macros)
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    original_sleep = output_runner.asyncio.sleep
    output_runner.asyncio.sleep = record_sleep
    try:
        timed = await dispatch_pty_mirror_text_plans(
            [
                {
                    "available": True,
                    "tap_hold_sec": 0.011,
                    "tap_gap_sec": 0.022,
                    "post_gap_sec": 0.033,
                    "taps": [
                        {"type": "tap", "key": "KC_A", "modifiers": [], "post_gap_sec": 0.077},
                        {"type": "tap", "key": "KC_C", "modifiers": []},
                    ],
                },
                {
                    "available": True,
                    "tap_hold_sec": 0.044,
                    "tap_gap_sec": 0.055,
                    "taps": [{"type": "tap", "key": "KC_B", "modifiers": []}],
                },
            ],
            ctx,
        )
    finally:
        output_runner.asyncio.sleep = original_sleep
    assert timed["result"] == "ok"
    assert sleeps == [0.011, 0.077, 0.011, 0.033, 0.044]

    sleeps.clear()
    output_runner.asyncio.sleep = record_sleep
    try:
        yielded = await dispatch_pty_mirror_text_plans(
            [
                {
                    "available": True,
                    "tap_hold_sec": 0,
                    "tap_gap_sec": 0,
                    "taps": [
                        {"type": "tap", "key": "KC_A", "modifiers": []}
                        for _ in range(PTY_MIRROR_OUTPUT_YIELD_EVERY_TAPS)
                    ],
                }
            ],
            ctx,
        )
    finally:
        output_runner.asyncio.sleep = original_sleep
    assert yielded["result"] == "ok"
    assert sleeps == [0]

    client = FakeClient()
    mirror = PtyMirrorRuntime(client=client)
    macros = FailingKeyMacros("KC_C")
    ctx = _ctx(mirror, macros)
    await handle_resolved_action("KC_SH7", True, ctx)
    assert mirror.active is False
    assert mirror.last_reason == "output_dispatch_failed"
    assert "synthetic KC_C press failed" in str(mirror.last_error)
    assert client.stops == [{"reason": "output_dispatch_failed"}]
    assert macros.alerts[-1] == ("PTY ERROR", 3.0, {"immediate": True})

    client = FakeClient()
    mirror = PtyMirrorRuntime(client=client)
    macros = FailingKeyMacros("KC_B")
    ctx = _ctx(mirror, macros)
    await handle_resolved_action("KC_SH7", True, ctx)
    await handle_resolved_action("KC_A", True, ctx)
    await _drain_pty_output(ctx)
    assert mirror.active is False
    assert mirror.last_reason == "output_dispatch_failed"
    assert "synthetic KC_B press failed" in str(mirror.last_error)
    assert client.actions == [("KC_A", True, ())]
    assert client.stops == [{"reason": "output_dispatch_failed"}]
    assert macros.alerts[-1] == ("PTY ERROR", 3.0, {"immediate": True})

    mirror = PtyMirrorRuntime(client=RaisingClient())
    failed_start = await mirror.start(source="KC_SH7")
    assert failed_start["active"] is False
    assert failed_start["last_reason"] == "start_failed"
    assert "start exploded" in failed_start["last_error"]

    mirror = PtyMirrorRuntime(client=RaisingClient(), active=True, active_modifiers={"KC_LSFT"})
    failed_route = await mirror.route_action("KC_A", True)
    assert failed_route == {"consumed": True, "reason": "sessiond_unavailable", "active": False, "text_plans": []}
    assert mirror.active_modifiers == set()
    assert "send exploded" in str(mirror.last_error)

    mirror = PtyMirrorRuntime(client=RaisingClient(), active=True, active_modifiers={"KC_LSFT"})
    stopped = await mirror.stop(reason="operator_stop")
    assert stopped["active"] is False
    assert stopped["last_reason"] == "operator_stop"
    assert stopped["active_modifiers"] == []
    assert "stop exploded" in stopped["last_error"]


def _test_key_action_text_aliases() -> None:
    assert key_action_to_text_char("KC_SPC") == " "
    assert key_action_to_text_char("KC_MINS") == "-"
    assert key_action_to_text_char("KC_MINS", ["KC_LSFT"]) == "_"
    assert key_action_to_text_char("KC_EQL") == "="
    assert key_action_to_text_char("KC_EQL", ["KC_LSFT"]) == "+"
    assert key_action_to_text_char("KC_LBRC") == "["
    assert key_action_to_text_char("KC_RBRC", ["KC_LSFT"]) == "}"
    assert key_action_to_text_char("KC_BSLS", ["KC_LSFT"]) == "|"
    assert key_action_to_text_char("KC_SCLN") == ";"
    assert key_action_to_text_char("KC_QUOT", ["KC_LSFT"]) == '"'
    assert key_action_to_text_char("KC_GRV") == "`"
    assert key_action_to_text_char("KC_COMM", ["KC_LSFT"]) == "<"
    assert key_action_to_text_char("KC_SLSH", ["KC_LSFT"]) == "?"


def main() -> None:
    _test_key_action_text_aliases()
    asyncio.run(_run())
    print("ok: logicd PTY mirror runtime consumes active key actions and exits on status")


if __name__ == "__main__":
    main()
