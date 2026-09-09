#!/usr/bin/env python3
"""Python split-keyboard ownership parity using synthetic report sinks."""
import asyncio
import itertools
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "daemon"), str(ROOT)]
from logicd.config_runtime import _with_usb_split_keyboard_switch
from logicd.hid_report import HidState
from logicd.macro import MacroExecutor
from logicd.output_router import CallableOutputBackend, OutputRouter
from logicd.input_events import InputEventContext, process_matrix_event
from logicd.interaction_engine import InteractionEngine
from logicd.keymap import LayerManager


def edges(reports, usage):
    state = False
    result = []
    for report in reports:
        held = usage in report[2:]
        if held != state:
            result.append(held)
        state = held
    return result


def fixture(route="jis_special_us_default"):
    main, sub = [], []
    router = OutputRouter()
    router.register(CallableOutputBackend("gadget", _with_usb_split_keyboard_switch(main.append, sub.append, route=route)))
    router.set_targets(("gadget",))
    state = HidState()
    return MacroExecutor(state, router, {}), state, main, sub


async def main_async():
    for actions, usages in ((("KC_A", "KC_RO"), (4, 0x87)), (("KC_GRV", "KC_ZKHK"), (0x35, 0x35))):
        for presses in itertools.permutations(range(2)):
            for releases in itertools.permutations(range(2)):
                executor, state, main, sub = fixture()
                for index in presses:
                    await executor.handle(actions[index], True)
                assert usages[0] in sub[-1][2:], (actions, presses, main, sub)
                assert usages[1] in main[-1][2:], (actions, presses, main, sub)
                for index in releases:
                    await executor.handle(actions[index], False)
                assert edges(sub, usages[0]) == [True, False], (actions, presses, releases, sub)
                assert edges(main, usages[1]) == [True, False], (actions, presses, releases, main)
                if usages[0] != usages[1]:
                    assert edges(main, usages[0]) == []
                    assert edges(sub, usages[1]) == []
                assert state.build() == main[-1] == sub[-1] == bytes(8)
                assert all(report[1] == 0 for report in main + sub)

    executor, state, main, sub = fixture()
    await executor.handle("KC_A", True, source="matrix")
    await executor.handle("KC_A", True, source="web")
    await executor.handle("KC_A", False, source="web")
    assert 4 in sub[-1][2:]
    await executor.handle("KC_A", False, source="matrix")
    assert edges(sub, 4) == [True, False]
    for source in ("matrix", "web"):
        await executor.handle("KC_LSFT", True, source=source)
    await executor.handle("KC_LSFT", False, source="web")
    assert state.mod == 2 and main[-1][0] == sub[-1][0] == 2
    await executor._tap(5, add_mod_bits=2, hold=0)
    assert state.mod == 2
    await executor.handle("KC_LSFT", False, source="matrix")
    assert main[-1] == sub[-1] == bytes(8)

    await executor.handle("KC_A", True, source="matrix")
    await executor.handle("KC_LSFT", True, source="matrix")
    cancelled_macro = asyncio.create_task(executor._exec(["{KC_DOWN:KC_A}", "{KC_DOWN:KC_LSFT}", "{KC_DOWN:KC_B}", "{DELAY:60000}"]))
    await asyncio.sleep(0)
    assert 5 in state.build()[2:]
    cancelled_macro.cancel()
    try:
        await cancelled_macro
    except asyncio.CancelledError:
        pass
    assert state.mod == 2 and set(state.build()[2:]) - {0} == {4}
    await executor.handle("KC_A", False, source="matrix")
    await executor.handle("KC_LSFT", False, source="matrix")
    assert state.build() == bytes(8)

    await executor.handle("KC_A", True, source="matrix")
    await executor.handle("KC_LSFT", True, source="matrix")
    cancelled_tap = asyncio.create_task(executor._tap(4, add_mod_bits=2, hold=60))
    await asyncio.sleep(0)
    cancelled_tap.cancel()
    try:
        await cancelled_tap
    except asyncio.CancelledError:
        pass
    assert state.mod == 2 and 4 in state.build()[2:]
    await executor.handle("KC_A", False, source="matrix")
    await executor.handle("KC_LSFT", False, source="matrix")
    assert main[-1] == sub[-1] == bytes(8)

    executor, state, main, sub = fixture()
    for action in ("KC_A", "KC_B", "KC_C", "KC_D", "KC_E", "KC_GRV", "KC_ZKHK", "KC_RO"):
        await executor.handle(action, True)
    assert list(state.build()[2:]) == [4, 5, 6, 7, 8, 0x35]
    assert main[-1] == bytes([0, 0, 0, 0, 0, 0, 0, 0x35])
    assert sub[-1] == bytes([0, 0, 4, 5, 6, 7, 8, 0x35])
    await executor.handle("KC_ZKHK", False)
    assert 0x35 in sub[-1][2:]
    await executor.handle("KC_GRV", False)
    assert state.build()[2:] == bytes([4, 5, 6, 7, 8, 0])

    executor, state, main, sub = fixture(route="all")
    for action in ("KC_A", "KC_RO", "KC_ZKHK", "KC_GRV"):
        await executor.handle(action, True)
    assert set(main[-1][2:]) - {0} == {0x35}
    assert set(sub[-1][2:]) - {0} == {4, 0x87, 0x35}
    for action in ("KC_ZKHK", "KC_RO", "KC_A", "KC_GRV"):
        await executor.handle(action, False)
    assert main[-1] == sub[-1] == bytes(8)
    assert edges(main, 0x35) == edges(sub, 0x35) == [True, False]

    events = []
    writer = _with_usb_split_keyboard_switch(
        lambda report: events.append(("main", report)),
        lambda report: events.append(("sub", report)),
        route="jis_special_us_default",
    )
    executor = MacroExecutor(HidState(), writer, {})
    await executor._tap(4, add_mod_bits=2, hold=0)
    assert events == [
        ("main", bytes([2, 0, 0, 0, 0, 0, 0, 0])),
        ("sub", bytes([2, 0, 0, 0, 0, 0, 0, 0])),
        ("sub", bytes([2, 0, 4, 0, 0, 0, 0, 0])),
        ("sub", bytes([2, 0, 0, 0, 0, 0, 0, 0])),
        ("main", bytes(8)),
        ("sub", bytes(8)),
    ], events

    executor, state, main, sub = fixture()
    layers = LayerManager()
    layers.load([{"0,0": "KC_A", "0,1": "KC_A", "0,2": "KC_LSFT"}])
    noop = lambda *args, **kwargs: None
    ctx = InputEventContext(
        layers=layers, interactions=InteractionEngine(layers), macros=executor,
        encoders=SimpleNamespace(handles=lambda *args: False), joysticks=None,
        pressed_matrix=set(), push_ledd_key_event=noop, push_ledd_status=noop,
        push_i2cd_status=noop, push_i2cd_alert=noop, push_ledd_anim=noop,
        apply_lighting_key_action=lambda *args: False, mouse_write_fn=noop,
        bt_manager=None, wifi_manager=None,
    )
    for owner, col in (("matrix", 0), ("matrix", 1), ("web", 0)):
        await process_matrix_event(("P", 0, col), ctx, owner=owner)
    for owner, col in (("web", 0), ("matrix", 1)):
        await process_matrix_event(("R", 0, col), ctx, owner=owner)
        assert 4 in state.build()[2:]
    await process_matrix_event(("R", 0, 0), ctx)
    assert edges(sub, 4) == [True, False]
    for owner in ("matrix", "web"):
        await process_matrix_event(("P", 0, 2), ctx, owner=owner)
    await process_matrix_event(("R", 0, 2), ctx, owner="web")
    assert state.mod == 2
    await process_matrix_event(("R", 0, 2), ctx)
    assert state.build() == bytes(8)
    assert not ctx.pressed_matrix_owners

    native_state = HidState()
    native_state.press(4, source="physical")
    native_state.press(0xE1, source="physical")
    native_events = []
    async def native_edge(code, pressed, source):
        native_events.append((code, pressed, source))
        (native_state.press if pressed else native_state.release)(code, source=source)
    def no_snapshot(report):
        raise AssertionError("native macro bypassed source-owned callback")
    native_executor = MacroExecutor(HidState(), no_snapshot, {"hold": ["{KC_DOWN:KC_LSFT}", "{KC_DOWN:KC_A}", "{KC_DOWN:KC_B}", "{DELAY:60000}"]})
    native_executor.keyboard_event_fn = native_edge
    await native_executor._tap(4, add_mod_bits=2, hold=0)
    assert [(code, pressed) for code, pressed, source in native_events] == [(0xE1, True), (4, True), (4, False), (0xE1, False)]
    assert native_state.mod == 2 and set(native_state.build()[2:]) - {0} == {4}
    task = asyncio.create_task(native_executor.handle_owned("MACRO:hold", True, source=("web", (0, 0))))
    await asyncio.sleep(0)
    assert native_events[-1][2][0] == ("web", (0, 0))
    assert 5 in native_state.build()[2:]
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert native_state.mod == 2 and set(native_state.build()[2:]) - {0} == {4}

    # Fake process only: source end suppresses later shell HID output, while
    # the existing script execution can finish and be reaped normally.
    entered, finish = asyncio.Event(), asyncio.Event()
    async def communicate():
        entered.set()
        await finish.wait()
        return b"fixture result", b""
    proc = SimpleNamespace(communicate=communicate, returncode=0)
    executor._resolve_shell_script = lambda name: __file__
    executor._load_script_report_metadata = lambda path: SimpleNamespace(enabled=True, sinks=("hid_text",))
    notify = AsyncMock()
    executor._notify_script_report = notify
    with patch("logicd.macro.asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
        await executor.handle_owned("KC_SH0", True, source=("web", (0, 0)))
        await entered.wait()
        assert executor.has_pending_output()
        executor.cancel_output_source("web")
        finish.set()
        await asyncio.gather(*list(executor._shell_output_tasks))
        assert not executor.has_pending_output()
        notify.assert_not_awaited()
    print("ok: Python keyboard route/source ownership and global six-key parity")


if __name__ == "__main__":
    asyncio.run(main_async())
