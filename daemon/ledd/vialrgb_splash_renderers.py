"""Splash VialRGB renderer loops for ledd."""

from __future__ import annotations

import colorsys
import math
import threading
import time

from .strip import Color
from vialrgb_effects import VIALRGB_SOLID_SPLASH_MODES


class VialRgbSplashRenderersMixin:
    def _run_vialrgb_multisplash(self, stop_event: threading.Event) -> None:
        if not self._led_coords:
            self._run_vialrgb_cycle_all(stop_event)
            return

        led_coords = self._led_coords[: self._led_count]
        last_idle_key: tuple[int, int, int, int] | None = None
        while not stop_event.is_set():
            now = time.monotonic()
            h, s, v = self._vialrgb_hsv
            speed = 120.0 + self._vialrgb_speed * 1.8
            width = 25.0
            base_v = max(0, v // 8) if self._vialrgb_mode in VIALRGB_SOLID_SPLASH_MODES else 0

            with self._vialrgb_lock:
                has_splashes = bool(self._vialrgb_splashes)
                if not has_splashes:
                    self._vialrgb_wake.clear()
            if not has_splashes:
                idle_key = (self._vialrgb_mode, h, s, base_v)
                if idle_key != last_idle_key:
                    color = Color(0, 0, 0)
                    if self._vialrgb_mode in VIALRGB_SOLID_SPLASH_MODES:
                        red_f, green_f, blue_f = colorsys.hsv_to_rgb(h / 255.0, s / 255.0, base_v / 255.0)
                        color = Color(int(red_f * 255), int(green_f * 255), int(blue_f * 255))
                    for idx in range(self._led_count):
                        self._strip.setPixelColor(idx, color)
                    self._show_with_state_overlays()
                    last_idle_key = idle_key
                self._vialrgb_wake.wait()
                continue

            last_idle_key = None
            rgb = [[0.0, 0.0, 0.0] for _ in range(self._led_count)]
            if self._vialrgb_mode in VIALRGB_SOLID_SPLASH_MODES:
                red_f, green_f, blue_f = colorsys.hsv_to_rgb(h / 255.0, s / 255.0, base_v / 255.0)
                fallback = (red_f * 255, green_f * 255, blue_f * 255)
                rgb = [self._semantic_base_rgb_for_index(idx, fallback) for idx in range(self._led_count)]
            else:
                rgb = [self._semantic_base_rgb_for_index(idx, (0.0, 0.0, 0.0)) for idx in range(self._led_count)]

            with self._vialrgb_lock:
                splashes = []
                for splash in self._vialrgb_splashes:
                    age = now - float(splash["start"])
                    radius = age * speed
                    if age <= 1.0:
                        splashes.append(splash)
                    for idx, (lx, ly) in enumerate(led_coords):
                        dist = math.sqrt((lx - float(splash["x"])) ** 2 + (ly - float(splash["y"])) ** 2)
                        diff = abs(dist - radius)
                        if diff <= width:
                            factor = (1.0 - diff / width) * max(0.0, 1.0 - age)
                            red_f, green_f, blue_f = colorsys.hsv_to_rgb(
                                (int(splash["h"]) % 256) / 255.0,
                                s / 255.0,
                                min(255, v) / 255.0,
                            )
                            rgb[idx][0] = min(255.0, rgb[idx][0] + red_f * 255 * factor)
                            rgb[idx][1] = min(255.0, rgb[idx][1] + green_f * 255 * factor)
                            rgb[idx][2] = min(255.0, rgb[idx][2] + blue_f * 255 * factor)
                self._vialrgb_splashes = splashes

            for idx, (r, g, b) in enumerate(rgb):
                self._strip.setPixelColor(idx, Color(int(r), int(g), int(b)))
            self._show_with_state_overlays()
            stop_event.wait(1.0 / 60.0)
