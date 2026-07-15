"""VialRGB runtime rendering mixin for ledd."""

from __future__ import annotations

import colorsys
import logging
import threading
from typing import Any

from .vialrgb_renderers import VialRgbRenderersMixin
from .strip import Color, all_off
from vialrgb_effects import (
    VIALRGB_ALLOWED_MODES,
    VIALRGB_RENDER_GROUPS,
)

logger = logging.getLogger("ledd")
_VIALRGB_SUPPORTED_MODES = set(VIALRGB_ALLOWED_MODES)
_DIRECT_PATTERN_NAMES = {"rainbow", "chase", "pulse"}
_HSV_COLOR_CACHE_LIMIT = 65536


class VialRgbRuntimeMixin(VialRgbRenderersMixin):
    def _color_from_hsv(self, h: int, s: int, v: int) -> int:
        key = (
            max(0, min(255, int(h))),
            max(0, min(255, int(s))),
            max(0, min(255, int(v))),
        )
        cached = self._vialrgb_color_cache.get(key)
        if cached is not None:
            return cached
        red_f, green_f, blue_f = colorsys.hsv_to_rgb(key[0] / 255.0, key[1] / 255.0, key[2] / 255.0)
        color = Color(round(red_f * 255), round(green_f * 255), round(blue_f * 255))
        if len(self._vialrgb_color_cache) >= _HSV_COLOR_CACHE_LIMIT:
            self._vialrgb_color_cache.clear()
        self._vialrgb_color_cache[key] = color
        return color

    def _start_vialrgb_thread(self, mode: int, target: Any) -> None:
        self._stop_current_animation()
        self._stop_event = threading.Event()
        self._vialrgb_wake.clear()
        self._thread = threading.Thread(
            target=target,
            args=(self._stop_event,),
            daemon=True,
            name=f"vialrgb-{mode}",
        )
        self._thread.start()

    def apply_vialrgb(self, mode: int, speed: int, h: int, s: int, v: int) -> None:
        """Apply supported VialRGB modes exposed to Vial GUI."""
        raw = (mode, speed, h, s, v)
        speed = max(0, min(255, int(speed)))
        h = max(0, min(255, int(h)))
        s = max(0, min(255, int(s)))
        v = max(0, min(255, int(v)))
        if raw != (mode, speed, h, s, v):
            logger.warning("VialRGB values clamped: raw=%r clamped=(%d,%d,%d,%d,%d)", raw, mode, speed, h, s, v)
        if mode not in _VIALRGB_SUPPORTED_MODES:
            logger.warning("未対応の VialRGB mode: %d; 現在の effect を維持", mode)
            self._vialrgb_speed = speed
            self._vialrgb_hsv = (h, s, v)
            return

        self._vialrgb_mode = mode
        self._vialrgb_speed = speed
        self._vialrgb_hsv = (h, s, v)

        if mode == 0:
            self._stop_current_animation()
            all_off(self._strip, self._led_count)
            logger.info("VialRGB mode=0 disable")
            return

        if mode == 1:
            self._stop_current_animation()
            all_off(self._strip, self._led_count)
            logger.info("VialRGB mode=1 direct control")
            return

        if mode == 6:
            self._start_vialrgb_thread(mode, self._run_vialrgb_breathing)
            logger.info("VialRGB mode=6 breathing speed=%d hsv=(%d,%d,%d)", speed, h, s, v)
            return

        if mode == 13:
            self._start_vialrgb_thread(mode, self._run_vialrgb_cycle_all)
            logger.info("VialRGB mode=13 cycle all speed=%d hsv=(%d,%d,%d)", speed, h, s, v)
            return

        if mode in VIALRGB_RENDER_GROUPS["gradient"]:
            self._start_vialrgb_thread(mode, self._run_vialrgb_gradient)
            logger.info("VialRGB mode=%d gradient speed=%d hsv=(%d,%d,%d)", mode, speed, h, s, v)
            return

        if mode == 3:
            self._start_vialrgb_thread(mode, self._run_vialrgb_alphas_mods)
            logger.info("VialRGB mode=3 alphas mods speed=%d hsv=(%d,%d,%d)", speed, h, s, v)
            return

        if mode in VIALRGB_RENDER_GROUPS["directional_cycle"]:
            self._start_vialrgb_thread(mode, self._run_vialrgb_directional_cycle)
            logger.info("VialRGB mode=%d directional cycle speed=%d hsv=(%d,%d,%d)", mode, speed, h, s, v)
            return

        if mode in VIALRGB_RENDER_GROUPS["chevron_beacon"]:
            self._start_vialrgb_thread(mode, self._run_vialrgb_chevron_beacon)
            logger.info("VialRGB mode=%d chevron/beacon speed=%d hsv=(%d,%d,%d)", mode, speed, h, s, v)
            return

        if mode in VIALRGB_RENDER_GROUPS["radial_cycle"]:
            self._start_vialrgb_thread(mode, self._run_vialrgb_radial_cycle)
            logger.info("VialRGB mode=%d radial cycle speed=%d hsv=(%d,%d,%d)", mode, speed, h, s, v)
            return

        if mode == 26:
            self._start_vialrgb_thread(mode, self._run_vialrgb_hue_breathing)
            logger.info("VialRGB mode=26 hue breathing speed=%d hsv=(%d,%d,%d)", speed, h, s, v)
            return

        if mode == 28:
            self._start_vialrgb_thread(mode, self._run_vialrgb_hue_wave)
            logger.info("VialRGB mode=28 hue wave speed=%d hsv=(%d,%d,%d)", speed, h, s, v)
            return

        if mode == 27:
            self._start_vialrgb_thread(mode, self._run_vialrgb_hue_pendulum)
            logger.info("VialRGB mode=27 hue pendulum speed=%d hsv=(%d,%d,%d)", speed, h, s, v)
            return

        if mode in VIALRGB_RENDER_GROUPS["position_pattern"]:
            self._start_vialrgb_thread(mode, self._run_vialrgb_position_pattern)
            logger.info("VialRGB mode=%d position pattern speed=%d hsv=(%d,%d,%d)", mode, speed, h, s, v)
            return

        if mode in VIALRGB_RENDER_GROUPS["pixel_rain"]:
            with self._vialrgb_lock:
                self._vialrgb_pixel_rain = []
            self._start_vialrgb_thread(mode, self._run_vialrgb_pixel_rain)
            logger.info("VialRGB mode=%d rain speed=%d hsv=(%d,%d,%d)", mode, speed, h, s, v)
            return

        if mode == 30:
            self._start_vialrgb_thread(mode, self._run_vialrgb_digital_rain)
            logger.info("VialRGB mode=30 digital rain speed=%d hsv=(%d,%d,%d)", speed, h, s, v)
            return

        if mode == 29:
            with self._vialrgb_lock:
                self._vialrgb_reactive_hits = []
            self._start_vialrgb_thread(mode, self._run_vialrgb_typing_heatmap)
            logger.info("VialRGB mode=29 typing heatmap speed=%d hsv=(%d,%d,%d)", speed, h, s, v)
            return

        if mode == 31:
            with self._vialrgb_lock:
                self._vialrgb_reactive_hits = []
            self._start_vialrgb_thread(mode, self._run_vialrgb_solid_reactive_simple)
            logger.info("VialRGB mode=31 solid reactive simple speed=%d hsv=(%d,%d,%d)", speed, h, s, v)
            return

        if mode in VIALRGB_RENDER_GROUPS["solid_reactive"]:
            with self._vialrgb_lock:
                self._vialrgb_reactive_hits = []
            self._start_vialrgb_thread(mode, self._run_vialrgb_solid_reactive)
            logger.info("VialRGB mode=%d solid reactive speed=%d hsv=(%d,%d,%d)", mode, speed, h, s, v)
            return

        if mode in VIALRGB_RENDER_GROUPS["splash"]:
            with self._vialrgb_lock:
                self._vialrgb_splashes = []
            self._start_vialrgb_thread(mode, self._run_vialrgb_multisplash)
            logger.info("VialRGB mode=%d splash speed=%d hsv=(%d,%d,%d)", mode, speed, h, s, v)
            return

        if mode in VIALRGB_RENDER_GROUPS["direct_splash"]:
            with self._vialrgb_lock:
                self._vialrgb_splashes = []
            self._stop_current_animation()
            if self._direct_frame_active:
                self._render_direct_frame_overlay()
            else:
                all_off(self._strip, self._led_count)
            logger.info("VialRGB mode=%d direct splash speed=%d hsv=(%d,%d,%d)", mode, speed, h, s, v)
            return

        if mode in VIALRGB_RENDER_GROUPS["life_game"]:
            with self._vialrgb_lock:
                self._vialrgb_life_game.clear()
            self._start_vialrgb_thread(mode, self._run_vialrgb_life_game)
            logger.info("VialRGB mode=%d life game speed=%d hsv=(%d,%d,%d)", mode, speed, h, s, v)
            return

        if mode in VIALRGB_RENDER_GROUPS["key_banner"]:
            with self._vialrgb_lock:
                self._vialrgb_key_banner_columns = []
            self._start_vialrgb_thread(mode, self._run_vialrgb_key_banner)
            logger.info("VialRGB mode=%d key banner speed=%d hsv=(%d,%d,%d)", mode, speed, h, s, v)
            return

        if mode == 44:
            self._start_vialrgb_thread(mode, self._run_vialrgb_pixel_fractal)
            logger.info("VialRGB mode=44 pixel fractal speed=%d hsv=(%d,%d,%d)", speed, h, s, v)
            return

        self._stop_current_animation()
        color = self._color_from_hsv(*self._vialrgb_hsv)
        for idx in range(self._led_count):
            self._strip.setPixelColor(idx, color)
        self._strip.show()
        logger.info("VialRGB mode=%d solid hsv=(%d,%d,%d)", mode, h, s, v)

    def apply_vialrgb_direct_pattern(self, pattern: str, fps: float, brightness: int) -> None:
        pattern = str(pattern)
        if pattern not in _DIRECT_PATTERN_NAMES:
            logger.warning("VialRGB direct pattern ignored: unsupported pattern=%r", pattern)
            return
        fps = max(1.0, min(60.0, float(fps)))
        brightness = max(0, min(255, int(brightness)))
        self._vialrgb_mode = 1
        self._vialrgb_direct_pattern = {
            "pattern": pattern,
            "fps": fps,
            "brightness": brightness,
        }
        self._start_vialrgb_thread(1, self._run_vialrgb_direct_pattern)
        logger.info(
            "VialRGB direct pattern pattern=%s fps=%.1f brightness=%d",
            pattern, fps, brightness,
        )

    def apply_vialrgb_direct(self, first_index: int, pixels: list[Any]) -> None:
        """Apply a VialRGB direct_fastset HSV chunk."""
        if first_index < 0:
            logger.warning("VialRGB direct ignored: negative first_index=%d", first_index)
            return
        if not isinstance(pixels, list):
            logger.warning("VialRGB direct ignored: pixels must be list, got %s", type(pixels).__name__)
            return
        if self._vialrgb_mode != 1:
            self._vialrgb_mode = 1
            self._stop_current_animation()

        applied = 0
        skipped = 0
        for offset, pixel in enumerate(pixels):
            idx = first_index + offset
            if not (0 <= idx < self._led_count):
                skipped += 1
                continue
            try:
                h, s, v = (int(pixel[0]), int(pixel[1]), int(pixel[2]))
            except (TypeError, ValueError, IndexError):
                logger.warning("VialRGB direct pixel ignored: offset=%d value=%r", offset, pixel)
                skipped += 1
                continue
            self._strip.setPixelColor(
                idx,
                self._color_from_hsv(
                    max(0, min(255, h)),
                    max(0, min(255, s)),
                    max(0, min(255, v)),
                ),
            )
            applied += 1
        self._strip.show()
        if skipped:
            logger.warning(
                "VialRGB direct applied with skipped pixels: first=%d applied=%d skipped=%d total_leds=%d",
                first_index, applied, skipped, self._led_count,
            )
