"""Runtime notification fan-out for logicd."""
from __future__ import annotations

from oled_text import ascii_oled_text

import logging
import json
from typing import Any

from hidloom_paths import default_config_file, runtime_file

from .notifications import broadcast_json, layer_payload, write_json
from .protocol import make_key_event_packet
from .state import LogicdRuntime

log = logging.getLogger(__name__)


def _load_ledd_semantic_roles_snapshot() -> tuple[dict[str, Any], str | None]:
    for path in (runtime_file("ledd.json"), default_config_file("ledd.json")):
        try:
            with path.open(encoding="utf-8") as fh:
                config = json.load(fh)
        except FileNotFoundError:
            continue
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("failed to load ledd semantic roles from %s: %s", path, exc)
            continue
        if not isinstance(config, dict):
            log.warning("invalid ledd config root in %s: %s", path, type(config).__name__)
            continue
        raw = config.get("semantic_roles") or config.get("led_semantic_roles") or {}
        if not isinstance(raw, dict):
            log.warning("invalid ledd semantic_roles in %s: %s", path, type(raw).__name__)
            raw = {}
        return dict(raw), str(path)
    return {}, None


class LogicdNotifier:
    def __init__(self, runtime: LogicdRuntime) -> None:
        self.runtime = runtime

    def push_ledd_status(self) -> None:
        runtime = self.runtime
        broadcast_json(
            runtime.ledd_writers,
            layer_payload(runtime.layers._momentary, runtime.layers._toggled, runtime.layers._default_layer),
        )

    def push_ledd_key_event(self, row: int, col: int, is_press: bool) -> None:
        broadcast_json(self.runtime.ledd_writers, {
            "t": "key",
            "kind": "P" if is_press else "R",
            "row": row,
            "col": col,
        })

    def push_ledd_morse_feedback(self, event: dict[str, Any]) -> None:
        payload = {"t": "morse_feedback", **event}
        broadcast_json(self.runtime.ledd_writers, payload)

    def push_ledd_anim(self, anim_id: int) -> None:
        broadcast_json(self.runtime.ledd_writers, {"t": "anim", "id": anim_id})

    def push_ledd_overlay_state(self, state: str, enabled: bool) -> None:
        broadcast_json(self.runtime.ledd_writers, {
            "t": "led_overlay_state",
            "state": state,
            "enabled": enabled,
        })

    def push_ledd_semantic_reload(self) -> None:
        self.push_ledd_semantic_roles()

    def push_ledd_semantic_roles(self) -> None:
        roles, source = _load_ledd_semantic_roles_snapshot()
        payload: dict[str, Any] = {"t": "semantic_roles", "semantic_roles": roles}
        if source is not None:
            payload["source"] = source
        broadcast_json(self.runtime.ledd_writers, payload)

    def push_ledd_semantic_keymap(self) -> None:
        broadcast_json(self.runtime.ledd_writers, {
            "t": "semantic_keymap",
            "layers": self.runtime.layers.layers_snapshot(),
        })

    def push_ledd_vialrgb(self) -> None:
        broadcast_json(self.runtime.ledd_writers, {"t": "vialrgb", **self.runtime.led_state})

    def push_ledd_vialrgb_direct(self, first_index: int, pixels: list) -> None:
        broadcast_json(self.runtime.ledd_writers, {
            "t": "vialrgb_direct",
            "first": first_index,
            "pixels": pixels,
        })

    def push_ledd_vialrgb_direct_pattern(self, pattern: str, fps: float, brightness: int) -> None:
        broadcast_json(self.runtime.ledd_writers, {
            "t": "vialrgb_direct_pattern",
            "pattern": pattern,
            "fps": fps,
            "brightness": brightness,
        })

    def push_ledd_mode(self, mode: str) -> None:
        self.runtime.current_hid_mode = mode
        broadcast_json(self.runtime.ledd_writers, {"t": "mode", "mode": mode})

    def push_bt_pairing_state(self, phase: str, digits: str = "") -> None:
        payload = {"t": "bt_pairing", "phase": phase, "digits": digits}
        broadcast_json(self.runtime.ledd_writers, payload)
        if not write_json(
            self.runtime.i2cd_writer,
            payload,
            on_error="i2cd へのBTペアリング状態送信失敗（切断検知）",
        ):
            self.runtime.i2cd_writer = None

    def push_i2cd_status(self) -> None:
        runtime = self.runtime
        if not write_json(
            runtime.i2cd_writer,
            layer_payload(runtime.layers._momentary, runtime.layers._toggled, runtime.layers._default_layer),
            on_error="i2cd への送信失敗（切断検知）",
        ):
            runtime.i2cd_writer = None

    def push_i2cd_mode(self, mode: str) -> None:
        self.runtime.current_i2cd_mode = mode
        if not write_json(
            self.runtime.i2cd_writer,
            {"t": "mode", "mode": mode},
            on_error="i2cd への送信失敗（切断検知）",
        ):
            self.runtime.i2cd_writer = None

    def push_i2cd_daemon_status(self, statuses: dict[str, bool]) -> None:
        if not write_json(
            self.runtime.i2cd_writer,
            {"t": "daemon_status", "services": statuses},
            on_error="i2cd へのデーモン状態送信失敗（切断検知）",
        ):
            self.runtime.i2cd_writer = None

    def push_i2cd_alert(self, message: str, sec: float = 2.0, immediate: bool = False) -> None:
        message = ascii_oled_text(message)
        if not write_json(
            self.runtime.i2cd_writer,
            {"t": "alert", "msg": message, "sec": sec, "immediate": immediate},
            on_error="i2cd へのアラート送信失敗（切断検知）",
        ):
            self.runtime.i2cd_writer = None

    def push_i2cd_script_exit(self, name: str, exit_code: int) -> None:
        if write_json(
            self.runtime.i2cd_writer,
            {"t": "script_exit", "name": name, "code": exit_code},
            on_error="i2cd への送信失敗（切断検知）",
        ):
            log.info("i2cd へスクリプト終了通知送信: %s (exit_code=%d)", name, exit_code)
        else:
            self.runtime.i2cd_writer = None

    def broadcast_key_event(self, keycode: int, modifier: int, is_press: bool) -> None:
        packet = make_key_event_packet(keycode, modifier, is_press)

        dead: list[Any] = []
        for writer in self.runtime.key_event_writers:
            try:
                writer.write(packet)
            except Exception:
                dead.append(writer)
        for writer in dead:
            self.runtime.key_event_writers.remove(writer)
        self.runtime.key_event_queue.put_nowait(None)
