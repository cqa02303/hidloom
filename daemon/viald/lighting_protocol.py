"""VialRGB lighting command handlers for viald."""

from __future__ import annotations

import json
import logging
import struct
from pathlib import Path

from vialrgb_effects import VIALRGB_SUPPORTED_EFFECTS
from .protocol_defs import (
    CMD_VIA_LIGHTING_GET_VALUE,
    REPORT_SIZE,
    VIALRGB_DIRECT_FASTSET,
    VIALRGB_GET_INFO,
    VIALRGB_GET_LED_INFO,
    VIALRGB_GET_MODE,
    VIALRGB_GET_NUMBER_LEDS,
    VIALRGB_GET_SUPPORTED,
    VIALRGB_SET_MODE,
)

log = logging.getLogger(__name__)


def _pad(payload: bytes) -> bytes:
    return payload[:REPORT_SIZE].ljust(REPORT_SIZE, b"\x00")


class VialLightingMixin:
    def _lighting_get_value(self, packet: bytes) -> bytes:
        subcommand = packet[1]
        if subcommand == VIALRGB_GET_INFO:
            # command, subcommand, protocol_version_le16, max_brightness
            return _pad(bytes([CMD_VIA_LIGHTING_GET_VALUE, subcommand, 1, 0, 255]))
        if subcommand == VIALRGB_GET_SUPPORTED:
            requested = struct.unpack("<H", packet[2:4])[0]
            supported = [effect for effect in VIALRGB_SUPPORTED_EFFECTS if effect > requested]
            payload = b"".join(struct.pack("<H", effect) for effect in supported) + b"\xff\xff"
            return _pad(bytes([CMD_VIA_LIGHTING_GET_VALUE, subcommand]) + payload)
        if subcommand == VIALRGB_GET_MODE:
            self._refresh_rgb_state_from_logicd()
            # mode_le16, speed, hsv
            return _pad(
                bytes([CMD_VIA_LIGHTING_GET_VALUE, subcommand])
                + struct.pack("<HBBBB", self.rgb_mode, self.rgb_speed, *self.rgb_hsv)
            )
        if subcommand == VIALRGB_GET_NUMBER_LEDS:
            return _pad(
                bytes([CMD_VIA_LIGHTING_GET_VALUE, subcommand])
                + struct.pack("<H", len(self._led_info))
            )
        if subcommand == VIALRGB_GET_LED_INFO:
            led_idx = struct.unpack("<H", packet[2:4])[0]
            if not (0 <= led_idx < len(self._led_info)):
                log.warning("VIALRGB_GET_LED_INFO out-of-range: led_idx=%d led_count=%d", led_idx, len(self._led_info))
                return bytes(REPORT_SIZE)
            x, y, row, col = self._led_info[led_idx]
            # x, y, flags, matrix row, matrix col. LED_FLAG_KEYLIGHT = 0x04.
            return _pad(bytes([CMD_VIA_LIGHTING_GET_VALUE, subcommand, x, y, 0x04, row, col]))
        log.warning("unsupported lighting get subcommand: 0x%02x payload=%s", subcommand, packet[:REPORT_SIZE].hex())
        return bytes(REPORT_SIZE)

    def _refresh_rgb_state_from_logicd(self) -> None:
        result = self._send_logicd_message({"t": "LED", "op": "vialrgb_get"})
        if not result or result.get("result") != "ok":
            log.warning("VIALRGB_GET_MODE using cached state: logicd result=%r", result)
            return
        try:
            mode_raw = int(result.get("mode", self.rgb_mode))
            speed_raw = int(result.get("speed", self.rgb_speed))
            h_raw = int(result.get("h", self.rgb_hsv[0]))
            s_raw = int(result.get("s", self.rgb_hsv[1]))
            v_raw = int(result.get("v", self.rgb_hsv[2]))
            self.rgb_mode = max(0, min(65535, mode_raw))
            self.rgb_speed = max(0, min(255, speed_raw))
            self.rgb_hsv = (
                max(0, min(255, h_raw)),
                max(0, min(255, s_raw)),
                max(0, min(255, v_raw)),
            )
            if (mode_raw, speed_raw, h_raw, s_raw, v_raw) != (self.rgb_mode, self.rgb_speed, *self.rgb_hsv):
                log.warning(
                    "VIALRGB_GET_MODE clamped logicd state: raw=(%d,%d,%d,%d,%d) clamped=(%d,%d,%d,%d,%d)",
                    mode_raw, speed_raw, h_raw, s_raw, v_raw,
                    self.rgb_mode, self.rgb_speed, *self.rgb_hsv,
                )
        except (TypeError, ValueError):
            log.warning("VIALRGB_GET_MODE ignored malformed logicd state: %r", result)
            return

    def _lighting_set_value(self, packet: bytes) -> bytes:
        subcommand = packet[1]
        if subcommand == VIALRGB_SET_MODE:
            mode, speed, h, s, v = struct.unpack("<HBBBB", packet[2:8])
            self.rgb_mode = mode
            self.rgb_speed = speed
            self.rgb_hsv = (h, s, v)
            self._send_logicd_message(
                {"t": "LED", "op": "vialrgb", "mode": mode, "speed": speed, "h": h, "s": s, "v": v}
            )
        elif subcommand == VIALRGB_DIRECT_FASTSET:
            first_index = struct.unpack("<H", packet[2:4])[0]
            led_count = packet[4]
            data = packet[5:5 + led_count * 3]
            max_payload_pixels = (REPORT_SIZE - 5) // 3
            if led_count > max_payload_pixels:
                log.warning(
                    "VIALRGB_DIRECT_FASTSET truncated by report size: first=%d led_count=%d max_payload=%d",
                    first_index, led_count, max_payload_pixels,
                )
            if first_index >= len(self._led_info):
                log.warning(
                    "VIALRGB_DIRECT_FASTSET starts outside LED range: first=%d led_count=%d total=%d",
                    first_index, led_count, len(self._led_info),
                )
            if led_count and len(data) == min(led_count, max_payload_pixels) * 3:
                pixels = [
                    [data[idx], data[idx + 1], data[idx + 2]]
                    for idx in range(0, len(data), 3)
                ]
                self._send_logicd_message(
                    {"t": "LED", "op": "vialrgb_direct", "first": first_index, "pixels": pixels}
                )
            else:
                log.warning("VIALRGB_DIRECT_FASTSET ignored: first=%d led_count=%d data_len=%d", first_index, led_count, len(data))
        else:
            log.warning("unsupported lighting set subcommand: 0x%02x payload=%s", subcommand, packet[:REPORT_SIZE].hex())
        return bytes(REPORT_SIZE)

    def _load_led_info(self, path: Path) -> list[tuple[int, int, int, int]]:
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
            leds = config.get("leds", {})
            if not isinstance(leds, dict):
                log.warning("LED info ignored: %s has non-dict leds", path)
                return []
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("LED info load failed: path=%s error=%s", path, exc)
            return []

        parsed: list[tuple[str, float, float, int, int]] = []
        for key, value in leds.items():
            if not isinstance(value, dict):
                continue
            try:
                row_s, col_s = str(key).split(",", 1)
                parsed.append((str(key), float(value["x"]), float(value["y"]), int(row_s), int(col_s)))
            except (KeyError, TypeError, ValueError):
                log.warning("LED info entry ignored: key=%r value=%r", key, value)
                continue
        if not parsed:
            return []

        xs = [item[1] for item in parsed]
        ys = [item[2] for item in parsed]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span_x = max(max_x - min_x, 1.0)
        span_y = max(max_y - min_y, 1.0)

        info: list[tuple[int, int, int, int]] = []
        for _key, x, y, row, col in parsed:
            qmk_x = round((x - min_x) / span_x * 224)
            qmk_y = round((y - min_y) / span_y * 64)
            info.append((
                max(0, min(255, qmk_x)),
                max(0, min(255, qmk_y)),
                max(0, min(255, row)),
                max(0, min(255, col)),
            ))
        return info

