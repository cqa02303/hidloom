"""Hue-focused VialRGB renderer loops for ledd."""

from __future__ import annotations

import math
import threading


class VialRgbHueRenderersMixin:
    def _run_vialrgb_hue_breathing(self, stop_event: threading.Event) -> None:
        phase = 0.0
        hue = self._vialrgb_hsv[0]
        while not stop_event.is_set():
            _h, s, v = self._vialrgb_hsv
            speed = max(1, self._vialrgb_speed)
            brightness = int(v * (0.20 + 0.80 * (0.5 + 0.5 * math.sin(phase))))
            color = self._color_from_hsv(hue % 256, s, brightness)
            for idx in range(self._led_count):
                self._strip.setPixelColor(idx, color)
            self._show_with_state_overlays()
            hue = (hue + max(1, speed // 32)) % 256
            phase += 0.04 + speed / 2048.0
            stop_event.wait(1.0 / 30.0)

    def _run_vialrgb_hue_wave(self, stop_event: threading.Event) -> None:
        min_x, max_x, _min_y, _max_y = self._coords_bounds()
        offset = 0
        while not stop_event.is_set():
            _h, s, v = self._vialrgb_hsv
            speed = max(1, self._vialrgb_speed)
            for idx in range(self._led_count):
                if idx < len(self._led_coords):
                    x, _y = self._led_coords[idx]
                    ratio = (x - min_x) / (max_x - min_x)
                else:
                    ratio = idx / max(1, self._led_count - 1)
                wave = 0.5 + 0.5 * math.sin((ratio * math.tau) + offset / 24.0)
                self._strip.setPixelColor(idx, self._color_from_hsv(int(wave * 255) % 256, s, v))
            self._show_with_state_overlays()
            offset = (offset + max(1, speed // 12)) % 256
            stop_event.wait(1.0 / 30.0)

    def _run_vialrgb_hue_pendulum(self, stop_event: threading.Event) -> None:
        phase = 0.0
        while not stop_event.is_set():
            h, s, v = self._vialrgb_hsv
            speed = max(1, self._vialrgb_speed)
            hue = int((h + math.sin(phase) * 64) % 256)
            color = self._color_from_hsv(hue, s, v)
            for idx in range(self._led_count):
                self._strip.setPixelColor(idx, color)
            self._show_with_state_overlays()
            phase += 0.035 + speed / 2048.0
            stop_event.wait(1.0 / 30.0)
