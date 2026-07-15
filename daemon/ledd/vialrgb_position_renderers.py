"""Position-based VialRGB renderer loops for ledd."""

from __future__ import annotations

import math
import threading


class VialRgbPositionRenderersMixin:
    def _run_vialrgb_position_pattern(self, stop_event: threading.Event) -> None:
        min_x, max_x, min_y, max_y = self._coords_bounds()
        cx = (min_x + max_x) / 2.0
        cy = (min_y + max_y) / 2.0
        span = max(max_x - min_x, max_y - min_y, 1.0)
        offset = 0
        while not stop_event.is_set():
            h, s, v = self._vialrgb_hsv
            speed = max(1, self._vialrgb_speed)
            mode = self._vialrgb_mode
            for idx in range(self._led_count):
                if idx < len(self._led_coords):
                    x, y = self._led_coords[idx]
                else:
                    x, y = float(idx), 0.0
                angle = (math.atan2(y - cy, x - cx) / math.tau + 1.0) % 1.0
                radius = math.sqrt((x - cx) ** 2 + (y - cy) ** 2) / span
                x_ratio = (x - min_x) / (max_x - min_x)
                y_ratio = (y - min_y) / (max_y - min_y)

                if mode == 7:  # Band Sat
                    hue, sat, val = h, int((x_ratio * 255 + offset) % 256), v
                elif mode == 8:  # Band Val
                    hue, sat, val = h, s, int((0.2 + 0.8 * ((x_ratio + offset / 255.0) % 1.0)) * v)
                elif mode == 9:  # Band Pinwheel Sat
                    hue, sat, val = h, int(((angle + offset / 255.0) % 1.0) * 255), v
                elif mode == 10:  # Band Pinwheel Val
                    hue, sat, val = h, s, int((0.2 + 0.8 * ((angle + offset / 255.0) % 1.0)) * v)
                elif mode == 11:  # Band Spiral Sat
                    hue, sat, val = h, int(((angle + radius + offset / 255.0) % 1.0) * 255), v
                elif mode == 12:  # Band Spiral Val
                    hue, sat, val = h, s, int((0.2 + 0.8 * ((angle + radius + offset / 255.0) % 1.0)) * v)
                elif mode == 22:  # Rainbow Beacon
                    hue, sat, val = int((angle * 255 + offset) % 256), s, v
                elif mode == 23:  # Rainbow Pinwheels
                    hue, sat, val = int(((angle * 2.0 + offset / 255.0) % 1.0) * 255), s, v
                else:
                    hue, sat, val = int(((x_ratio + y_ratio + offset / 255.0) % 1.0) * 255), s, v
                self._strip.setPixelColor(idx, self._color_from_hsv(hue, sat, max(0, min(255, val))))
            self._show_with_state_overlays()
            offset = (offset + max(1, speed // 16)) % 256
            stop_event.wait(1.0 / 30.0)
