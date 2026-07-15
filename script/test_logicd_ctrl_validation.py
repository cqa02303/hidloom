#!/usr/bin/env python3
"""Local smoke test for logicd ctrl input validation and error responses."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd import logicd  # noqa: E402
from logicd.env import env_float, env_int  # noqa: E402
from logicd.hid_report import HidState  # noqa: E402
from logicd.joystick import JoystickBinding, JoystickManager  # noqa: E402
from logicd.keymap import LayerManager  # noqa: E402


class FakeWriter:
    def __init__(self) -> None:
        self.data = bytearray()

    def write(self, data: bytes) -> None:
        self.data.extend(data)

    async def drain(self) -> None:
        return None

    def messages(self) -> list[dict]:
        return [json.loads(line) for line in self.data.decode("utf-8").splitlines() if line]


class FakeOutputWriter:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.reports: list[bytes] = []

    def __call__(self, report: bytes) -> None:
        self.reports.append(report)

    def force_auto(self) -> None:
        self.calls.append("auto")

    def force_gadget(self) -> None:
        self.calls.append("gadget")

    def force_uinput(self) -> None:
        self.calls.append("uinput")

    def force_bt(self) -> None:
        self.calls.append("bt")


class FakeBtManager:
    def __init__(self) -> None:
        self.ensure_powered_calls = 0

    async def ensure_powered_for_output(self) -> None:
        self.ensure_powered_calls += 1


async def request(line: str) -> list[dict]:
    writer = FakeWriter()
    await logicd._process_ctrl_json(line, writer)  # type: ignore[attr-defined]
    return writer.messages()


async def main_async() -> None:
    assert env_int("NO_SUCH_ENV", 7, min_value=1, max_value=10) == 7
    old_bad_int = logicd.os.environ.get("LOGICD_TEST_BAD_INT")  # type: ignore[attr-defined]
    old_bad_float = logicd.os.environ.get("LOGICD_TEST_BAD_FLOAT")  # type: ignore[attr-defined]
    logicd.os.environ["LOGICD_TEST_BAD_INT"] = "nan"  # type: ignore[attr-defined]
    logicd.os.environ["LOGICD_TEST_BAD_FLOAT"] = "nope"  # type: ignore[attr-defined]
    try:
        assert env_int("LOGICD_TEST_BAD_INT", 9, min_value=1) == 9
        assert env_float("LOGICD_TEST_BAD_FLOAT", 0.25, min_value=0.0) == 0.25
    finally:
        if old_bad_int is None:
            logicd.os.environ.pop("LOGICD_TEST_BAD_INT", None)  # type: ignore[attr-defined]
        else:
            logicd.os.environ["LOGICD_TEST_BAD_INT"] = old_bad_int  # type: ignore[attr-defined]
        if old_bad_float is None:
            logicd.os.environ.pop("LOGICD_TEST_BAD_FLOAT", None)  # type: ignore[attr-defined]
        else:
            logicd.os.environ["LOGICD_TEST_BAD_FLOAT"] = old_bad_float  # type: ignore[attr-defined]

    logicd._runtime.layers = LayerManager()  # type: ignore[attr-defined]
    logicd._runtime.led_state.update({"mode": 2, "speed": 128, "h": 0, "s": 0, "v": 128})
    logicd._push_ledd_vialrgb = lambda: None  # type: ignore[assignment]
    led_key_events: list[tuple[int, int, bool]] = []
    logicd._push_ledd_key_event = lambda row, col, is_press: led_key_events.append((row, col, is_press))  # type: ignore[assignment]
    direct_patterns: list[tuple[str, float, int]] = []
    logicd._push_ledd_vialrgb_direct_pattern = lambda pattern, fps, brightness: direct_patterns.append((pattern, fps, brightness))  # type: ignore[assignment]
    led_save_calls: list[str] = []
    logicd._schedule_led_state_save = lambda: led_save_calls.append("save")  # type: ignore[assignment]
    led_save_cancels: list[str] = []
    logicd._cancel_led_state_save = lambda: led_save_cancels.append("cancel")  # type: ignore[assignment]
    logicd._load_led_state = lambda: logicd._runtime.led_state.update({"mode": 2, "speed": 64, "h": 1, "s": 2, "v": 3})  # type: ignore[assignment, attr-defined]
    logicd._save_runtime_keymap = lambda: "/tmp/keymap.json"  # type: ignore[assignment]
    semantic_reloads: list[str] = []
    logicd._push_ledd_semantic_reload = lambda: semantic_reloads.append("reload")  # type: ignore[assignment]
    alerts: list[tuple[str, float]] = []
    logicd._push_i2cd_alert = lambda msg, sec=2.0: alerts.append((msg, sec))  # type: ignore[assignment]
    output_writer = FakeOutputWriter()
    logicd._runtime.macros._write = output_writer  # type: ignore[attr-defined]
    bt_manager = FakeBtManager()
    logicd._runtime.bt_manager = bt_manager  # type: ignore[attr-defined]
    modes: list[str] = []
    logicd._push_ledd_mode = lambda mode: modes.append(mode)  # type: ignore[assignment]
    logicd._push_i2cd_mode = lambda mode: modes.append(f"i2c:{mode}")  # type: ignore[assignment]
    bt_pairing_states: list[tuple[str, str]] = []
    logicd._push_bt_pairing_state = lambda phase, digits="": bt_pairing_states.append((phase, digits))  # type: ignore[assignment]

    invalid_json = await request("{")
    assert invalid_json[-1]["result"] == "error"

    invalid_root = await request("[1, 2]")
    assert invalid_root[-1]["result"] == "error"

    bad_remap = await request('{"t":"M","l":0,"r":99,"c":0,"a":"KC_A"}')
    assert bad_remap[-1]["result"] == "error"
    assert logicd._runtime.layers.layers_snapshot() == [{}]  # type: ignore[attr-defined]

    ok_remap = await request('{"t":"M","l":0,"r":1,"c":2,"a":"KC_A"}')
    assert ok_remap[-1] == {"t": "M", "result": "ok"}
    assert logicd._runtime.layers.layers_snapshot()[0]["1,2"] == "KC_A"  # type: ignore[attr-defined]

    joystick = JoystickManager([JoystickBinding(
        name="stick0",
        up=(0, 0),
        down=(3, 3),
        left=(4, 4),
        right=(1, 2),
    )])
    joystick.process(0, 80, 0, logicd._runtime.layers.get_action)  # type: ignore[attr-defined]
    logicd._runtime.joysticks = joystick  # type: ignore[attr-defined]
    logicd._runtime.pressed_matrix = {(0, 1)}  # type: ignore[attr-defined]
    logicd._runtime.observed_pressed_matrix = {(2, 3)}  # type: ignore[attr-defined]
    joystick_status = await request('{"t":"JOYSTICK_STATUS"}')
    assert joystick_status[-1]["result"] == "ok"
    assert joystick_status[-1]["schema"] == "joystick.runtime_status.v1"
    assert joystick_status[-1]["sticks"][0]["directions"][3]["active"] is True
    matrix_status = await request('{"t":"K"}')
    assert matrix_status[-1]["t"] == "matrix"
    assert matrix_status[-1]["pressed"] == [[0, 1], [2, 3]]
    assert matrix_status[-1]["joystick"]["sticks"][0]["directions"][3]["row"] == 1
    logicd._runtime.pressed_matrix.clear()  # type: ignore[attr-defined]
    logicd._runtime.observed_pressed_matrix.clear()  # type: ignore[attr-defined]

    active_layers = await request('{"t":"ACTIVE"}')
    assert active_layers[-1]["t"] == "active"
    assert active_layers[-1]["active"]["all"] == [0]
    assert "layers" not in active_layers[-1]

    added_layer = await request('{"t":"LAYER_ADD"}')
    assert added_layer[-1]["result"] == "ok"
    assert added_layer[-1]["layer"] == 1
    assert logicd._runtime.layers.layers_snapshot()[1]["1,2"] == "KC_TRNS"  # type: ignore[attr-defined]
    assert semantic_reloads[-1] == "reload"

    bad_clear = await request('{"t":"LAYER_CLEAR","l":0}')
    assert bad_clear[-1]["result"] == "error"

    await request('{"t":"M","l":1,"r":1,"c":2,"a":"KC_B"}')
    cleared_layer = await request('{"t":"LAYER_CLEAR","l":1}')
    assert cleared_layer[-1]["result"] == "ok"
    assert cleared_layer[-1]["operation"] == "removed"
    assert len(logicd._runtime.layers.layers_snapshot()) == 1  # type: ignore[attr-defined]
    assert len(semantic_reloads) >= 2

    await request('{"t":"LAYER_ADD"}')
    await request('{"t":"LAYER_ADD"}')
    await request('{"t":"M","l":1,"r":1,"c":2,"a":"KC_B"}')
    middle_clear = await request('{"t":"LAYER_CLEAR","l":1}')
    assert middle_clear[-1]["result"] == "ok"
    assert middle_clear[-1]["operation"] == "cleared"
    assert len(logicd._runtime.layers.layers_snapshot()) == 3  # type: ignore[attr-defined]
    assert logicd._runtime.layers.layers_snapshot()[1]["1,2"] == "KC_TRNS"  # type: ignore[attr-defined]
    assert len(semantic_reloads) >= 5

    logicd._runtime.layers.momentary_on(2)  # type: ignore[attr-defined]
    assert logicd._runtime.layers.layer_lock_toggle_current() == 2  # type: ignore[attr-defined]
    assert logicd._runtime.layers.active_snapshot()["locked"] == [2]  # type: ignore[attr-defined]
    layer_lock_clear = await request('{"t":"LAYER_LOCK_CLEAR"}')
    assert layer_lock_clear[-1]["result"] == "ok"
    assert layer_lock_clear[-1]["changed"] is True
    assert layer_lock_clear[-1]["locked_before"] == [2]
    assert layer_lock_clear[-1]["active"]["locked"] == []
    assert logicd._runtime.layers.active_snapshot()["locked"] == []  # type: ignore[attr-defined]

    logicd._runtime.interactions.caps_word_active = True  # type: ignore[attr-defined]
    logicd._runtime.interactions.repeat_history = "KC_LEFT"  # type: ignore[attr-defined]
    logicd._runtime.interactions.key_locks.handle_action("KEY_LOCK(KC_LSFT)", is_press=True)  # type: ignore[attr-defined]
    logicd._runtime.interactions.layers.oneshot_on(0)  # type: ignore[attr-defined]
    interaction_status = await request('{"t":"INTERACTION_STATUS"}')
    assert interaction_status[-1]["result"] == "ok"
    assert interaction_status[-1]["schema"] == "interaction.runtime_status.v1"
    assert interaction_status[-1]["save_payload_includes_runtime_state"] is False
    assert interaction_status[-1]["caps_word"]["active"] is True
    assert interaction_status[-1]["repeat_key"]["history_available"] is True
    assert interaction_status[-1]["repeat_key"]["alternate_available"] is True
    assert interaction_status[-1]["key_lock"]["keys"][0]["action"] == "KC_LSFT"
    assert interaction_status[-1]["one_shot_layer"]["active_count"] == 1
    assert "KC_LEFT" not in json.dumps(interaction_status[-1]), "repeat history action must stay private"
    logicd._runtime.interactions.clear_runtime_shortcuts()  # type: ignore[attr-defined]
    logicd._runtime.interactions.clear_key_locks(reason="test")  # type: ignore[attr-defined]
    logicd._runtime.interactions.layers.oneshot_clear()  # type: ignore[attr-defined]
    interaction_status = await request('{"t":"INTERACTION_STATUS"}')
    assert interaction_status[-1]["caps_word"]["active"] is False
    assert interaction_status[-1]["repeat_key"]["history_available"] is False
    assert interaction_status[-1]["key_lock"]["keys"] == []
    assert interaction_status[-1]["one_shot_layer"]["active_count"] == 0

    keymap_save = await request('{"t":"S"}')
    assert keymap_save[-1]["result"] == "ok"
    assert semantic_reloads[-1] == "reload"

    clamped_led = await request('{"t":"LED","op":"vialrgb","mode":2,"speed":999,"h":-1,"s":256,"v":64}')
    assert clamped_led[-1] == {"t": "LED", "result": "ok"}
    assert logicd._runtime.led_state["speed"] == 255  # type: ignore[index]
    assert logicd._runtime.led_state["h"] == 0  # type: ignore[index]
    assert logicd._runtime.led_state["s"] == 255  # type: ignore[index]
    assert len(led_save_calls) == 1
    assert not alerts

    mode_led = await request('{"t":"LED","op":"vialrgb","mode":40,"speed":128,"h":80,"s":255,"v":128}')
    assert mode_led[-1] == {"t": "LED", "result": "ok"}
    assert alerts[-1][0] == "LED Effect\n40: Multisplash"
    assert len(led_save_calls) == 2

    high_splash_led = await request('{"t":"LED","op":"vialrgb","mode":40,"speed":128,"h":80,"s":255,"v":255}')
    assert high_splash_led[-1] == {"t": "LED", "result": "ok"}
    assert logicd._runtime.led_state["v"] == 160  # type: ignore[index]
    assert len(led_save_calls) == 3

    preview_restore_led = await request(
        '{"t":"LED","op":"vialrgb","mode":40,"speed":128,"h":80,"s":255,"v":128,"save":false}'
    )
    assert preview_restore_led[-1] == {"t": "LED", "result": "ok"}
    assert len(led_save_calls) == 3

    reset_led = await request('{"t":"LED","op":"vialrgb_reset"}')
    assert reset_led[-1] == {"t": "LED", "result": "ok", "mode": 2, "speed": 64, "h": 1, "s": 2, "v": 3}
    assert led_save_cancels == ["cancel"]

    bad_direct = await request('{"t":"LED","op":"vialrgb_direct","first":0,"pixels":[[1,2,999]]}')
    assert bad_direct[-1]["result"] == "error"

    ok_pattern = await request('{"t":"LED","op":"vialrgb_direct_pattern","pattern":"chase","fps":20,"brightness":96}')
    assert ok_pattern[-1]["result"] == "ok"
    assert direct_patterns[-1] == ("chase", 20.0, 96)

    bad_pattern = await request('{"t":"LED","op":"vialrgb_direct_pattern","pattern":"bad","fps":20,"brightness":96}')
    assert bad_pattern[-1]["result"] == "error"

    led_key_event = await request('{"t":"LED","op":"key_event","kind":"P","row":4,"col":6}')
    assert led_key_event[-1] == {"t": "LED", "result": "ok", "op": "key_event", "kind": "P", "row": 4, "col": 6}
    assert led_key_events[-1] == (4, 6, True)
    bad_led_key_event = await request('{"t":"LED","op":"key_event","kind":"X","row":4,"col":6}')
    assert bad_led_key_event[-1]["result"] == "error"

    output_bt = await request('{"t":"OUTPUT","target":"bt"}')
    assert output_bt[-1] == {"t": "OUTPUT", "result": "ok", "target": "bt"}
    assert output_writer.calls[-1] == "bt"
    assert bt_manager.ensure_powered_calls == 1
    assert modes[-2:] == ["bt", "i2c:bt"]
    assert bt_pairing_states[-1] == ("off", "")

    output_alias = await request('{"t":"OUTPUT","target":"KC_USB"}')
    assert output_alias[-1] == {"t": "OUTPUT", "result": "ok", "target": "gadget"}
    assert output_writer.calls[-1] == "gadget"

    output_auto = await request('{"t":"OUTPUT","target":"auto"}')
    assert output_auto[-1] == {"t": "OUTPUT", "result": "ok", "target": "auto"}
    assert output_writer.calls[-1] == "auto"
    assert "i2c:auto" not in modes
    assert bt_pairing_states[-1] == ("off", "")

    output_bad = await request('{"t":"OUTPUT","target":"bad"}')
    assert output_bad[-1]["result"] == "error"

    logicd._runtime.text_send.begin("kana_a")  # type: ignore[attr-defined]
    text_cancel = await request('{"t":"TEXT_SEND_CANCEL","reason":"emergency_release"}')
    assert text_cancel[-1]["result"] == "ok"
    assert text_cancel[-1]["canceled"] is True
    assert text_cancel[-1]["last_cancel_reason"] == "emergency_release"
    assert text_cancel[-1]["zero_report_sent"] is True
    assert output_writer.reports[-1] == HidState.null_report()

    logicd._runtime.text_send.begin("kana_a")  # type: ignore[attr-defined]
    output_cancel = await request('{"t":"OUTPUT","target":"auto"}')
    assert output_cancel[-1] == {"t": "OUTPUT", "result": "ok", "target": "auto"}
    assert logicd._runtime.text_send.last_cancel_reason == "output_switch"  # type: ignore[attr-defined]
    assert logicd._runtime.text_send.active is False  # type: ignore[attr-defined]
    assert logicd._runtime.text_send.last_zero_report_reason == "output_switch"  # type: ignore[attr-defined]
    assert output_writer.reports[-1] == HidState.null_report()

    logicd._runtime.text_send.begin("kana_timeout", now=20.0, timeout_sec=0.25)  # type: ignore[attr-defined]
    not_expired = logicd._expire_text_send_runner(20.24)  # type: ignore[attr-defined]
    assert not_expired is None
    expired = logicd._expire_text_send_runner(20.25)  # type: ignore[attr-defined]
    assert expired is not None
    assert expired["canceled"] is True
    assert expired["last_cancel_reason"] == "runner_timeout"
    assert expired["zero_report_sent"] is True
    assert output_writer.reports[-1] == HidState.null_report()

    unknown = await request('{"t":"NOPE"}')
    assert unknown[-1]["result"] == "error"


def main() -> None:
    asyncio.run(main_async())
    print("ok: logicd ctrl validation rejects malformed input")


if __name__ == "__main__":
    main()
