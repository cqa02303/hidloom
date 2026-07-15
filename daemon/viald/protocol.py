"""Minimal Vial/VIA protocol dispatcher."""
from __future__ import annotations

import json
import logging
import lzma
import os
import socket
import struct
from pathlib import Path

from .keycode_codec import KeycodeCodec
from .dynamic_protocol import VialDynamicMixin
from .keymap_protocol import VialKeymapMixin
from .lighting_protocol import VialLightingMixin
from .protocol_defs import *  # noqa: F403
from .unlock_protocol import VialUnlockMixin

log = logging.getLogger(__name__)


def _pad(payload: bytes) -> bytes:
    return payload[:REPORT_SIZE].ljust(REPORT_SIZE, b"\x00")


class VialProtocol(VialKeymapMixin, VialLightingMixin, VialUnlockMixin, VialDynamicMixin):
    def __init__(self, vial_json_path: Path = VIAL_JSON_PATH) -> None:
        self._definition = json.loads(vial_json_path.read_text(encoding="utf-8"))
        self._definition_payload = lzma.compress(
            json.dumps(self._definition, separators=(",", ":")).encode("utf-8")
        )
        matrix = self._definition["matrix"]
        self.rows = int(matrix["rows"])
        self.cols = int(matrix["cols"])
        self.uid = int(self._definition["uid"])
        self.layers = DEFAULT_LAYER_COUNT
        self._codec = KeycodeCodec()
        self.encoder_map = self._load_encoder_map(vial_json_path)
        self.tap_dance_count = DEFAULT_TAP_DANCE_COUNT
        self.combo_count = DEFAULT_COMBO_COUNT
        self.key_override_count = DEFAULT_KEY_OVERRIDE_COUNT
        self.macro_count = DEFAULT_MACRO_COUNT
        self.macro_buffer_size = DEFAULT_MACRO_BUFFER_SIZE
        self.rgb_mode = 2
        self.rgb_speed = 128
        self.rgb_hsv = (0, 0, 128)
        self._led_info = self._load_led_info(LEDD_JSON_PATH)
        self.unlock_keys = self._load_unlock_keys()
        self.unlocked = not self.unlock_keys or os.environ.get("VIALD_UNLOCKED", "0") in {"1", "true", "True"}
        self.unlock_in_progress = False
        self.unlock_counter = 0

    def dispatch(self, packet: bytes) -> bytes:
        if not packet:
            log.warning("empty VIA packet ignored")
            return bytes(REPORT_SIZE)
        if len(packet) < REPORT_SIZE:
            log.warning("short VIA packet: len=%d payload=%s", len(packet), packet.hex())
            packet = packet.ljust(REPORT_SIZE, b"\x00")

        command = packet[0]
        if command == CMD_VIA_GET_PROTOCOL_VERSION:
            return _pad(bytes([command]) + struct.pack(">H", VIA_PROTOCOL_VERSION))
        if command == CMD_VIA_GET_KEYBOARD_VALUE:
            return self._get_keyboard_value(packet)
        if command == CMD_VIA_SET_KEYCODE:
            return self._set_keycode(packet)
        if command == CMD_VIA_LIGHTING_SET_VALUE:
            return self._lighting_set_value(packet)
        if command == CMD_VIA_GET_LAYER_COUNT:
            layers = self._fetch_logicd_layers()
            if layers:
                self.layers = len(layers)
            return _pad(bytes([command, self.layers]))
        if command == CMD_VIA_MACRO_GET_COUNT:
            return self._macro_get_count()
        if command == CMD_VIA_MACRO_GET_BUFFER_SIZE:
            return self._macro_get_buffer_size()
        if command == CMD_VIA_MACRO_GET_BUFFER:
            return self._macro_get_buffer(packet)
        if command == CMD_VIA_MACRO_SET_BUFFER:
            return self._macro_set_buffer(packet)
        if command == CMD_VIA_KEYMAP_GET_BUFFER:
            return self._get_keymap_buffer(packet)
        if command == CMD_VIA_KEYMAP_SET_BUFFER:
            return self._set_keymap_buffer(packet)
        if command == CMD_VIA_LIGHTING_GET_VALUE:
            return self._lighting_get_value(packet)
        if command == CMD_VIA_LIGHTING_SAVE:
            self._send_logicd_message({"t": "LED", "op": "vialrgb_save"})
            return bytes(REPORT_SIZE)
        if command == CMD_VIA_VIAL_PREFIX:
            return self._dispatch_vial(packet)
        log.warning("unsupported VIA command: 0x%02x payload=%s", command, packet[:REPORT_SIZE].hex())
        return bytes(REPORT_SIZE)

    def _dispatch_vial(self, packet: bytes) -> bytes:
        subcommand = packet[1]
        if subcommand == CMD_VIAL_GET_KEYBOARD_ID:
            return _pad(struct.pack("<IQ", VIAL_PROTOCOL_VERSION, self.uid))
        if subcommand == CMD_VIAL_GET_SIZE:
            return _pad(struct.pack("<I", len(self._definition_payload)))
        if subcommand == CMD_VIAL_GET_DEFINITION:
            block = struct.unpack("<I", packet[2:6])[0]
            start = block * REPORT_SIZE
            if start >= len(self._definition_payload):
                log.warning(
                    "VIAL_GET_DEFINITION out-of-range: block=%d start=%d size=%d",
                    block, start, len(self._definition_payload),
                )
            return _pad(self._definition_payload[start:start + REPORT_SIZE])
        if subcommand == CMD_VIAL_GET_ENCODER:
            return self._get_encoder(packet)
        if subcommand == CMD_VIAL_SET_ENCODER:
            return self._set_encoder(packet)
        if subcommand == CMD_VIAL_GET_UNLOCK_STATUS:
            return self._get_unlock_status()
        if subcommand == CMD_VIAL_UNLOCK_START:
            return self._unlock_start()
        if subcommand == CMD_VIAL_UNLOCK_POLL:
            return self._unlock_poll()
        if subcommand == CMD_VIAL_LOCK:
            return self._lock()
        if subcommand == CMD_VIAL_QMK_SETTINGS_QUERY:
            return self._qmk_settings_query(packet)
        if subcommand == CMD_VIAL_QMK_SETTINGS_GET:
            return self._qmk_settings_get(packet)
        if subcommand == CMD_VIAL_QMK_SETTINGS_SET:
            return self._qmk_settings_set(packet)
        if subcommand == CMD_VIAL_QMK_SETTINGS_RESET:
            return self._qmk_settings_reset()
        if subcommand == CMD_VIAL_DYNAMIC_ENTRY_OP:
            return self._dispatch_dynamic_entry_op(packet)
        log.warning("unsupported Vial subcommand: 0x%02x payload=%s", subcommand, packet[:REPORT_SIZE].hex())
        return bytes(REPORT_SIZE)








    def _get_keyboard_value(self, packet: bytes) -> bytes:
        if packet[1] == VIA_SWITCH_MATRIX_STATE:
            return self._get_switch_matrix_state(packet[1])
        if packet[1] != 0x02:
            log.warning("unsupported keyboard value id: 0x%02x payload=%s", packet[1], packet[:REPORT_SIZE].hex())
        # layout options query (value id 0x02) and unknown values -> options=0
        return _pad(bytes([CMD_VIA_GET_KEYBOARD_VALUE, packet[1]]) + struct.pack(">I", 0))

    def _get_switch_matrix_state(self, value_id: int) -> bytes:
        row_size = (self.cols + 7) // 8
        matrix = bytearray(self.rows * row_size)
        result = self._send_logicd_message({"t": "K"})
        pressed = result.get("pressed", []) if isinstance(result, dict) else []
        if not isinstance(pressed, list):
            log.warning("matrix state ignored: malformed pressed field %r", pressed)
            pressed = []

        for item in pressed:
            try:
                row, col = int(item[0]), int(item[1])
            except (TypeError, ValueError, IndexError):
                log.warning("matrix state ignored: malformed pressed item %r", item)
                continue
            if not (0 <= row < self.rows and 0 <= col < self.cols):
                log.warning("matrix state ignored: out-of-range row=%d col=%d", row, col)
                continue
            offset = row * row_size + (row_size - 1 - (col // 8))
            matrix[offset] |= 1 << (col % 8)

        return _pad(bytes([CMD_VIA_GET_KEYBOARD_VALUE, value_id]) + bytes(matrix))


    def _fetch_logicd_layers(self) -> list[dict[str, str]]:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                sock.connect(CTRLD_SOCKET_PATH)
                sock.sendall(b'{"t":"G"}\n')
                data = b""
                while not data.endswith(b"\n"):
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    data += chunk
            msg = json.loads(data.decode("utf-8"))
            layers = msg.get("layers", [])
            if not isinstance(layers, list):
                log.warning("logicd keymap ignored: layers is not list result=%r", msg)
                return []
            return layers
        except (OSError, TimeoutError, json.JSONDecodeError) as exc:
            log.warning("logicd keymap fetch failed: %s", exc)
            return []




    def _send_logicd_message(self, msg: dict[str, object]) -> dict[str, object] | None:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                sock.connect(CTRLD_SOCKET_PATH)
                sock.sendall((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
                data = b""
                while not data.endswith(b"\n"):
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    data += chunk
            return json.loads(data.decode("utf-8")) if data else None
        except (OSError, TimeoutError, json.JSONDecodeError) as exc:
            log.warning("logicd request failed: msg=%r error=%s", msg, exc)
            return None
