#!/usr/bin/env python3
"""Local smoke test for VialProtocol without Unix sockets or USB hardware."""
from __future__ import annotations

import json
import lzma
import os
import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from viald.protocol import (  # noqa: E402
    CMD_VIA_GET_KEYBOARD_VALUE,
    CMD_VIA_GET_LAYER_COUNT,
    CMD_VIA_GET_PROTOCOL_VERSION,
    CMD_VIA_KEYMAP_GET_BUFFER,
    CMD_VIA_KEYMAP_SET_BUFFER,
    CMD_VIA_LIGHTING_GET_VALUE,
    CMD_VIA_LIGHTING_SAVE,
    CMD_VIA_LIGHTING_SET_VALUE,
    CMD_VIA_MACRO_GET_BUFFER,
    CMD_VIA_MACRO_GET_BUFFER_SIZE,
    CMD_VIA_MACRO_GET_COUNT,
    CMD_VIA_MACRO_SET_BUFFER,
    CMD_VIA_SET_KEYCODE,
    CMD_VIA_VIAL_PREFIX,
    CMD_VIAL_GET_DEFINITION,
    CMD_VIAL_GET_ENCODER,
    CMD_VIAL_GET_KEYBOARD_ID,
    CMD_VIAL_LOCK,
    CMD_VIAL_SET_ENCODER,
    CMD_VIAL_GET_SIZE,
    CMD_VIAL_GET_UNLOCK_STATUS,
    CMD_VIAL_UNLOCK_POLL,
    CMD_VIAL_UNLOCK_START,
    CMD_VIAL_DYNAMIC_ENTRY_OP,
    CMD_VIAL_QMK_SETTINGS_GET,
    CMD_VIAL_QMK_SETTINGS_QUERY,
    CMD_VIAL_QMK_SETTINGS_RESET,
    CMD_VIAL_QMK_SETTINGS_SET,
    DYNAMIC_VIAL_COMBO_GET,
    DYNAMIC_VIAL_COMBO_SET,
    DYNAMIC_VIAL_GET_NUMBER_OF_ENTRIES,
    DYNAMIC_VIAL_KEY_OVERRIDE_GET,
    DYNAMIC_VIAL_KEY_OVERRIDE_SET,
    DYNAMIC_VIAL_TAP_DANCE_GET,
    DYNAMIC_VIAL_TAP_DANCE_SET,
    VIALRGB_GET_INFO,
    VIALRGB_GET_LED_INFO,
    VIALRGB_GET_MODE,
    VIALRGB_GET_NUMBER_LEDS,
    VIALRGB_GET_SUPPORTED,
    VIALRGB_DIRECT_FASTSET,
    VIALRGB_SET_MODE,
    VIA_SWITCH_MATRIX_STATE,
    VialProtocol,
)
from viald.keycode_codec import KeycodeCodec, VIAL_GUI_USER_BASE, VIAL_V5_USER_BASE  # noqa: E402
import viald.dynamic_protocol as dynamic_protocol  # noqa: E402
from vialrgb_effects import VIALRGB_SUPPORTED_EFFECTS  # noqa: E402

REPORT_SIZE = 32


class TestProtocol(VialProtocol):
    def __init__(self) -> None:
        super().__init__()
        self.layers_data: list[dict[str, str]] = [
            {
                "0,0": "KC_A",
                "0,1": "KC_ESC",
                "0,2": "KC_MS_U",
                "0,3": "KC_SHUTDOWN",
                "1,0": "MO(1)",
                "1,1": "TG(1)",
                "6,1": "KC_WH_D",
                "7,1": "KC_WH_U",
            },
            {
                "0,0": "KC_TRNS",
            },
        ]
        self.sent: list[dict[str, object]] = []
        self.pressed_matrix: list[list[int]] = [[0, 0], [0, 8], [2, 9]]

    def dispatch(self, packet: bytes) -> bytes:
        return super().dispatch(packet.ljust(REPORT_SIZE, b"\x00"))

    def _fetch_logicd_layers(self) -> list[dict[str, str]]:
        return self.layers_data

    def _send_logicd_message(self, msg: dict[str, object]) -> dict[str, object] | None:
        self.sent.append(msg)
        if msg.get("t") == "M":
            layer = int(msg["l"])
            key = f"{msg['r']},{msg['c']}"
            while len(self.layers_data) <= layer:
                self.layers_data.append({})
            self.layers_data[layer][key] = str(msg["a"])
            return {"t": "M", "result": "ok"}
        if msg.get("t") == "S":
            return {"t": "S", "result": "ok", "path": "/tmp/keymap.json"}
        if msg.get("t") == "LED":
            if msg.get("op") == "vialrgb_get":
                return {"t": "LED", "result": "ok", "mode": 6, "speed": 7, "h": 8, "s": 9, "v": 10}
            if msg.get("op") == "vialrgb_save":
                return {"t": "LED", "result": "ok", "path": "/tmp/led_state.json"}
            return {"t": "LED", "result": "ok"}
        if msg.get("t") == "K":
            return {"t": "matrix", "pressed": self.pressed_matrix}
        return None


class BrokenLogicdProtocol(TestProtocol):
    def __init__(self) -> None:
        super().__init__()
        self.matrix_response: dict[str, object] | None = {"t": "matrix", "pressed": "bad"}
        self.led_response: dict[str, object] | None = {
            "t": "LED",
            "result": "ok",
            "mode": 99999,
            "speed": -1,
            "h": 300,
            "s": "bad",
            "v": 10,
        }

    def _send_logicd_message(self, msg: dict[str, object]) -> dict[str, object] | None:
        self.sent.append(msg)
        if msg.get("t") == "K":
            return self.matrix_response
        if msg.get("t") == "LED" and msg.get("op") == "vialrgb_get":
            return self.led_response
        return None


def packet(*values: int) -> bytes:
    return bytes(values).ljust(REPORT_SIZE, b"\x00")


def read_supported_effects(proto: VialProtocol) -> list[int]:
    effects: list[int] = []
    requested = 0
    while requested < 0xFFFF:
        response = proto.dispatch(
            bytes([CMD_VIA_LIGHTING_GET_VALUE, VIALRGB_GET_SUPPORTED]) + struct.pack("<H", requested)
        )
        page: list[int] = []
        for idx in range(2, REPORT_SIZE, 2):
            value = struct.unpack("<H", response[idx:idx + 2])[0]
            if value == 0xFFFF:
                if page:
                    assert page == sorted(page), page
                    assert not effects or page[0] > effects[-1], (effects[-1], page)
                    effects.extend(page)
                return effects
            if value != 0:
                page.append(value)
        assert page, f"VialRGB supported effects page did not include terminator after {requested}"
        assert page == sorted(page), page
        assert not effects or page[0] > effects[-1], (effects[-1], page)
        effects.extend(page)
        requested = page[-1]
    raise AssertionError("VialRGB supported effects list did not terminate")


def read_keymap(proto: TestProtocol, layer: int, row: int, col: int) -> int:
    offset = (layer * proto.rows * proto.cols + row * proto.cols + col) * 2
    response = proto.dispatch(bytes([CMD_VIA_KEYMAP_GET_BUFFER]) + struct.pack(">HB", offset, 2))
    assert response[:4] == bytes([CMD_VIA_KEYMAP_GET_BUFFER]) + struct.pack(">HB", offset, 2)
    return struct.unpack(">H", response[4:6])[0]


def read_encoder(proto: TestProtocol, layer: int, encoder: int, action: int) -> int:
    matrix_size = proto.layers * proto.rows * proto.cols * 2
    offset = matrix_size + (layer * len(proto.encoder_map) * 2 + encoder * 2 + action) * 2
    response = proto.dispatch(bytes([CMD_VIA_KEYMAP_GET_BUFFER]) + struct.pack(">HB", offset, 2))
    assert response[:4] == bytes([CMD_VIA_KEYMAP_GET_BUFFER]) + struct.pack(">HB", offset, 2)
    return struct.unpack(">H", response[4:6])[0]


def main() -> None:
    tmp_dir = tempfile.TemporaryDirectory()
    config_path = Path(tmp_dir.name) / "config.json"
    config_path.write_text(json.dumps({
        "settings": {
            "interaction": {
                "tap_dance_term": 0.2,
                "tapping_term": 0.18,
                "hold_on_other_key_press": True,
                "combo_term": 0.04,
                "combos": [
                    {"keys": [[0, 0], [0, 1]], "action": "KC_TAB"}
                ],
                "tap_dances": {
                    "TD0": {"1": "KC_A", "hold": "KC_LSFT", "2": "KC_ESC", "tap_hold": "KC_LCTL"}
                },
                "key_overrides": [
                    {"trigger": "KC_LSFT", "key": "KC_1", "replacement": "KC_ESC"}
                ],
            }
        }
    }), encoding="utf-8")
    old_config_path = dynamic_protocol.CONFIG_JSON_PATH
    old_fallback_path = dynamic_protocol.FALLBACK_CONFIG_JSON_PATH
    old_reload = os.environ.get("VIALD_RELOAD_LOGICD")
    dynamic_protocol.CONFIG_JSON_PATH = config_path
    dynamic_protocol.FALLBACK_CONFIG_JSON_PATH = config_path
    os.environ["VIALD_RELOAD_LOGICD"] = "0"
    proto = TestProtocol()
    codec = KeycodeCodec()
    kc_shutdown = codec.action_to_vial("KC_SHUTDOWN")
    rgb_tog = codec.action_to_vial("RGB_TOG")
    rgb_mod = codec.action_to_vial("RGB_MOD")
    rgb_rmod = codec.action_to_vial("RGB_RMOD")
    rgb_tog_gui = VIAL_GUI_USER_BASE + (rgb_tog - VIAL_V5_USER_BASE)

    version = proto.dispatch(packet(CMD_VIA_GET_PROTOCOL_VERSION))
    assert version[:3] == b"\x01\x00\x09"

    layer_count = proto.dispatch(packet(CMD_VIA_GET_LAYER_COUNT))
    assert layer_count[:2] == bytes([CMD_VIA_GET_LAYER_COUNT, 2])

    layout_options = proto.dispatch(packet(CMD_VIA_GET_KEYBOARD_VALUE, 0x02))
    assert layout_options[:6] == bytes([CMD_VIA_GET_KEYBOARD_VALUE, 0x02, 0, 0, 0, 0])

    assert proto.dispatch(packet(CMD_VIA_MACRO_GET_COUNT))[:2] == bytes([CMD_VIA_MACRO_GET_COUNT, 8])
    assert proto.dispatch(packet(CMD_VIA_MACRO_GET_BUFFER_SIZE))[:3] == bytes(
        [CMD_VIA_MACRO_GET_BUFFER_SIZE, 2, 0]
    )
    proto.dispatch(
        bytes([CMD_VIA_MACRO_SET_BUFFER])
        + struct.pack(">HB", 0, 6)
        + b"Hi\x00Bye"
    )
    macro_resp = proto.dispatch(bytes([CMD_VIA_MACRO_GET_BUFFER]) + struct.pack(">HB", 0, 6))
    assert macro_resp[:4] == bytes([CMD_VIA_MACRO_GET_BUFFER]) + struct.pack(">HB", 0, 6)
    assert macro_resp[4:10] == b"Hi\x00Bye"
    stored_macros = json.loads(config_path.read_text(encoding="utf-8"))["macros"]
    assert stored_macros["VIAL0"] == ["Hi"]
    assert stored_macros["VIAL1"] == ["Bye"]
    proto.dispatch(
        bytes([CMD_VIA_MACRO_SET_BUFFER])
        + struct.pack(">HB", 0, 10)
        + b"\x01\x02\x04\x01\x04\x32\x00\x01\x03\x04"
    )
    stored_macros = json.loads(config_path.read_text(encoding="utf-8"))["macros"]
    assert stored_macros["VIAL0"] == ["{KC_DOWN:KC_A}", "{DELAY:50}", "{KC_UP:KC_A}"]

    identity = proto.dispatch(packet(CMD_VIA_VIAL_PREFIX, CMD_VIAL_GET_KEYBOARD_ID))
    vial_protocol, uid = struct.unpack("<IQ", identity[:12])
    assert vial_protocol == 5
    assert uid == proto.uid

    qmk_settings = proto.dispatch(packet(CMD_VIA_VIAL_PREFIX, CMD_VIAL_QMK_SETTINGS_QUERY, 0, 0))
    assert [struct.unpack("<H", qmk_settings[idx:idx + 2])[0] for idx in range(0, 8, 2)] == [2, 7, 23, 0xFFFF]
    combo_term = proto.dispatch(
        bytes([CMD_VIA_VIAL_PREFIX, CMD_VIAL_QMK_SETTINGS_GET]) + struct.pack("<H", 2)
    )
    assert combo_term[:3] == bytes([0, 40, 0])
    tapping_term = proto.dispatch(
        bytes([CMD_VIA_VIAL_PREFIX, CMD_VIAL_QMK_SETTINGS_GET]) + struct.pack("<H", 7)
    )
    assert tapping_term[:3] == bytes([0, 180, 0])
    hold_on_other = proto.dispatch(
        bytes([CMD_VIA_VIAL_PREFIX, CMD_VIAL_QMK_SETTINGS_GET]) + struct.pack("<H", 23)
    )
    assert hold_on_other[:2] == bytes([0, 1])
    proto.dispatch(
        bytes([CMD_VIA_VIAL_PREFIX, CMD_VIAL_QMK_SETTINGS_SET]) + struct.pack("<H", 2) + struct.pack("<H", 55)
    )
    stored_config = json.loads(config_path.read_text(encoding="utf-8"))
    assert stored_config["settings"]["interaction"]["combo_term"] == 0.055

    dynamic_counts = proto.dispatch(
        packet(CMD_VIA_VIAL_PREFIX, CMD_VIAL_DYNAMIC_ENTRY_OP, DYNAMIC_VIAL_GET_NUMBER_OF_ENTRIES)
    )
    assert dynamic_counts[:4] == bytes([4, 4, 4, 0])
    tap_dance = proto.dispatch(packet(CMD_VIA_VIAL_PREFIX, CMD_VIAL_DYNAMIC_ENTRY_OP, DYNAMIC_VIAL_TAP_DANCE_GET, 0))
    assert tap_dance[0] == 0
    assert struct.unpack("<HHHHH", tap_dance[1:11]) == (0x0004, 0x00E1, 0x0029, 0x00E0, 200)
    combo = proto.dispatch(packet(CMD_VIA_VIAL_PREFIX, CMD_VIAL_DYNAMIC_ENTRY_OP, DYNAMIC_VIAL_COMBO_GET, 0))
    assert combo[0] == 0
    assert struct.unpack("<HHHHH", combo[1:11]) == (0x0004, 0x0029, 0, 0, 0x002B)
    key_override = proto.dispatch(
        packet(CMD_VIA_VIAL_PREFIX, CMD_VIAL_DYNAMIC_ENTRY_OP, DYNAMIC_VIAL_KEY_OVERRIDE_GET, 0)
    )
    assert key_override[0] == 0
    assert struct.unpack("<HHHBBBB", key_override[1:11]) == (0x001E, 0x0029, 0xFFFF, 0x02, 0, 0, 0x83)
    proto.dispatch(
        bytes([CMD_VIA_VIAL_PREFIX, CMD_VIAL_DYNAMIC_ENTRY_OP, DYNAMIC_VIAL_TAP_DANCE_SET, 1])
        + struct.pack("<HHHHH", 0x0005, 0x00E1, 0x002B, 0x00E0, 250)
    )
    stored_config = json.loads(config_path.read_text(encoding="utf-8"))
    stored_interaction = stored_config["settings"]["interaction"]
    assert stored_interaction["tap_dance_term"] == 0.25
    assert stored_interaction["tap_dances"]["TD1"] == {
        "1": "KC_B",
        "hold": "KC_LSHIFT",
        "2": "KC_TAB",
        "tap_hold": "KC_LCTRL",
        "term": 0.25,
    }
    proto.dispatch(
        bytes([CMD_VIA_VIAL_PREFIX, CMD_VIAL_DYNAMIC_ENTRY_OP, DYNAMIC_VIAL_COMBO_SET, 1])
        + struct.pack("<HHHHH", 0x0004, 0x0029, 0, 0, 0x002B)
    )
    stored_config = json.loads(config_path.read_text(encoding="utf-8"))
    assert stored_config["settings"]["interaction"]["combos"][1] == {
        "keys": [[0, 0], [0, 1]],
        "action": "KC_TAB",
    }
    proto.dispatch(
        bytes([CMD_VIA_VIAL_PREFIX, CMD_VIAL_DYNAMIC_ENTRY_OP, DYNAMIC_VIAL_KEY_OVERRIDE_SET, 1])
        + struct.pack("<HHHBBBB", 0x001F, 0x002B, 0x0003, 0x01, 0x02, 0x02, 0x83)
    )
    stored_config = json.loads(config_path.read_text(encoding="utf-8"))
    assert stored_config["settings"]["interaction"]["key_overrides"][1] == {
        "trigger": "KC_LCTL",
        "negative_trigger": "KC_LSFT",
        "key": "KC_2",
        "replacement": "KC_TAB",
        "layers": 0x0003,
        "suppressed_mods": 0x02,
        "options": 0x83,
    }
    proto.dispatch(packet(CMD_VIA_VIAL_PREFIX, CMD_VIAL_QMK_SETTINGS_RESET))
    stored_config = json.loads(config_path.read_text(encoding="utf-8"))
    assert stored_config["settings"]["interaction"]["combo_term"] == 0.05
    assert stored_config["settings"]["interaction"]["tapping_term"] == 0.2
    assert stored_config["settings"]["interaction"]["hold_on_other_key_press"] is True

    size_resp = proto.dispatch(packet(CMD_VIA_VIAL_PREFIX, CMD_VIAL_GET_SIZE))
    definition_size = struct.unpack("<I", size_resp[:4])[0]
    payload = bytearray()
    block = 0
    while len(payload) < definition_size:
        request = bytes([CMD_VIA_VIAL_PREFIX, CMD_VIAL_GET_DEFINITION]) + struct.pack("<I", block)
        payload.extend(proto.dispatch(request))
        block += 1
    definition = json.loads(lzma.decompress(bytes(payload[:definition_size])))
    assert definition["name"] in {
        "CQA02303v5 Keyboard",
        "CQA02303v5-40 Touch Panel (waveshare-8.8)",
        "CQA02303v5-40 Touch Panel (osoyoo-4.3)",
    }
    assert int(definition["uid"]) == proto.uid
    assert "labels" not in definition.get("layouts", {})

    unlock = proto.dispatch(packet(CMD_VIA_VIAL_PREFIX, CMD_VIAL_GET_UNLOCK_STATUS))
    assert unlock[:2] == b"\x00\x00"
    unlock_keys = definition.get("vial", {}).get("unlockKeys", [])
    expected_unlock = bytes(value for pair in unlock_keys[:15] for value in pair)
    assert unlock[2:2 + len(expected_unlock)] == expected_unlock

    matrix = proto.dispatch(packet(CMD_VIA_GET_KEYBOARD_VALUE, VIA_SWITCH_MATRIX_STATE))
    assert matrix[:2] == bytes([CMD_VIA_GET_KEYBOARD_VALUE, VIA_SWITCH_MATRIX_STATE])
    row_size = (proto.cols + 7) // 8
    row0 = matrix[2:2 + row_size]
    row2 = matrix[2 + 2 * row_size:2 + 3 * row_size]
    assert row0 == bytes([0x01, 0x01])
    assert row2 == bytes([0x02, 0x00])

    proto.pressed_matrix = []
    proto.dispatch(packet(CMD_VIA_VIAL_PREFIX, CMD_VIAL_UNLOCK_START))
    poll = proto.dispatch(packet(CMD_VIA_VIAL_PREFIX, CMD_VIAL_UNLOCK_POLL))
    assert poll[:3] == bytes([0, 1, 25])
    proto.pressed_matrix = unlock_keys
    for _ in range(25):
        poll = proto.dispatch(packet(CMD_VIA_VIAL_PREFIX, CMD_VIAL_UNLOCK_POLL))
    assert poll[:3] == bytes([1, 0, 0])
    assert proto.dispatch(packet(CMD_VIA_VIAL_PREFIX, CMD_VIAL_GET_UNLOCK_STATUS))[:2] == b"\x01\x00"
    proto.dispatch(packet(CMD_VIA_VIAL_PREFIX, CMD_VIAL_LOCK))
    assert proto.dispatch(packet(CMD_VIA_VIAL_PREFIX, CMD_VIAL_GET_UNLOCK_STATUS))[:2] == b"\x00\x00"

    assert read_keymap(proto, 0, 0, 0) == 0x0004
    assert read_keymap(proto, 0, 0, 1) == 0x0029
    assert read_keymap(proto, 0, 0, 2) == 0x00F0
    assert read_keymap(proto, 0, 0, 3) == kc_shutdown
    assert read_keymap(proto, 0, 1, 0) == 0x5101
    assert read_keymap(proto, 0, 1, 1) == 0x5301
    assert read_keymap(proto, 1, 0, 0) == 0x0001
    if proto.encoder_map:
        assert read_encoder(proto, 0, 0, 0) == 0x00FA  # encoder 0 CCW -> KC_WH_D at 6,1
        assert read_encoder(proto, 0, 0, 1) == 0x00F9  # encoder 0 CW  -> KC_WH_U at 7,1
        get_encoder = proto.dispatch(packet(CMD_VIA_VIAL_PREFIX, CMD_VIAL_GET_ENCODER, 0, 0))
        assert struct.unpack(">HH", get_encoder[:4]) == (0x00FA, 0x00F9)

    set_a_to_b = bytes([CMD_VIA_SET_KEYCODE, 0, 0, 0]) + struct.pack(">H", 0x0005)
    proto.dispatch(set_a_to_b)
    assert proto.layers_data[0]["0,0"] == "KC_B"
    assert proto.sent[-2:] == [
        {"t": "M", "l": 0, "r": 0, "c": 0, "a": "KC_B"},
        {"t": "S"},
    ]
    assert read_keymap(proto, 0, 0, 0) == 0x0005

    set_b_to_rgb = bytes([CMD_VIA_SET_KEYCODE, 0, 0, 0]) + struct.pack(">H", rgb_tog)
    proto.dispatch(set_b_to_rgb)
    assert proto.layers_data[0]["0,0"] == "RGB_TOG"
    assert proto.sent[-2:] == [
        {"t": "M", "l": 0, "r": 0, "c": 0, "a": "RGB_TOG"},
        {"t": "S"},
    ]
    assert read_keymap(proto, 0, 0, 0) == rgb_tog

    set_rgb_gui_value = bytes([CMD_VIA_SET_KEYCODE, 0, 0, 0]) + struct.pack(">H", rgb_tog_gui)
    proto.dispatch(set_rgb_gui_value)
    assert proto.layers_data[0]["0,0"] == "RGB_TOG"
    assert proto.sent[-2:] == [
        {"t": "M", "l": 0, "r": 0, "c": 0, "a": "RGB_TOG"},
        {"t": "S"},
    ]
    assert read_keymap(proto, 0, 0, 0) == rgb_tog

    vial_lt1_1 = 0x4000 | (1 << 8) | 0x001E
    set_rgb_to_lt = bytes([CMD_VIA_SET_KEYCODE, 0, 0, 0]) + struct.pack(">H", vial_lt1_1)
    proto.dispatch(set_rgb_to_lt)
    assert proto.layers_data[0]["0,0"] == "LT(1,KC_1)"
    assert proto.sent[-2:] == [
        {"t": "M", "l": 0, "r": 0, "c": 0, "a": "LT(1,KC_1)"},
        {"t": "S"},
    ]
    assert read_keymap(proto, 0, 0, 0) == vial_lt1_1

    offset = (0 * proto.rows * proto.cols + 0 * proto.cols + 1) * 2
    set_buffer = (
        bytes([CMD_VIA_KEYMAP_SET_BUFFER])
        + struct.pack(">HB", offset, 4)
        + struct.pack(">HH", rgb_mod, rgb_rmod)
    )
    proto.dispatch(set_buffer)
    assert proto.layers_data[0]["0,1"] == "RGB_MOD"
    assert proto.layers_data[0]["0,2"] == "RGB_RMOD"
    assert proto.sent[-3:] == [
        {"t": "M", "l": 0, "r": 0, "c": 1, "a": "RGB_MOD"},
        {"t": "M", "l": 0, "r": 0, "c": 2, "a": "RGB_RMOD"},
        {"t": "S"},
    ]
    assert read_keymap(proto, 0, 0, 1) == rgb_mod
    assert read_keymap(proto, 0, 0, 2) == rgb_rmod

    encoder_offset = proto.layers * proto.rows * proto.cols * 2
    if proto.encoder_map:
        set_encoder = (
            bytes([CMD_VIA_KEYMAP_SET_BUFFER])
            + struct.pack(">HB", encoder_offset, 4)
            + struct.pack(">HH", 0x00F0, 0x00F3)
        )
        proto.dispatch(set_encoder)
        assert proto.layers_data[0]["6,1"] == "KC_MS_U"
        assert proto.layers_data[0]["7,1"] == "KC_MS_R"
        assert proto.sent[-3:] == [
            {"t": "M", "l": 0, "r": 6, "c": 1, "a": "KC_MS_U"},
            {"t": "M", "l": 0, "r": 7, "c": 1, "a": "KC_MS_R"},
            {"t": "S"},
        ]
        assert read_encoder(proto, 0, 0, 0) == 0x00F0
        assert read_encoder(proto, 0, 0, 1) == 0x00F3

        set_encoder_cw = (
            bytes([CMD_VIA_VIAL_PREFIX, CMD_VIAL_SET_ENCODER, 0, 0, 1])
            + struct.pack(">H", 0x00F2)
        )
        proto.dispatch(set_encoder_cw)
        assert proto.layers_data[0]["7,1"] == "KC_MS_L"
        assert proto.sent[-2:] == [
            {"t": "M", "l": 0, "r": 7, "c": 1, "a": "KC_MS_L"},
            {"t": "S"},
        ]
        get_encoder = proto.dispatch(packet(CMD_VIA_VIAL_PREFIX, CMD_VIAL_GET_ENCODER, 0, 0))
        assert struct.unpack(">HH", get_encoder[:4]) == (0x00F0, 0x00F2)

    unsupported = bytes([CMD_VIA_SET_KEYCODE, 0, 0, 0]) + struct.pack(">H", 0x7FFF)
    before = list(proto.sent)
    proto.dispatch(unsupported)
    assert proto.sent == before

    info = proto.dispatch(packet(CMD_VIA_LIGHTING_GET_VALUE, VIALRGB_GET_INFO))
    assert info[:5] == bytes([CMD_VIA_LIGHTING_GET_VALUE, VIALRGB_GET_INFO, 1, 0, 255])

    assert read_supported_effects(proto) == list(VIALRGB_SUPPORTED_EFFECTS)

    led_count_resp = proto.dispatch(packet(CMD_VIA_LIGHTING_GET_VALUE, VIALRGB_GET_NUMBER_LEDS))
    led_count = struct.unpack("<H", led_count_resp[2:4])[0]
    assert led_count > 0

    led_info = proto.dispatch(
        bytes([CMD_VIA_LIGHTING_GET_VALUE, VIALRGB_GET_LED_INFO]) + struct.pack("<H", 0)
    )
    assert led_info[:2] == bytes([CMD_VIA_LIGHTING_GET_VALUE, VIALRGB_GET_LED_INFO])
    assert led_info[4] == 0x04

    set_rgb = bytes([CMD_VIA_LIGHTING_SET_VALUE, VIALRGB_SET_MODE]) + struct.pack("<HBBBB", 2, 64, 3, 4, 5)
    proto.dispatch(set_rgb)
    assert proto.sent[-1] == {"t": "LED", "op": "vialrgb", "mode": 2, "speed": 64, "h": 3, "s": 4, "v": 5}
    mode = proto.dispatch(packet(CMD_VIA_LIGHTING_GET_VALUE, VIALRGB_GET_MODE))
    assert proto.sent[-1] == {"t": "LED", "op": "vialrgb_get"}
    assert struct.unpack("<HBBBB", mode[2:8]) == (6, 7, 8, 9, 10)

    proto.dispatch(packet(CMD_VIA_LIGHTING_SAVE))
    assert proto.sent[-1] == {"t": "LED", "op": "vialrgb_save"}

    direct = (
        bytes([CMD_VIA_LIGHTING_SET_VALUE, VIALRGB_DIRECT_FASTSET])
        + struct.pack("<HB", 2, 2)
        + bytes([10, 20, 30, 40, 50, 60])
    )
    proto.dispatch(direct)
    assert proto.sent[-1] == {
        "t": "LED",
        "op": "vialrgb_direct",
        "first": 2,
        "pixels": [[10, 20, 30], [40, 50, 60]],
    }

    invalid = BrokenLogicdProtocol()
    invalid.dispatch(packet(0x99))
    invalid.dispatch(packet(CMD_VIA_VIAL_PREFIX, 0x99))
    invalid.dispatch(bytes([CMD_VIA_VIAL_PREFIX, CMD_VIAL_GET_DEFINITION]) + struct.pack("<I", 9999))
    invalid.dispatch(bytes([CMD_VIA_KEYMAP_GET_BUFFER]) + struct.pack(">HB", 0xFFFF, 2))
    invalid.dispatch(bytes([CMD_VIA_SET_KEYCODE, 0, invalid.rows, 0]) + struct.pack(">H", 0x0004))
    assert invalid.sent == []

    bad_matrix = invalid.dispatch(packet(CMD_VIA_GET_KEYBOARD_VALUE, VIA_SWITCH_MATRIX_STATE))
    assert bad_matrix[:2] == bytes([CMD_VIA_GET_KEYBOARD_VALUE, VIA_SWITCH_MATRIX_STATE])
    assert bad_matrix[2:] == bytes(REPORT_SIZE - 2)

    cached_rgb = invalid.dispatch(packet(CMD_VIA_LIGHTING_GET_VALUE, VIALRGB_GET_MODE))
    assert struct.unpack("<HBBBB", cached_rgb[2:8]) == (2, 128, 0, 0, 128)

    invalid.led_response = {"t": "LED", "result": "ok", "mode": 99999, "speed": -1, "h": 300, "s": 256, "v": -5}
    clamped_rgb = invalid.dispatch(packet(CMD_VIA_LIGHTING_GET_VALUE, VIALRGB_GET_MODE))
    assert struct.unpack("<HBBBB", clamped_rgb[2:8]) == (65535, 0, 255, 255, 0)

    invalid.dispatch(
        bytes([CMD_VIA_LIGHTING_SET_VALUE, VIALRGB_DIRECT_FASTSET])
        + struct.pack("<HB", 9999, 12)
        + bytes([1, 2, 3] * 9)
    )

    dynamic_protocol.CONFIG_JSON_PATH = old_config_path
    dynamic_protocol.FALLBACK_CONFIG_JSON_PATH = old_fallback_path
    if old_reload is None:
        os.environ.pop("VIALD_RELOAD_LOGICD", None)
    else:
        os.environ["VIALD_RELOAD_LOGICD"] = old_reload
    tmp_dir.cleanup()

    print("ok: local Vial protocol dispatch is coherent")


if __name__ == "__main__":
    main()
