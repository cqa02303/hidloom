"""VialRGB renderer loops for ledd."""

from __future__ import annotations

import math
import threading
import time

from .vialrgb_hue_renderers import VialRgbHueRenderersMixin
from .vialrgb_position_renderers import VialRgbPositionRenderersMixin
from .vialrgb_rain_renderers import VialRgbRainRenderersMixin
from .vialrgb_reactive_renderers import VialRgbReactiveRenderersMixin
from .vialrgb_splash_renderers import VialRgbSplashRenderersMixin


class VialRgbRenderersMixin(
    VialRgbHueRenderersMixin,
    VialRgbPositionRenderersMixin,
    VialRgbRainRenderersMixin,
    VialRgbReactiveRenderersMixin,
    VialRgbSplashRenderersMixin,
):
    def _run_vialrgb_direct_pattern(self, stop_event: threading.Event) -> None:
        frame_index = 0
        next_frame = time.monotonic()
        while not stop_event.is_set():
            opts = self._vialrgb_direct_pattern
            pattern = str(opts.get("pattern", "rainbow"))
            fps = max(1.0, float(opts.get("fps", 16.0)))
            brightness = max(0, min(255, int(opts.get("brightness", 96))))
            phase = frame_index * 7
            for idx in range(self._led_count):
                ratio = idx / max(1, self._led_count - 1)
                if pattern == "chase":
                    distance = min(
                        abs((idx - frame_index) % self._led_count),
                        abs((frame_index - idx) % self._led_count),
                    )
                    val = max(8, brightness - distance * 32)
                    hue = (phase + idx * 3) % 256
                elif pattern == "pulse":
                    wave = (math.sin(frame_index * 0.18 + ratio * math.tau) + 1.0) / 2.0
                    val = int(16 + wave * max(0, brightness - 16))
                    hue = (phase + int(ratio * 64)) % 256
                else:
                    val = brightness
                    hue = (phase + int(ratio * 255)) % 256
                self._strip.setPixelColor(idx, self._color_from_hsv(hue, 255, val))
            self._show_with_state_overlays()
            frame_index += 1
            next_frame += 1.0 / fps
            stop_event.wait(max(0.0, next_frame - time.monotonic()))
            if next_frame < time.monotonic() - 1.0:
                next_frame = time.monotonic()

    def _run_vialrgb_breathing(self, stop_event: threading.Event) -> None:
        phase = 0.0
        while not stop_event.is_set():
            h, s, v = self._vialrgb_hsv
            speed = max(1, self._vialrgb_speed)
            brightness = int(v * (0.20 + 0.80 * (0.5 + 0.5 * math.sin(phase))))
            color = self._color_from_hsv(h, s, brightness)
            for idx in range(self._led_count):
                self._strip.setPixelColor(idx, color)
            self._show_with_state_overlays()
            phase += 0.04 + speed / 2048.0
            stop_event.wait(1.0 / 30.0)

    def _run_vialrgb_cycle_all(self, stop_event: threading.Event) -> None:
        hue = 0
        while not stop_event.is_set():
            _h, s, v = self._vialrgb_hsv
            speed = max(1, self._vialrgb_speed)
            color = self._color_from_hsv(hue % 256, s, v)
            for idx in range(self._led_count):
                self._strip.setPixelColor(idx, color)
            self._show_with_state_overlays()
            hue = (hue + max(1, speed // 16)) % 256
            stop_event.wait(1.0 / 30.0)

    def _coords_bounds(self) -> tuple[float, float, float, float]:
        if not self._led_coords:
            return (0.0, 1.0, 0.0, 1.0)
        xs = [coord[0] for coord in self._led_coords]
        ys = [coord[1] for coord in self._led_coords]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        return (
            min_x,
            max_x if max_x > min_x else min_x + 1.0,
            min_y,
            max_y if max_y > min_y else min_y + 1.0,
        )

    def _run_vialrgb_gradient(self, stop_event: threading.Event) -> None:
        min_x, max_x, min_y, max_y = self._coords_bounds()
        while not stop_event.is_set():
            h, s, v = self._vialrgb_hsv
            horizontal = self._vialrgb_mode == 5
            for idx in range(self._led_count):
                if idx < len(self._led_coords):
                    x, y = self._led_coords[idx]
                    ratio = (x - min_x) / (max_x - min_x) if horizontal else (y - min_y) / (max_y - min_y)
                else:
                    ratio = idx / max(1, self._led_count - 1)
                self._strip.setPixelColor(idx, self._color_from_hsv(int((h + ratio * 64) % 256), s, v))
            self._show_with_state_overlays()
            stop_event.wait(1.0 / 15.0)

    def _run_vialrgb_alphas_mods(self, stop_event: threading.Event) -> None:
        min_x, max_x, min_y, max_y = self._coords_bounds()
        while not stop_event.is_set():
            h, s, v = self._vialrgb_hsv
            for idx in range(self._led_count):
                key = self._led_keys[idx] if idx < len(self._led_keys) else ""
                keycode = self.keycode_for_position(key) if key else ""
                if idx < len(self._led_coords):
                    x, y = self._led_coords[idx]
                    x_ratio = (x - min_x) / (max_x - min_x)
                    y_ratio = (y - min_y) / (max_y - min_y)
                else:
                    x_ratio = idx / max(1, self._led_count - 1)
                    y_ratio = 0.5
                is_alpha = (
                    self._vialrgb_is_alpha_key(keycode)
                    if keycode
                    else 0.18 <= x_ratio <= 0.82 and y_ratio <= 0.78
                )
                hue = h if is_alpha else (h + 96) % 256
                val = v if is_alpha else max(0, int(v * 0.75))
                self._strip.setPixelColor(idx, self._color_from_hsv(hue, s, val))
            self._show_with_state_overlays()
            stop_event.wait(1.0 / 15.0)

    def _vialrgb_is_alpha_key(self, keycode: str) -> bool:
        keycode = str(keycode or "").upper()
        if not (keycode.startswith("KC_") and len(keycode) == 4 and keycode[-1].isalpha()):
            return False
        return self._semantic_roles.role_for_keycode(keycode) == "normal"

    def _run_vialrgb_directional_cycle(self, stop_event: threading.Event) -> None:
        min_x, max_x, min_y, max_y = self._coords_bounds()
        offset = 0
        while not stop_event.is_set():
            _h, s, v = self._vialrgb_hsv
            speed = max(1, self._vialrgb_speed)
            horizontal = self._vialrgb_mode == 14
            for idx in range(self._led_count):
                if idx < len(self._led_coords):
                    x, y = self._led_coords[idx]
                    ratio = (x - min_x) / (max_x - min_x) if horizontal else (y - min_y) / (max_y - min_y)
                else:
                    ratio = idx / max(1, self._led_count - 1)
                self._strip.setPixelColor(idx, self._color_from_hsv(int((ratio * 255 + offset) % 256), s, v))
            self._show_with_state_overlays()
            offset = (offset + max(1, speed // 20)) % 256
            stop_event.wait(1.0 / 30.0)

    def _run_vialrgb_radial_cycle(self, stop_event: threading.Event) -> None:
        min_x, max_x, min_y, max_y = self._coords_bounds()
        cx = (min_x + max_x) / 2.0
        cy = (min_y + max_y) / 2.0
        max_radius = 1.0
        if self._led_coords:
            max_radius = max(
                math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
                for x, y in self._led_coords
            ) or 1.0
        offset = 0
        while not stop_event.is_set():
            _h, s, v = self._vialrgb_hsv
            speed = max(1, self._vialrgb_speed)
            mode = self._vialrgb_mode
            for idx in range(self._led_count):
                if idx < len(self._led_coords):
                    x, y = self._led_coords[idx]
                    angle = (math.atan2(y - cy, x - cx) / math.tau + 1.0) % 1.0
                    radius = math.sqrt((x - cx) ** 2 + (y - cy) ** 2) / max_radius
                else:
                    angle = idx / max(1, self._led_count - 1)
                    radius = angle

                if mode == 17:  # Cycle Out In
                    hue = int((radius * 255 + offset) % 256)
                elif mode == 18:  # Cycle Out In Dual
                    hue = int((abs(0.5 - radius) * 510 + offset) % 256)
                elif mode == 19:  # Cycle Pinwheel
                    hue = int((angle * 255 + offset) % 256)
                else:  # Cycle Spiral
                    hue = int(((angle + radius) * 128 + offset) % 256)
                self._strip.setPixelColor(idx, self._color_from_hsv(hue, s, v))
            self._show_with_state_overlays()
            offset = (offset + max(1, speed // 18)) % 256
            stop_event.wait(1.0 / 30.0)

    def _run_vialrgb_chevron_beacon(self, stop_event: threading.Event) -> None:
        min_x, max_x, min_y, max_y = self._coords_bounds()
        cx = (min_x + max_x) / 2.0
        cy = (min_y + max_y) / 2.0
        offset = 0
        while not stop_event.is_set():
            _h, s, v = self._vialrgb_hsv
            speed = max(1, self._vialrgb_speed)
            mode = self._vialrgb_mode
            for idx in range(self._led_count):
                if idx < len(self._led_coords):
                    x, y = self._led_coords[idx]
                    x_ratio = (x - min_x) / (max_x - min_x)
                    y_ratio = (y - min_y) / (max_y - min_y)
                    angle = (math.atan2(y - cy, x - cx) / math.tau + 1.0) % 1.0
                else:
                    x_ratio = idx / max(1, self._led_count - 1)
                    y_ratio = 0.0
                    angle = x_ratio
                if mode == 16:  # Rainbow Moving Chevron
                    chevron = (abs(x_ratio - 0.5) * 2.0 + y_ratio + offset / 255.0) % 1.0
                    hue = int(chevron * 255)
                else:  # Dual Beacon
                    beacon_a = abs(((angle + offset / 255.0) % 1.0) - 0.5)
                    beacon_b = abs(((angle + 0.5 + offset / 255.0) % 1.0) - 0.5)
                    hue = int((min(beacon_a, beacon_b) * 510 + offset) % 256)
                self._strip.setPixelColor(idx, self._color_from_hsv(hue, s, v))
            self._show_with_state_overlays()
            offset = (offset + max(1, speed // 16)) % 256
            stop_event.wait(1.0 / 30.0)
