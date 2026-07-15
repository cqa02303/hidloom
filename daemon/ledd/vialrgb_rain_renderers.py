"""Rain and pixel-noise VialRGB renderer loops for ledd."""

from __future__ import annotations

import math
import random
import threading
import time


class VialRgbRainRenderersMixin:
    def _run_vialrgb_pixel_rain(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            h, s, v = self._vialrgb_hsv
            speed = max(1, self._vialrgb_speed)
            mode = self._vialrgb_mode
            with self._vialrgb_lock:
                drops = []
                for drop in self._vialrgb_pixel_rain:
                    age = time.monotonic() - float(drop["start"])
                    lifetime = 1.15 if mode in {24, 25} else 0.8
                    if age <= lifetime:
                        drops.append(drop)
                target_count = max(1, self._led_count // (9 if mode in {24, 25} else 12))
                while len(drops) < target_count:
                    hue = h if mode == 24 else (h + random.randrange(96)) % 256
                    drops.append({
                        "idx": random.randrange(max(1, self._led_count)),
                        "start": time.monotonic(),
                        "h": hue,
                    })
                self._vialrgb_pixel_rain = drops

                colors = [0] * self._led_count
                for drop in drops:
                    age = time.monotonic() - float(drop["start"])
                    lifetime = 1.15 if mode in {24, 25} else 0.8
                    brightness = int(v * max(0.0, 1.0 - age / lifetime))
                    colors[int(drop["idx"])] = self._color_from_hsv(int(drop["h"]), s, brightness)

            for idx, color in enumerate(colors):
                self._strip.setPixelColor(idx, color)
            self._show_with_state_overlays()
            stop_event.wait(max(0.02, 0.12 - speed / 4096.0))

    def _run_vialrgb_digital_rain(self, stop_event: threading.Event) -> None:
        min_x, max_x, min_y, max_y = self._coords_bounds()
        columns = max(1, min(16, int(math.sqrt(max(1, self._led_count))) + 2))
        drops = [
            {"col": col, "head": random.random(), "speed": 0.004 + random.random() * 0.010}
            for col in range(columns)
        ]
        while not stop_event.is_set():
            h, s, v = self._vialrgb_hsv
            speed = max(1, self._vialrgb_speed)
            for idx in range(self._led_count):
                if idx < len(self._led_coords):
                    x, y = self._led_coords[idx]
                    x_ratio = (x - min_x) / (max_x - min_x)
                    y_ratio = (y - min_y) / (max_y - min_y)
                else:
                    x_ratio = idx / max(1, self._led_count - 1)
                    y_ratio = 0.0
                col = min(columns - 1, max(0, int(x_ratio * columns)))
                head = float(drops[col]["head"])
                distance = (y_ratio - head) % 1.0
                brightness = 0
                if distance < 0.22:
                    brightness = int(v * (1.0 - distance / 0.22))
                self._strip.setPixelColor(idx, self._color_from_hsv(h, s, max(0, min(255, brightness))))
            self._show_with_state_overlays()
            for drop in drops:
                drop["head"] = (float(drop["head"]) + float(drop["speed"]) * (0.5 + speed / 128.0)) % 1.0
            stop_event.wait(1.0 / 30.0)

    def _run_vialrgb_pixel_fractal(self, stop_event: threading.Event) -> None:
        min_x, max_x, min_y, max_y = self._coords_bounds()
        phase = 0.0
        while not stop_event.is_set():
            _h, s, v = self._vialrgb_hsv
            speed = max(1, self._vialrgb_speed)
            for idx in range(self._led_count):
                if idx < len(self._led_coords):
                    x, y = self._led_coords[idx]
                    x_ratio = (x - min_x) / (max_x - min_x)
                    y_ratio = (y - min_y) / (max_y - min_y)
                else:
                    x_ratio = idx / max(1, self._led_count - 1)
                    y_ratio = 0.0
                value = math.sin((x_ratio * 5.0 + phase) * math.tau) + math.sin((y_ratio * 3.0 - phase * 0.7) * math.tau)
                hue = int(((value + 2.0) / 4.0) * 255) % 256
                self._strip.setPixelColor(idx, self._color_from_hsv(hue, s, v))
            self._show_with_state_overlays()
            phase = (phase + (0.003 + speed / 32768.0)) % 1.0
            stop_event.wait(1.0 / 30.0)
