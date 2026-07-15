"""VIA/Vial keymap and encoder command handlers."""

from __future__ import annotations

import json
import logging
import struct
from pathlib import Path

from .protocol_defs import REPORT_SIZE, SAVE_ON_SET

log = logging.getLogger(__name__)


def _pad(payload: bytes) -> bytes:
    return payload[:REPORT_SIZE].ljust(REPORT_SIZE, b"\x00")


class VialKeymapMixin:
    def _load_encoder_map(self, vial_json_path: Path) -> list[tuple[tuple[int, int], tuple[int, int]]]:
        """Return encoder action targets as ``[(ccw_row_col, cw_row_col), ...]``.

        Vial stores encoder keycodes after the matrix keymap buffer.  The visual
        ``e`` slots in vial.json carry only encoder index/action, so we map them
        back to the matrix-backed A/B positions used by logicd.
        """
        keymap_path = vial_json_path.with_name("keymap.json")
        try:
            keymap = json.loads(keymap_path.read_text(encoding="utf-8"))
        except OSError as exc:
            log.warning("encoder map unavailable: cannot read %s: %s", keymap_path, exc)
            return []
        except json.JSONDecodeError as exc:
            log.warning("encoder map unavailable: invalid %s: %s", keymap_path, exc)
            return []

        explicit = keymap.get("encoders")
        if isinstance(explicit, list):
            result: list[tuple[tuple[int, int], tuple[int, int]]] = []
            for idx, item in enumerate(explicit):
                try:
                    a = (int(item["a"][0]), int(item["a"][1]))
                    b = (int(item["b"][0]), int(item["b"][1]))
                except (TypeError, ValueError, KeyError, IndexError):
                    log.warning("encoder map ignored: malformed explicit encoder index=%d item=%r", idx, item)
                    continue
                result.append((b, a))
            if result:
                log.info("Loaded %d Vial encoder map item(s): %s", len(result), result)
            return result

        layout_def = keymap.get("_layout_def", {})
        found: dict[str, dict[str, tuple[int, int]]] = {}
        if isinstance(layout_def, dict):
            for group, entries in layout_def.items():
                if not isinstance(group, str) or not group.startswith("encoder"):
                    continue
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if not isinstance(entry, list) or len(entry) < 3:
                        continue
                    try:
                        row, col, label = int(entry[0]), int(entry[1]), str(entry[2])
                    except (TypeError, ValueError):
                        log.warning("encoder map entry ignored: malformed entry=%r", entry)
                        continue
                    if label.endswith("A"):
                        found.setdefault(label[:-1], {})["a"] = (row, col)
                    elif label.endswith("B"):
                        found.setdefault(label[:-1], {})["b"] = (row, col)

        result = []
        for name in sorted(found):
            item = found[name]
            if "a" in item and "b" in item:
                result.append((item["b"], item["a"]))
            else:
                log.warning("encoder map ignored: incomplete A/B binding for %s: %r", name, item)
        if result:
            log.info("Loaded %d Vial encoder map item(s): %s", len(result), result)
        return result




    def _encoder_target(self, encoder_idx: int, clockwise: bool) -> tuple[int, int] | None:
        if not (0 <= encoder_idx < len(self.encoder_map)):
            return None
        ccw, cw = self.encoder_map[encoder_idx]
        return cw if clockwise else ccw
    def _get_encoder(self, packet: bytes) -> bytes:
        layer = int(packet[2])
        encoder_idx = int(packet[3])
        if not (0 <= encoder_idx < len(self.encoder_map)):
            log.warning(
                "VIAL_GET_ENCODER ignored: encoder out-of-range layer=%d encoder=%d",
                layer, encoder_idx,
            )
            return _pad(struct.pack(">HH", 0, 0))
        layers = self._fetch_logicd_layers()
        if layers:
            self.layers = max(1, len(layers))
        if not (0 <= layer < len(layers)):
            return _pad(struct.pack(">HH", 0, 0))
        payload = bytearray()
        for row, col in self.encoder_map[encoder_idx]:
            action = layers[layer].get(f"{row},{col}", "KC_NONE")
            payload.extend(struct.pack(">H", self._codec.action_to_vial(str(action))))
        return _pad(bytes(payload))
    def _set_encoder(self, packet: bytes) -> bytes:
        layer = int(packet[2])
        encoder_idx = int(packet[3])
        clockwise = bool(packet[4])
        keycode = struct.unpack(">H", packet[5:7])[0]
        target = self._encoder_target(encoder_idx, clockwise)
        if target is None:
            log.warning(
                "VIAL_SET_ENCODER ignored: encoder out-of-range layer=%d encoder=%d clockwise=%s keycode=0x%04x",
                layer, encoder_idx, clockwise, keycode,
            )
            return bytes(REPORT_SIZE)
        row, col = target
        self._apply_keycode(layer, row, col, keycode, save=SAVE_ON_SET, source="VIAL_SET_ENCODER")
        return bytes(REPORT_SIZE)

    def _get_keymap_buffer(self, packet: bytes) -> bytes:
        offset, size = struct.unpack(">HB", packet[1:4])
        buffer = self._build_keymap_buffer()
        total_size = len(buffer)
        if offset >= total_size:
            log.warning("KEYMAP_GET_BUFFER out-of-range: offset=%d size=%d total=%d", offset, size, total_size)
            return _pad(packet[:4])
        if offset + size > total_size:
            log.warning("KEYMAP_GET_BUFFER truncated: offset=%d size=%d total=%d", offset, size, total_size)
        payload = buffer[offset:offset + size]
        return _pad(packet[:4] + payload)
    def _set_keymap_buffer(self, packet: bytes) -> bytes:
        offset, size = struct.unpack(">HB", packet[1:4])
        data = packet[4:4 + size]
        if offset % 2:
            log.warning("KEYMAP_SET_BUFFER ignored: odd offset=%d size=%d", offset, size)
            return bytes(REPORT_SIZE)
        layers = self._fetch_logicd_layers()
        if layers:
            self.layers = max(1, len(layers))
        matrix_size = max(1, self.layers) * self.rows * self.cols * 2
        encoder_size = max(1, self.layers) * len(self.encoder_map) * 2 * 2
        total_size = matrix_size + encoder_size
        if offset >= total_size:
            log.warning("KEYMAP_SET_BUFFER ignored: offset=%d size=%d total=%d", offset, size, total_size)
            return bytes(REPORT_SIZE)
        if offset + size > total_size:
            log.warning("KEYMAP_SET_BUFFER truncated: offset=%d size=%d total=%d", offset, size, total_size)

        changed = 0
        total_keys = self.rows * self.cols
        for idx in range(0, len(data) - 1, 2):
            byte_offset = offset + idx
            if byte_offset < matrix_size:
                key_index = byte_offset // 2
                layer = key_index // total_keys
                within_layer = key_index % total_keys
                row = within_layer // self.cols
                col = within_layer % self.cols
            else:
                encoder_index = (byte_offset - matrix_size) // 2
                per_layer = len(self.encoder_map) * 2
                if not per_layer:
                    continue
                layer = encoder_index // per_layer
                within_layer = encoder_index % per_layer
                enc_idx = within_layer // 2
                action_idx = within_layer % 2
                if enc_idx >= len(self.encoder_map):
                    log.warning("KEYMAP_SET_BUFFER ignored: decoded encoder out-of-range layer=%d encoder=%d action=%d", layer, enc_idx, action_idx)
                    continue
                row, col = self.encoder_map[enc_idx][action_idx]
            if not self._valid_layer_row_col(layer, row, col):
                log.warning("KEYMAP_SET_BUFFER ignored: decoded out-of-range layer=%d row=%d col=%d", layer, row, col)
                continue
            keycode = struct.unpack(">H", data[idx:idx + 2])[0]
            if self._apply_keycode(layer, row, col, keycode, save=False, source="KEYMAP_SET_BUFFER"):
                changed += 1

        if changed and SAVE_ON_SET:
            save_result = self._send_logicd_message({"t": "S"})
            if not save_result or save_result.get("result") != "ok":
                log.warning("KEYMAP_SET_BUFFER save failed: changed=%d result=%r", changed, save_result)
        log.info("KEYMAP_SET_BUFFER processed: offset=%d size=%d changed=%d", offset, size, changed)
        return bytes(REPORT_SIZE)
    def _build_keymap_buffer(self) -> bytes:
        layers = self._fetch_logicd_layers()
        if not layers:
            layers = [{} for _ in range(self.layers)]
        self.layers = max(1, len(layers))
        matrix_size = self.layers * self.rows * self.cols * 2
        encoder_size = self.layers * len(self.encoder_map) * 2 * 2
        out = bytearray(matrix_size + encoder_size)
        for layer_idx, layer in enumerate(layers):
            for pos, action in layer.items():
                try:
                    row_s, col_s = pos.split(",", 1)
                    row, col = int(row_s), int(col_s)
                except (ValueError, AttributeError):
                    log.warning("keymap layer entry ignored: layer=%d pos=%r action=%r", layer_idx, pos, action)
                    continue
                if not (0 <= row < self.rows and 0 <= col < self.cols):
                    log.warning("keymap layer entry out-of-range: layer=%d row=%d col=%d action=%r", layer_idx, row, col, action)
                    continue
                offset = layer_idx * self.rows * self.cols * 2 + row * self.cols * 2 + col * 2
                out[offset:offset + 2] = struct.pack(">H", self._codec.action_to_vial(str(action)))
            for enc_idx, targets in enumerate(self.encoder_map):
                for action_idx, (row, col) in enumerate(targets):
                    action = layer.get(f"{row},{col}", "KC_NONE")
                    offset = (
                        matrix_size
                        + (layer_idx * len(self.encoder_map) * 2 + enc_idx * 2 + action_idx) * 2
                    )
                    out[offset:offset + 2] = struct.pack(">H", self._codec.action_to_vial(str(action)))
        return bytes(out)
    def _set_keycode(self, packet: bytes) -> bytes:
        layer, row, col, keycode = struct.unpack(">BBBH", packet[1:6])
        if not self._valid_layer_row_col(layer, row, col):
            log.warning("SET_KEYCODE ignored: out-of-range layer=%d row=%d col=%d keycode=0x%04x", layer, row, col, keycode)
            return bytes(REPORT_SIZE)
        self._apply_keycode(layer, row, col, keycode, save=SAVE_ON_SET, source="SET_KEYCODE")
        return bytes(REPORT_SIZE)
    def _valid_layer_row_col(self, layer: int, row: int, col: int) -> bool:
        return 0 <= layer < 32 and 0 <= row < self.rows and 0 <= col < self.cols
    def _apply_keycode(
        self,
        layer: int,
        row: int,
        col: int,
        keycode: int,
        *,
        save: bool,
        source: str,
    ) -> bool:
        action = self._codec.vial_to_action(keycode)
        if action is None:
            log.warning(
                "%s ignored: unsupported keycode=0x%04x layer=%d row=%d col=%d",
                source, keycode, layer, row, col,
            )
            return False
        result = self._send_logicd_message({"t": "M", "l": layer, "r": row, "c": col, "a": action})
        if not result or result.get("result") != "ok":
            log.warning(
                "%s failed: action=%s keycode=0x%04x layer=%d row=%d col=%d result=%r",
                source, action, keycode, layer, row, col, result,
            )
            return False
        log.info(
            "%s accepted: action=%s keycode=0x%04x layer=%d row=%d col=%d",
            source, action, keycode, layer, row, col,
        )
        if save:
            save_result = self._send_logicd_message({"t": "S"})
            if not save_result or save_result.get("result") != "ok":
                log.warning("%s save failed: action=%s result=%r", source, action, save_result)
        return True
