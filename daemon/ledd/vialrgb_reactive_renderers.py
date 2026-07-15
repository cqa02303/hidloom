"""Reactive VialRGB renderer loops for ledd."""

from __future__ import annotations

import colorsys
import math
import threading
import time

from .strip import Color
from vialrgb_effects import (
    VIALRGB_CROSS_REACTIVE_MODES,
    VIALRGB_MULTI_HUE_REACTIVE_MODES,
    VIALRGB_SHORT_REACTIVE_MODES,
    VIALRGB_WIDE_REACTIVE_MODES,
)

_FONT_5X7_ROWS: dict[str, tuple[str, ...]] = {
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01110"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("01110", "00100", "00100", "00100", "00100", "00100", "01110"),
    "J": ("00111", "00010", "00010", "00010", "00010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
}

_KEY_BANNER_COLUMN_SCALE = 2
_KEY_BANNER_SCROLL_BRIGHTNESS_SCALE = 0.7
_KEY_BANNER_MOD_SPLASH_LIFETIME = 0.55
_KEY_BANNER_MOD_SPLASH_WIDTH = 14.0


def _font_columns(char: str) -> list[int]:
    rows = _FONT_5X7_ROWS.get(char.upper(), _FONT_5X7_ROWS["-"])
    columns: list[int] = []
    width = len(rows[0])
    for x in range(width):
        mask = 0
        for y, row in enumerate(rows):
            if row[x] == "1":
                mask |= 1 << y
        columns.append(mask)
    return columns


def _stretch_columns(columns: list[int], scale: int) -> list[int]:
    scale = max(1, int(scale))
    if scale == 1:
        return list(columns)
    out: list[int] = []
    for column in columns:
        out.extend([column] * scale)
    return out


def _text_columns(text: str) -> list[int]:
    out: list[int] = []
    for char in text[:8]:
        out.extend(_stretch_columns(_font_columns(char), _KEY_BANNER_COLUMN_SCALE))
        out.append(0)
    out.extend([0, 0])
    return out


def _keycode_banner_text(keycode: str) -> str | None:
    keycode = str(keycode or "").upper()
    if keycode.startswith("KC_") and len(keycode) == 4 and keycode[-1].isalpha():
        return keycode[-1]
    if keycode.startswith("KC_") and len(keycode) == 4 and keycode[-1].isdigit():
        return keycode[-1]
    if keycode in {"KC_MINUS", "KC_MINS"}:
        return "-"
    if keycode in {"KC_DOT", "KC_PERIOD"}:
        return "."
    return None


class VialRgbReactiveRenderersMixin:
    def _vialrgb_key_banner_has_text(self, keycode: str) -> bool:
        return _keycode_banner_text(keycode) is not None

    def _vialrgb_queue_key_banner(self, keycode: str) -> None:
        text = _keycode_banner_text(keycode)
        if text is None:
            return
        with self._vialrgb_lock:
            self._vialrgb_key_banner_columns.extend(_text_columns(text))
            max_columns = 240 * _KEY_BANNER_COLUMN_SCALE
            if len(self._vialrgb_key_banner_columns) > max_columns:
                self._vialrgb_key_banner_columns = self._vialrgb_key_banner_columns[-max_columns:]
            self._vialrgb_wake.set()

    def _vialrgb_reactive_has_hits(self) -> bool:
        with self._vialrgb_lock:
            has_hits = bool(self._vialrgb_reactive_hits)
            if not has_hits:
                self._vialrgb_wake.clear()
        return has_hits

    def _vialrgb_take_overlay_dirty(self) -> bool:
        with self._vialrgb_lock:
            dirty = bool(getattr(self, "_vialrgb_overlay_dirty", False))
            self._vialrgb_overlay_dirty = False
        return dirty

    def _vialrgb_idle_needs_render(self, idle_rendered: bool) -> bool:
        return not idle_rendered or self._vialrgb_take_overlay_dirty()

    def _run_vialrgb_solid_reactive_simple(self, stop_event: threading.Event) -> None:
        idle_rendered = False
        while not stop_event.is_set():
            now = time.monotonic()
            h, s, v = self._vialrgb_hsv
            base_color = 0
            for idx in range(self._led_count):
                self._strip.setPixelColor(idx, self._semantic_base_color_for_index(idx, base_color))

            if not self._vialrgb_reactive_has_hits():
                if self._vialrgb_idle_needs_render(idle_rendered):
                    self._show_with_state_overlays()
                    idle_rendered = True
                self._vialrgb_wake.wait()
                continue
            idle_rendered = False
            with self._vialrgb_lock:
                hits = []
                for hit in self._vialrgb_reactive_hits:
                    age = now - float(hit["start"])
                    if age <= 0.45:
                        hits.append(hit)
                        factor = 1.0 - age / 0.45
                        brightness = max(0, min(255, int(v * factor)))
                        self._strip.setPixelColor(int(hit["idx"]), self._color_from_hsv(h, s, brightness))
                self._vialrgb_reactive_hits = hits

            self._show_with_state_overlays()
            stop_event.wait(1.0 / 60.0)

    def _run_vialrgb_typing_heatmap(self, stop_event: threading.Event) -> None:
        idle_rendered = False
        while not stop_event.is_set():
            now = time.monotonic()
            h, s, v = self._vialrgb_hsv
            heat = [0.0] * self._led_count
            if not self._vialrgb_reactive_has_hits():
                if self._vialrgb_idle_needs_render(idle_rendered):
                    for idx in range(self._led_count):
                        hue = int((h + 44) % 256)
                        self._strip.setPixelColor(idx, self._color_from_hsv(hue, s, v // 10))
                    self._show_with_state_overlays()
                    idle_rendered = True
                self._vialrgb_wake.wait()
                continue
            idle_rendered = False
            with self._vialrgb_lock:
                hits = []
                for hit in self._vialrgb_reactive_hits:
                    age = now - float(hit["start"])
                    if age <= 2.4:
                        hits.append(hit)
                        idx = int(hit["idx"])
                        if 0 <= idx < self._led_count:
                            heat[idx] = min(1.0, heat[idx] + (1.0 - age / 2.4))
                self._vialrgb_reactive_hits = hits
            for idx, value in enumerate(heat):
                hue = int((h + (1.0 - value) * 44) % 256)
                brightness = int(max(v // 10, v * value))
                self._strip.setPixelColor(idx, self._color_from_hsv(hue, s, brightness))
            self._show_with_state_overlays()
            stop_event.wait(1.0 / 30.0)

    def _run_vialrgb_key_banner(self, stop_event: threading.Event) -> None:
        min_x, max_x, min_y, max_y = self._coords_bounds()
        display_cols = max(8, min(40, len({round(x, 1) for x, _y in self._led_coords}) or self._led_count))
        display_rows = 7
        visible = [0] * display_cols
        next_frame = time.monotonic()
        while not stop_event.is_set():
            now = time.monotonic()
            h, s, v = self._vialrgb_hsv
            speed = max(1, self._vialrgb_speed)
            fps = 6.0 + (speed / 255.0) * 24.0
            splash_speed = 120.0 + speed * 1.8
            wait_for_input = False
            active_splashes: list[dict[str, float | int]] = []
            with self._vialrgb_lock:
                queue = self._vialrgb_key_banner_columns
                if queue:
                    next_col = queue.pop(0)
                    visible = visible[1:] + [next_col]
                elif any(visible):
                    visible = visible[1:] + [0]
                splashes = []
                for splash in self._vialrgb_splashes:
                    age = now - float(splash["start"])
                    if age <= _KEY_BANNER_MOD_SPLASH_LIFETIME:
                        splashes.append(splash)
                        active_splashes.append(splash)
                self._vialrgb_splashes = splashes
                if not queue and not any(visible) and not active_splashes:
                    self._vialrgb_wake.clear()
                    wait_for_input = True
            if wait_for_input:
                base_color = self._color_from_hsv((h + 48) % 256, s, max(0, v // 16))
                for idx in range(self._led_count):
                    self._strip.setPixelColor(idx, self._semantic_base_color_for_index(idx, base_color))
                self._show_with_state_overlays()
                self._vialrgb_wake.wait()
                next_frame = time.monotonic()
                continue

            for idx in range(self._led_count):
                if idx < len(self._led_coords):
                    x, y = self._led_coords[idx]
                    col = round((x - min_x) / (max_x - min_x) * (display_cols - 1))
                    row = round((y - min_y) / (max_y - min_y) * (display_rows - 1))
                else:
                    col = idx % display_cols
                    row = idx % display_rows
                col = max(0, min(display_cols - 1, int(col)))
                row = max(0, min(display_rows - 1, int(row)))
                mask = visible[col]
                if mask & (1 << row):
                    hue = (h + int(col * 96 / max(1, display_cols - 1))) % 256
                    brightness = int(v * _KEY_BANNER_SCROLL_BRIGHTNESS_SCALE)
                else:
                    hue = (h + 48) % 256
                    brightness = int(max(0, v // 18) * _KEY_BANNER_SCROLL_BRIGHTNESS_SCALE)
                red_f, green_f, blue_f = colorsys.hsv_to_rgb(hue / 255.0, s / 255.0, brightness / 255.0)
                red = red_f * 255.0
                green = green_f * 255.0
                blue = blue_f * 255.0
                for splash in active_splashes:
                    age = now - float(splash["start"])
                    radius = age * splash_speed
                    decay = max(0.0, 1.0 - age / _KEY_BANNER_MOD_SPLASH_LIFETIME)
                    sx = float(splash.get("x", 0.0))
                    sy = float(splash.get("y", 0.0))
                    dx = float(x if idx < len(self._led_coords) else idx) - sx
                    dy = float(y if idx < len(self._led_coords) else 0.0) - sy
                    dist = math.sqrt(dx * dx + dy * dy)
                    diff = abs(dist - radius)
                    if diff > _KEY_BANNER_MOD_SPLASH_WIDTH:
                        continue
                    factor = (1.0 - diff / _KEY_BANNER_MOD_SPLASH_WIDTH) * decay * 0.85
                    if factor <= 0.0:
                        continue
                    splash_hue = int(splash.get("h", h))
                    splash_r, splash_g, splash_b = colorsys.hsv_to_rgb(splash_hue / 255.0, s / 255.0, v / 255.0)
                    red = min(255.0, red + splash_r * 255.0 * factor)
                    green = min(255.0, green + splash_g * 255.0 * factor)
                    blue = min(255.0, blue + splash_b * 255.0 * factor)
                self._strip.setPixelColor(idx, Color(int(red), int(green), int(blue)))
            self._show_with_state_overlays()
            next_frame += 1.0 / fps
            stop_event.wait(max(0.0, next_frame - time.monotonic()))
            if next_frame < time.monotonic() - 1.0:
                next_frame = time.monotonic()

    def _run_vialrgb_solid_reactive(self, stop_event: threading.Event) -> None:
        min_x, max_x, min_y, max_y = self._coords_bounds()
        span = max(max_x - min_x, max_y - min_y, 1.0)
        idle_rendered = False
        while not stop_event.is_set():
            now = time.monotonic()
            h, s, v = self._vialrgb_hsv
            mode = self._vialrgb_mode
            base_rgb = colorsys.hsv_to_rgb(h / 255.0, s / 255.0, max(0, v // 10) / 255.0)
            fallback = (base_rgb[0] * 255, base_rgb[1] * 255, base_rgb[2] * 255)
            rgb = [self._semantic_base_rgb_for_index(idx, fallback) for idx in range(self._led_count)]
            if not self._vialrgb_reactive_has_hits():
                if self._vialrgb_idle_needs_render(idle_rendered):
                    for idx, (r, g, b) in enumerate(rgb):
                        self._strip.setPixelColor(idx, Color(int(r), int(g), int(b)))
                    self._show_with_state_overlays()
                    idle_rendered = True
                self._vialrgb_wake.wait()
                continue
            idle_rendered = False
            with self._vialrgb_lock:
                hits = []
                for hit in self._vialrgb_reactive_hits:
                    age = now - float(hit["start"])
                    lifetime = 0.65 if mode in VIALRGB_SHORT_REACTIVE_MODES else 0.9
                    if age <= lifetime:
                        hits.append(hit)
                    decay = max(0.0, 1.0 - age / lifetime)
                    hx = float(hit.get("x", 0.0))
                    hy = float(hit.get("y", 0.0))
                    hit_hue = int(hit.get("h", h)) if mode in VIALRGB_MULTI_HUE_REACTIVE_MODES else h
                    for idx in range(self._led_count):
                        if idx < len(self._led_coords):
                            lx, ly = self._led_coords[idx]
                        else:
                            lx, ly = float(idx), 0.0
                        dx = abs(lx - hx) / span
                        dy = abs(ly - hy) / span
                        if mode == 32:
                            reach = 1.0 if idx == int(hit["idx"]) else 0.0
                        elif mode in VIALRGB_WIDE_REACTIVE_MODES:
                            reach = max(0.0, 1.0 - math.sqrt(dx * dx + dy * dy) / 0.28)
                        elif mode in VIALRGB_CROSS_REACTIVE_MODES:
                            reach = max(0.0, 1.0 - min(dx, dy) / 0.12)
                        else:  # Nexus / Multinexus
                            reach = max(0.0, 1.0 - math.sqrt(dx * dx + dy * dy) / 0.42)
                        factor = decay * reach
                        if factor <= 0.0:
                            continue
                        red_f, green_f, blue_f = colorsys.hsv_to_rgb(hit_hue / 255.0, s / 255.0, v / 255.0)
                        rgb[idx][0] = min(255.0, rgb[idx][0] + red_f * 255 * factor)
                        rgb[idx][1] = min(255.0, rgb[idx][1] + green_f * 255 * factor)
                        rgb[idx][2] = min(255.0, rgb[idx][2] + blue_f * 255 * factor)
                self._vialrgb_reactive_hits = hits
            for idx, (r, g, b) in enumerate(rgb):
                self._strip.setPixelColor(idx, Color(int(r), int(g), int(b)))
            self._show_with_state_overlays()
            stop_event.wait(1.0 / 60.0)

    def _run_vialrgb_life_game(self, stop_event: threading.Event) -> None:
        idle_rendered = False
        next_frame = time.monotonic()
        while not stop_event.is_set():
            h, s, v = self._vialrgb_hsv
            # Life Game is legible only when each generation has time to be read.
            # Keep the full speed range much slower than reactive/splash effects.
            fps = 0.8 + (max(0, min(255, self._vialrgb_speed)) / 255.0) * 4.6
            frame_interval = 1.0 / fps
            now = time.monotonic()
            with self._vialrgb_lock:
                active = (
                    self._vialrgb_life_game.alive_count > 0
                    or any(self._vialrgb_life_game.frame(self._led_count))
                    or any(self._vialrgb_life_game.transition_intensity_frame(self._led_count))
                )
                pending_only = self._vialrgb_life_game.pending_count > 0 and self._vialrgb_life_game.alive_count == 0
                if active and not (pending_only and now < next_frame):
                    self._vialrgb_life_game.step()
                frame = self._vialrgb_life_game.frame(self._led_count)
                transition = self._vialrgb_life_game.transition_frame(self._led_count)
                transition_intensity = self._vialrgb_life_game.transition_intensity_frame(self._led_count)
                tick = self._vialrgb_life_game.tick_count
                alive_count = self._vialrgb_life_game.alive_count

            if not active:
                if self._vialrgb_idle_needs_render(idle_rendered):
                    base_color = self._color_from_hsv((h + 44) % 256, s, max(0, v // 16))
                    for idx in range(self._led_count):
                        self._strip.setPixelColor(idx, self._semantic_base_color_for_index(idx, base_color))
                    self._show_with_state_overlays()
                    idle_rendered = True
                self._vialrgb_wake.wait()
                next_frame = time.monotonic() + frame_interval
                continue

            idle_rendered = False
            frame_started = time.monotonic()
            self._show_vialrgb_life_game_frame(frame, h, s, v, transition, transition_intensity)
            self._push_life_game_oled_debug(tick, alive_count, fps)
            subframes = 8
            for subframe in range(1, subframes):
                wait_until = frame_started + frame_interval * (subframe / subframes)
                if stop_event.wait(max(0.0, wait_until - time.monotonic())):
                    return
                scaled_transition = self._scale_life_game_dying_transition(
                    transition,
                    transition_intensity,
                    1.0 - subframe / subframes,
                )
                self._show_vialrgb_life_game_frame(frame, h, s, v, transition, scaled_transition)
            next_frame += frame_interval
            stop_event.wait(max(0.0, next_frame - time.monotonic()))
            if next_frame < time.monotonic() - 1.0:
                next_frame = time.monotonic()

    def _show_vialrgb_life_game_frame(
        self,
        frame: list[float],
        h: int,
        s: int,
        v: int,
        transition: list[str] | None = None,
        transition_intensity: list[float] | None = None,
    ) -> None:
        with self._semantic_config_lock:
            for idx, value in enumerate(frame):
                marker = transition[idx] if transition is not None and idx < len(transition) else ""
                if marker == "dying":
                    marker_value = transition_intensity[idx] if transition_intensity is not None and idx < len(transition_intensity) else value
                    brightness = max(v // 12, min(255, int(v * 0.58 * (marker_value ** 1.75))))
                    self._strip.setPixelColor(idx, Color(brightness, 0, 0))
                elif marker in {"born", "pending"}:
                    marker_value = transition_intensity[idx] if transition_intensity is not None and idx < len(transition_intensity) else 1.0
                    ramp = 0.45 + (1.0 - marker_value) * 0.55
                    brightness = max(v // 6, min(255, int(v * ramp)))
                    self._strip.setPixelColor(idx, self._color_from_hsv(h, s, brightness))
                elif marker == "birth_parent":
                    self._strip.setPixelColor(idx, Color(max(96, v), 32, max(96, v)))
                else:
                    brightness = max(v // 16, min(255, int(v * value)))
                    hue = (h + int((1.0 - value) * 44)) % 256
                    self._strip.setPixelColor(idx, self._color_from_hsv(hue, s, brightness))
            self._show_with_state_overlays()

    def _scale_life_game_dying_transition(
        self,
        transition: list[str],
        transition_intensity: list[float],
        scale: float,
    ) -> list[float]:
        factor = max(0.0, min(1.0, scale))
        out = list(transition_intensity)
        for idx, marker in enumerate(transition):
            if marker == "dying" and idx < len(out):
                out[idx] *= factor
            elif marker in {"born", "pending"} and idx < len(out):
                out[idx] *= 1.0 - factor
        return out
