"""LED-related ctrl JSON-line commands for logicd."""
from __future__ import annotations

import logging
from typing import Any

from .ctrl_common import clamp_with_log, ctrl_error, ctrl_int, ctrl_response

log = logging.getLogger(__name__)
_DIRECT_PATTERN_NAMES = {"rainbow", "chase", "pulse"}


def validate_vialrgb_direct_pixels(pixels: object) -> list:
    if not isinstance(pixels, list):
        raise ValueError("pixels must be a list")
    for idx, pixel in enumerate(pixels):
        if not isinstance(pixel, list) or len(pixel) != 3:
            raise ValueError(f"pixel[{idx}] must be [h,s,v]")
        for component in pixel:
            component_i = int(component)
            if not (0 <= component_i <= 255):
                raise ValueError(f"pixel[{idx}] component out of range: {component_i}")
    return pixels


async def process_led_json(msg: dict, ctx: Any, writer: Any = None) -> None:
    op = msg.get("op")
    if op == "vialrgb_get":
        if writer is not None:
            await ctrl_response(writer, {"t": "LED", "result": "ok", **ctx.normalize_led_state(ctx.led_state)})
        return

    if op == "vialrgb_save":
        try:
            path = ctx.save_led_state()
            if writer is not None:
                await ctrl_response(writer, {"t": "LED", "result": "ok", "path": path})
            log.info("ctrl LED: state saved to %s", path)
        except Exception as exc:
            if writer is not None:
                await ctrl_response(writer, {"t": "LED", "result": "error", "msg": str(exc)})
            log.warning("ctrl LED: save failed: %s", exc)
        return

    if op == "vialrgb_reset":
        try:
            previous_mode = int(ctx.led_state.get("mode", 0))
            ctx.cancel_led_state_save()
            ctx.load_led_state()
            ctx.remember_nonzero_led_mode()
            ctx.push_ledd_vialrgb()
            ctx.notify_i2cd_led_effect_if_changed(previous_mode, int(ctx.led_state.get("mode", 0)))
            if writer is not None:
                await ctrl_response(writer, {
                    "t": "LED",
                    "result": "ok",
                    **ctx.normalize_led_state(ctx.led_state),
                })
            log.info("ctrl LED: state reset to saved file")
        except Exception as exc:
            if writer is not None:
                await ctrl_response(writer, {"t": "LED", "result": "error", "msg": str(exc)})
            log.warning("ctrl LED: reset failed: %s", exc)
        return

    if op == "vialrgb_direct":
        try:
            first_index = ctrl_int(msg, "first", default=0)
            if first_index < 0:
                raise ValueError(f"first must be >= 0: {first_index}")
            pixels = validate_vialrgb_direct_pixels(msg.get("pixels", []))
            ctx.push_ledd_vialrgb_direct(first_index, pixels)
            if writer is not None:
                await ctrl_response(writer, {"t": "LED", "result": "ok"})
            log.debug("ctrl LED: vialrgb direct first=%d count=%d", first_index, len(pixels))
        except (TypeError, ValueError) as exc:
            if writer is not None:
                await ctrl_response(writer, {"t": "LED", "result": "error", "msg": str(exc)})
            log.warning("ctrl LED: invalid direct request: %s", exc)
        return

    if op == "vialrgb_direct_pattern":
        try:
            pattern = str(msg.get("pattern", "rainbow"))
            if pattern not in _DIRECT_PATTERN_NAMES:
                raise ValueError(f"unsupported pattern: {pattern!r}")
            fps = float(msg.get("fps", 16.0))
            if fps <= 0:
                raise ValueError(f"fps must be > 0: {fps}")
            fps = max(1.0, min(60.0, fps))
            brightness = clamp_with_log(
                "brightness",
                ctrl_int(msg, "brightness", default=96),
                0,
                255,
                "ctrl LED direct pattern",
            )
            ctx.push_ledd_vialrgb_direct_pattern(pattern, fps, brightness)
            if writer is not None:
                await ctrl_response(writer, {
                    "t": "LED",
                    "result": "ok",
                    "pattern": pattern,
                    "fps": fps,
                    "brightness": brightness,
                })
            log.info("ctrl LED: vialrgb direct pattern=%s fps=%.1f brightness=%d", pattern, fps, brightness)
        except (TypeError, ValueError) as exc:
            if writer is not None:
                await ctrl_response(writer, {"t": "LED", "result": "error", "msg": str(exc)})
            log.warning("ctrl LED: invalid direct pattern request: %s", exc)
        return

    if op == "key_event":
        if getattr(ctx, "push_ledd_key_event", None) is None:
            await ctrl_error(writer, "LED", "LED key event diagnostic route is not available")
            return
        try:
            kind = str(msg.get("kind", "")).upper()
            if kind not in {"P", "R"}:
                raise ValueError(f"kind must be P or R: {kind!r}")
            row = clamp_with_log("row", ctrl_int(msg, "row"), 0, 31, "ctrl LED key_event")
            col = clamp_with_log("col", ctrl_int(msg, "col"), 0, 31, "ctrl LED key_event")
            ctx.push_ledd_key_event(row, col, kind == "P")
            if writer is not None:
                await ctrl_response(writer, {"t": "LED", "result": "ok", "op": "key_event", "kind": kind, "row": row, "col": col})
            log.debug("ctrl LED: diagnostic key_event kind=%s row=%d col=%d", kind, row, col)
        except (TypeError, ValueError) as exc:
            if writer is not None:
                await ctrl_response(writer, {"t": "LED", "result": "error", "msg": str(exc)})
            log.warning("ctrl LED: invalid key_event request: %s", exc)
        return

    if op != "vialrgb":
        await ctrl_error(writer, "LED", f"unsupported LED op: {msg.get('op')!r}")
        return

    try:
        previous_mode = int(ctx.led_state.get("mode", 0))
        mode = ctx.normalize_vialrgb_mode(ctrl_int(msg, "mode"))
        speed = clamp_with_log("speed", ctrl_int(msg, "speed"), 0, 255, "ctrl LED")
        h = clamp_with_log("h", ctrl_int(msg, "h"), 0, 255, "ctrl LED")
        s = clamp_with_log("s", ctrl_int(msg, "s"), 0, 255, "ctrl LED")
        v = clamp_with_log("v", ctrl_int(msg, "v"), 0, 255, "ctrl LED")
        ctx.led_state.update(ctx.normalize_led_state({
            "mode": mode,
            "speed": speed,
            "h": h,
            "s": s,
            "v": v,
        }))
        ctx.remember_nonzero_led_mode()
        ctx.push_ledd_vialrgb()
        save_state = msg.get("save", True) is not False
        if save_state:
            ctx.schedule_led_state_save()
        ctx.notify_i2cd_led_effect_if_changed(previous_mode, int(ctx.led_state.get("mode", 0)))
        if writer is not None:
            await ctrl_response(writer, {"t": "LED", "result": "ok"})
        log.info(
            "ctrl LED: vialrgb mode=%d speed=%d hsv=(%d,%d,%d) save=%s",
            ctx.led_state["mode"], ctx.led_state["speed"], ctx.led_state["h"], ctx.led_state["s"], ctx.led_state["v"],
            save_state,
        )
    except (KeyError, TypeError, ValueError) as exc:
        if writer is not None:
            await ctrl_response(writer, {"t": "LED", "result": "error", "msg": str(exc)})
        log.warning("ctrl LED: invalid request: %s", exc)
