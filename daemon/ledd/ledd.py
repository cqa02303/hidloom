#!/usr/bin/env python3
"""ledd - LED制御デーモン

config/default/ledd.json の設定に基づいて WS2812B/SK6812 LEDストリップのアニメーションを制御する。

機能:
  - logicd の ledd_socket (Unix ドメインソケット) に接続してイベントを受信。
  - direct-frame socket で 1 packet = 1 full LED frame を受け取り LED buffer へ反映する。
  - direct-frame producer 切断時は設定された fallback policy を適用する。
"""

import colorsys
import json
import logging
import math
import os
import re
import signal
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from .animations import REGISTRY, AnimationBase
from .direct_frame import DirectFramePacket
from .direct_frame_socket import DEFAULT_DIRECT_FRAME_SOCKET, DirectFrameReceiverStats, direct_frame_receiver
from .logicd_client import handle_logicd_message as _handle_logicd_message
from .logicd_client import logicd_receiver
from .life_game import LedLifeGameState, cells_from_led_positions
from .semantic_roles import (
    LedSemanticRoleConfig,
    infer_role_from_keycode,
    lock_state_for_keycode,
    normalize_led_semantic_role_config,
)
from .strip import Color, PixelStrip, all_off, init_strip
from .vialrgb_runtime import VialRgbRuntimeMixin
from vialrgb_effects import (
    VIALRGB_DIRECT_MULTI_SPLASH_MODES,
    VIALRGB_DIRECT_SPLASH_MODES,
    VIALRGB_MULTI_SPLASH_MODES,
    VIALRGB_REACTIVE_MODES,
    VIALRGB_RENDER_GROUPS,
    VIALRGB_SPLASH_MODES,
)

_LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ledd")

_BASE_DIR = Path(__file__).resolve().parents[2]
from hidloom_paths import default_config_file, runtime_file
_CONFIG_PATH = default_config_file("ledd.json", _BASE_DIR)
_KEYMAP_PATHS = (
    runtime_file("keymap.json"),
    default_config_file("keymap.json", _BASE_DIR),
)
_LAYER_ACTION_RE = re.compile(r"^(?:MO|TG|TO|DF|OSL|TT)\((\d+)\)$|^LT\((\d+),")
_DEFAULT_LAYER_OVERLAY_COLORS = (
    [0, 80, 0],
    [0, 48, 120],
    [96, 0, 96],
    [120, 60, 0],
    [0, 96, 96],
    [120, 0, 48],
)
DIRECT_FRAME_FALLBACK_POLICIES = {"keep_last_frame", "off", "restore_default"}
DEFAULT_DIRECT_FRAME_STATUS_PATH = "/tmp/ledd_direct_frame_status.json"
DEFAULT_I2CD_SOCKET_PATH = "/tmp/i2c_events.sock"
DEFAULT_STARTUP_EFFECT = {
    "enabled": True,
    "kind": "vialrgb",
    "mode": 6,
    "speed": 48,
    "h": 140,
    "s": 120,
    "v": 32,
}
_MORSE_LED_COLORS = {
    "pending": Color(255, 150, 0),
    "commit": Color(0, 220, 60),
    "fallback": Color(230, 0, 45),
    "cancel": Color(230, 0, 45),
}
_MORSE_LED_DURATIONS = {
    "pending": 0.28,
    "commit": 0.28,
    "fallback": 0.45,
    "cancel": 0.45,
}

_HELP = f"""usage: python3 -m ledd.ledd

LED animation/control daemon.

Options:
  -h, --help    show this help and exit

Configuration:
  default config path: {_CONFIG_PATH}

Common environment:
  LOG_LEVEL
  LEDD_DIRECT_FRAME_SOCK
  LEDD_DIRECT_FRAME_STATUS
  LEDD_DIRECT_FRAME_FALLBACK
  LEDD_I2CD_SOCKET
"""


def load_config(path: Path) -> dict[str, Any]:
    """設定ファイルを読み込んで返す"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_led_chain_order(config: dict[str, Any]) -> list[str]:
    """leds セクションのキーを記述順のまま返す。

    JSON の記述順が LED の接続順として扱われる。
    """
    return list(config.get("leds", {}).keys())


def load_keycode_layers_by_position(path: Path | None = None) -> list[dict[str, str]]:
    """Return keycodes indexed by ``row,col`` for every layer in keymap.json."""
    paths = (path,) if path is not None else _KEYMAP_PATHS
    data: dict[str, Any] | None = None
    loaded_path: Path | None = None
    for candidate in paths:
        try:
            data = load_config(candidate)
            loaded_path = candidate
            break
        except (FileNotFoundError, PermissionError, json.JSONDecodeError) as exc:
            logger.warning("keymap load failed for semantic LED roles: %s: %s", candidate, exc)
    if data is None:
        return []
    logger.info("semantic LED keymap loaded from %s", loaded_path)
    return keycode_layers_by_position_from_keymap(data)


def keycode_layers_by_position_from_keymap(data: Mapping[str, Any]) -> list[dict[str, str]]:
    """Return keycodes indexed by ``row,col`` from a loaded keymap document."""
    layout = data.get("_layout_def", {})
    layers = data.get("layers", [])
    if not isinstance(layout, Mapping) or not isinstance(layers, list) or not layers:
        return []
    out: list[dict[str, str]] = []
    for layer in layers:
        if not isinstance(layer, Mapping):
            out.append({})
            continue
        keycodes: dict[str, str] = {}
        for group, coords in layout.items():
            values = layer.get(group)
            if not isinstance(coords, list) or not isinstance(values, list):
                continue
            for coord, keycode in zip(coords, values):
                if not isinstance(coord, list) or len(coord) < 2:
                    continue
                try:
                    pos = f"{int(coord[0])},{int(coord[1])}"
                except (TypeError, ValueError):
                    continue
                if isinstance(keycode, str) and keycode:
                    keycodes[pos] = keycode
        out.append(keycodes)
    return out


def load_base_keycodes_by_position(path: Path | None = None) -> dict[str, str]:
    """Return base-layer keycodes indexed by ``row,col`` from keymap.json."""
    layers = load_keycode_layers_by_position(path)
    return layers[0] if layers else {}


def _keycode_layers_from_runtime_config(
    config: Mapping[str, Any],
    *,
    allow_keymap_fallback: bool = True,
) -> list[dict[str, str]]:
    raw_layers = config.get("keycode_layers_by_position") or config.get("keycodes_by_layer")
    if isinstance(raw_layers, list):
        return [
            {str(key): str(value) for key, value in layer.items()}
            for layer in raw_layers
            if isinstance(layer, Mapping)
        ]
    raw_keycodes = config.get("keycodes_by_position") or config.get("keycode_by_led_key") or config.get("matrix_keycodes")
    if isinstance(raw_keycodes, Mapping):
        return [{str(key): str(value) for key, value in raw_keycodes.items()}]
    if not allow_keymap_fallback:
        return []
    return load_keycode_layers_by_position()


def _load_keymap_on_startup(config: Mapping[str, Any]) -> bool:
    raw = config.get("semantic_roles") or config.get("led_semantic_roles")
    if isinstance(raw, Mapping) and "load_keymap_on_startup" in raw:
        value = raw.get("load_keymap_on_startup")
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off", "disabled"}
        return bool(value)
    return True


def _layer_target_from_action(action: str) -> int | None:
    match = _LAYER_ACTION_RE.match(str(action))
    if not match:
        return None
    raw = match.group(1) or match.group(2)
    try:
        layer = int(raw)
    except (TypeError, ValueError):
        return None
    return layer if layer > 0 else None


def _default_layer_overlay_color(layer: int) -> list[int]:
    return list(_DEFAULT_LAYER_OVERLAY_COLORS[(layer - 1) % len(_DEFAULT_LAYER_OVERLAY_COLORS)])


def _default_semantic_role_config(keycode_layers_by_position: list[dict[str, str]]) -> dict[str, Any]:
    keycodes_by_position = keycode_layers_by_position[0] if keycode_layers_by_position else {}
    layer_keys_by_target: dict[int, set[str]] = {}
    for keycode in keycodes_by_position.values():
        layer = _layer_target_from_action(keycode)
        if layer is not None:
            layer_keys_by_target.setdefault(layer, set()).add(keycode)
    for layer in range(2, len(keycode_layers_by_position)):
        layer_keys_by_target.setdefault(layer, set())
    overlays: dict[str, dict[str, Any]] = {
        "caps_lock": {"keys": ["KC_CAPS"], "color": [0, 0, 96], "priority": 40},
    }
    for layer, layer_keys in sorted(layer_keys_by_target.items()):
        overlays[f"layer:{layer}"] = {
            "keys": sorted(layer_keys),
            "include_layer_changes": True,
            "color": _default_layer_overlay_color(layer),
            "effect_blend": "max",
            "priority": 30,
        }
    return {
        "state_overlays": overlays,
        "reactive": {"exclude_roles": ["modifier", "function", "layer", "lock"]},
    }


def _layer_index_from_overlay_name(name: str) -> int | None:
    for prefix in ("layer:", "layer_"):
        if name.startswith(prefix):
            try:
                return int(name[len(prefix) :])
            except ValueError:
                return None
    return None


def _expand_layer_change_overlay_leds(raw: dict[str, Any], keycode_layers_by_position: list[dict[str, str]]) -> None:
    if not keycode_layers_by_position:
        return
    overlays = raw.get("state_overlays")
    if not isinstance(overlays, Mapping):
        return
    base_layer = keycode_layers_by_position[0]
    for name, overlay in overlays.items():
        if not isinstance(name, str) or not isinstance(overlay, dict):
            continue
        if not overlay.get("include_layer_changes", False):
            continue
        layer_index = _layer_index_from_overlay_name(name)
        if layer_index is None or layer_index <= 0 or layer_index >= len(keycode_layers_by_position):
            continue
        changed_leds = []
        for pos, action in keycode_layers_by_position[layer_index].items():
            if not action or action == "KC_TRNS" or action == base_layer.get(pos):
                continue
            changed_leds.append(pos)
        if not changed_leds:
            continue
        existing_leds = overlay.get("leds", overlay.get("extra_leds", []))
        if not isinstance(existing_leds, list):
            existing_leds = []
        overlay["leds"] = list(dict.fromkeys([*existing_leds, *sorted(changed_leds)]))


def _semantic_role_config_from_runtime(config: Mapping[str, Any], keycode_layers_by_position: list[dict[str, str]]) -> LedSemanticRoleConfig:
    raw = dict(_default_semantic_role_config(keycode_layers_by_position))
    user_raw = config.get("semantic_roles") or config.get("led_semantic_roles")
    if isinstance(user_raw, Mapping):
        user_copy = dict(user_raw)
        has_user_overlays = "state_overlays" in user_copy
        user_overlays = user_copy.get("state_overlays", {})
        if not isinstance(user_overlays, Mapping):
            user_overlays = {}
        default_overlays = dict(raw.get("state_overlays", {}))
        if has_user_overlays:
            default_overlays = {
                name: overlay
                for name, overlay in default_overlays.items()
                if _layer_index_from_overlay_name(str(name)) is not None
            }
        for name in user_overlays:
            if not isinstance(name, str):
                continue
            layer = _layer_index_from_overlay_name(name)
            if layer is None:
                continue
            default_overlays.pop(f"layer:{layer}", None)
            default_overlays.pop(f"layer_{layer}", None)
        merged_overlays = {
            **default_overlays,
            **dict(user_overlays),
        }
        raw.update(user_copy)
        raw["state_overlays"] = merged_overlays
    _expand_layer_change_overlay_leds(raw, keycode_layers_by_position)
    return normalize_led_semantic_role_config(raw)


def direct_frame_fallback_policy(config: dict[str, Any]) -> str:
    """Return direct-frame producer disconnect fallback policy.

    Supported policies:
    - keep_last_frame: keep the last received full frame displayed.
    - off: turn LEDs off on producer disconnect.
    - restore_default: restart the configured default animation.
    """
    ipc_cfg = config.get("ipc", {}) if isinstance(config, dict) else {}
    raw = os.environ.get("LEDD_DIRECT_FRAME_FALLBACK") or ipc_cfg.get("direct_frame_fallback", "keep_last_frame")
    policy = str(raw).strip().lower().replace("-", "_")
    if policy not in DIRECT_FRAME_FALLBACK_POLICIES:
        logger.warning("unknown direct-frame fallback policy %r; using keep_last_frame", raw)
        return "keep_last_frame"
    return policy


def startup_effect_config(config: Mapping[str, Any]) -> dict[str, Any]:
    raw = config.get("startup_effect", DEFAULT_STARTUP_EFFECT)
    if raw is None:
        return {"enabled": False}
    if not isinstance(raw, Mapping):
        logger.warning("invalid startup_effect root: %s; using default", type(raw).__name__)
        raw = DEFAULT_STARTUP_EFFECT
    effect = dict(DEFAULT_STARTUP_EFFECT)
    effect.update(raw)
    effect["enabled"] = bool(effect.get("enabled", True))
    effect["kind"] = str(effect.get("kind", "vialrgb")).strip().lower()
    for key, default in DEFAULT_STARTUP_EFFECT.items():
        if key in {"enabled", "kind"}:
            continue
        try:
            effect[key] = int(effect.get(key, default))
        except (TypeError, ValueError):
            logger.warning("invalid startup_effect.%s=%r; using %r", key, effect.get(key), default)
            effect[key] = default
    return effect


def apply_startup_effect(manager: "AnimationManager", config: Mapping[str, Any]) -> bool:
    effect = startup_effect_config(config)
    if not effect.get("enabled", True):
        return False
    kind = effect.get("kind")
    if kind != "vialrgb":
        logger.warning("unsupported startup_effect.kind=%r; using animation.default_id", kind)
        return False
    manager.apply_vialrgb(
        int(effect["mode"]),
        int(effect["speed"]),
        int(effect["h"]),
        int(effect["s"]),
        int(effect["v"]),
    )
    logger.info(
        "startup effect applied: kind=vialrgb mode=%d speed=%d hsv=(%d,%d,%d)",
        int(effect["mode"]),
        int(effect["speed"]),
        int(effect["h"]),
        int(effect["s"]),
        int(effect["v"]),
    )
    return True


def write_direct_frame_status(
    path: str,
    stats: DirectFrameReceiverStats,
    *,
    led_count: int,
    socket_path: str,
    fallback: str,
    runtime: dict[str, Any] | None = None,
) -> None:
    """Write a small side-effect-free status snapshot for HTTP diagnostics."""
    data = {
        "available": True,
        "led_count": int(led_count),
        "socket_path": socket_path,
        "fallback": fallback,
        "updated_at": time.time(),
        **stats.as_dict(),
        **(runtime or {}),
    }
    target = Path(path)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        tmp.replace(target)
    except OSError as exc:
        logger.debug("direct-frame status write failed: %s", exc)
        try:
            tmp.unlink()
        except OSError:
            pass


def direct_frame_status_writer(
    path: str,
    stats: DirectFrameReceiverStats,
    stop_event: threading.Event,
    *,
    led_count: int,
    socket_path: str,
    fallback: str,
    runtime_getter: Callable[[], dict[str, Any]] | None = None,
    interval: float = 1.0,
) -> None:
    while not stop_event.wait(interval):
        runtime = runtime_getter() if runtime_getter is not None else None
        write_direct_frame_status(path, stats, led_count=led_count, socket_path=socket_path, fallback=fallback, runtime=runtime)
    runtime = runtime_getter() if runtime_getter is not None else None
    write_direct_frame_status(path, stats, led_count=led_count, socket_path=socket_path, fallback=fallback, runtime=runtime)


def _color_to_rgb(color: int) -> list[int]:
    return [
        (int(color) >> 16) & 0xFF,
        (int(color) >> 8) & 0xFF,
        int(color) & 0xFF,
    ]


class _SemanticOverlayStrip:
    """PixelStrip proxy that records animation base colors before overlays."""

    def __init__(self, manager: "AnimationManager", raw_strip: Any) -> None:
        self._manager = manager
        self._raw_strip = raw_strip

    def setPixelColor(self, idx: int, color: int) -> None:
        self._manager._set_base_pixel(idx, color)

    def show(self) -> None:
        self._manager._show_with_state_overlays()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._raw_strip, name)


class AnimationManager(VialRgbRuntimeMixin):
    """アニメーションの登録・切り替え・キーイベント転送を管理するクラス。"""

    def __init__(
        self,
        strip: Any,
        led_count: int,
        config: dict[str, Any],
        led_positions: dict[str, dict],
    ) -> None:
        self._raw_strip = strip
        self._led_count = led_count
        self._semantic_base_pixels: list[int] = [Color(0, 0, 0)] * led_count
        self._strip = _SemanticOverlayStrip(self, strip)
        self._config = config
        self._led_positions = led_positions
        self._semantic_config_lock = threading.RLock()
        self._semantic_reload_timer: threading.Timer | None = None
        self._semantic_reload_lock = threading.Lock()
        led_cfg = config.get("led") or {}
        try:
            self._show_min_interval_sec = float(led_cfg.get("show_min_interval_sec", 0.0))
        except (TypeError, ValueError):
            self._show_min_interval_sec = 0.0
        self._show_min_interval_sec = max(0.0, min(0.25, self._show_min_interval_sec))
        self._show_lock = threading.Lock()
        self._last_show_at = 0.0
        self._deferred_show_lock = threading.Lock()
        self._deferred_show_timer: threading.Timer | None = None
        self._keycode_layers_by_position = _keycode_layers_from_runtime_config(
            config,
            allow_keymap_fallback=_load_keymap_on_startup(config),
        )
        if self._keycode_layers_by_position:
            self._keycode_by_position = self._keycode_layers_by_position[0]
        else:
            self._keycode_by_position = {}
        self._semantic_roles = _semantic_role_config_from_runtime(config, self._keycode_layers_by_position)
        self._active_semantic_states: set[str] = set()
        self._active_layer = 0
        self._active_layers = [0]
        self._default_anim_id = int(config.get("animation", {}).get("default_id", 0))
        self._direct_frame_fallback = direct_frame_fallback_policy(config)
        self._stop_event: threading.Event = threading.Event()
        self._thread: threading.Thread | None = None
        self._current_anim: AnimationBase | None = None
        self._current_id: int = -1
        self._vialrgb_mode: int = 2
        self._vialrgb_speed: int = 128
        self._vialrgb_hsv: tuple[int, int, int] = (0, 0, 128)
        self._vialrgb_lock = threading.Lock()
        self._vialrgb_wake = threading.Event()
        self._vialrgb_overlay_dirty = False
        self._vialrgb_reactive_hits: list[dict[str, Any]] = []
        self._vialrgb_splashes: list[dict[str, Any]] = []
        self._vialrgb_pixel_rain: list[dict[str, Any]] = []
        self._vialrgb_key_banner_columns: list[int] = []
        self._vialrgb_direct_pattern: dict[str, Any] = {
            "pattern": "rainbow",
            "fps": 16.0,
            "brightness": 96,
        }
        self._vialrgb_color_cache: dict[tuple[int, int, int], int] = {}
        self._direct_frame_active = False
        self._direct_frame_last_id: int | None = None
        self._direct_frame_base_rgb: list[tuple[int, int, int]] = [(0, 0, 0)] * led_count
        self._direct_frame_applied_frames = 0
        self._direct_frame_ignored_frames = 0
        self._direct_frame_lock = threading.Lock()
        self._morse_flash_overlays: dict[int, tuple[int, float]] = {}
        self._led_keys = list(led_positions.keys())
        self._led_index_by_key = {key: idx for idx, key in enumerate(self._led_keys)}
        self._vialrgb_life_game = LedLifeGameState(cells_from_led_positions(self._led_keys, led_positions))
        self._life_game_oled_debug = os.environ.get("LEDD_LIFE_GAME_OLED_DEBUG", "1").lower() not in {"0", "false", "no", "off"}
        self._i2cd_socket_path = os.environ.get("LEDD_I2CD_SOCKET", DEFAULT_I2CD_SOCKET_PATH)
        self._led_coords = [
            (float(led_positions[key]["x"]), float(led_positions[key]["y"]))
            for key in self._led_keys[:led_count]
            if key in led_positions
        ]
        self._bt_indicator_stop: threading.Event | None = None
        self._bt_indicator_thread: threading.Thread | None = None
        self._bt_indicator_resume_id: int | None = None
        self._bt_indicator_resume_vialrgb: tuple[int, int, int, int, int] | None = None
        self._bt_top_indices = self._indicator_indices("top")
        self._bt_digit_indices = self._indicator_indices("digits")

    @property
    def current_id(self) -> int:
        """現在実行中のアニメーション ID"""
        return self._current_id

    @property
    def direct_frame_fallback(self) -> str:
        return self._direct_frame_fallback

    def direct_frame_runtime_status(self) -> dict[str, Any]:
        with self._direct_frame_lock:
            return {
                "direct_frame_active": self._direct_frame_active,
                "applied_frames": self._direct_frame_applied_frames,
                "ignored_frames": self._direct_frame_ignored_frames,
                "last_applied_frame_id": self._direct_frame_last_id,
                "overlay": "multisplash" if self._direct_frame_overlay_active() else "none",
            }

    def reload_semantic_roles(self, config_path: Path = _CONFIG_PATH) -> bool:
        """Reload semantic LED roles and keymap-derived layer roles atomically."""
        try:
            config = load_config(config_path)
            keycode_layers = _keycode_layers_from_runtime_config(config)
            semantic_roles = _semantic_role_config_from_runtime(config, keycode_layers)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("semantic LED config reload failed; keeping current config: %s", exc)
            return False

        with self._semantic_config_lock:
            self._config = config
            self._keycode_layers_by_position = keycode_layers
            self._keycode_by_position = keycode_layers[0] if keycode_layers else {}
            self._semantic_roles = semantic_roles
            self._active_semantic_states.intersection_update(self._semantic_roles.state_overlays)
            self._show_with_state_overlays()
        logger.info("semantic LED config reloaded: states=%s", sorted(self._semantic_roles.state_overlays))
        return True

    def apply_semantic_keymap(self, keycode_layers: Any) -> bool:
        """Apply keycode layers pushed by logicd-companion without reading keymap.json."""
        keycode_layers = _keycode_layers_from_runtime_config(
            {"keycode_layers_by_position": keycode_layers},
            allow_keymap_fallback=False,
        )
        semantic_roles = _semantic_role_config_from_runtime(self._config, keycode_layers)
        with self._semantic_config_lock:
            self._keycode_layers_by_position = keycode_layers
            self._keycode_by_position = keycode_layers[0] if keycode_layers else {}
            self._semantic_roles = semantic_roles
            self._active_semantic_states.intersection_update(self._semantic_roles.state_overlays)
            self._show_with_state_overlays()
        logger.info(
            "semantic LED keymap synced from logicd: layers=%d states=%s",
            len(keycode_layers),
            sorted(self._semantic_roles.state_overlays),
        )
        return True

    def apply_semantic_roles(self, semantic_roles_raw: Any) -> bool:
        """Apply semantic role definitions pushed by logicd-companion."""
        if not isinstance(semantic_roles_raw, Mapping):
            raise ValueError(f"semantic_roles must be an object: {type(semantic_roles_raw).__name__}")
        config = dict(self._config)
        config.pop("led_semantic_roles", None)
        config["semantic_roles"] = dict(semantic_roles_raw)
        semantic_roles = _semantic_role_config_from_runtime(config, self._keycode_layers_by_position)
        with self._semantic_config_lock:
            self._config = config
            self._semantic_roles = semantic_roles
            self._active_semantic_states.intersection_update(self._semantic_roles.state_overlays)
            self._show_with_state_overlays()
        logger.info("semantic LED roles synced from logicd: states=%s", sorted(self._semantic_roles.state_overlays))
        return True

    def request_semantic_roles_reload(self, delay_sec: float = 0.2) -> None:
        """Debounce semantic config reload requests from low-rate control paths."""
        delay = max(0.0, float(delay_sec))

        def run_reload() -> None:
            with self._semantic_reload_lock:
                self._semantic_reload_timer = None
            self.reload_semantic_roles()

        with self._semantic_reload_lock:
            if self._semantic_reload_timer is not None:
                self._semantic_reload_timer.cancel()
            timer = threading.Timer(delay, run_reload)
            timer.daemon = True
            self._semantic_reload_timer = timer
            timer.start()

    def switch(self, anim_id: int) -> bool:
        """指定した ID のアニメーションに切り替える。"""
        if anim_id not in REGISTRY:
            logger.warning("不明なアニメーション ID: %d (登録済み: %s)", anim_id, list(REGISTRY.keys()))
            return False

        if anim_id == self._current_id:
            logger.debug("アニメーション %d は既に実行中", anim_id)
            return True

        self._direct_frame_active = False
        self._direct_frame_last_id = None
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        self._stop_event = threading.Event()
        cls = REGISTRY[anim_id]
        anim = cls()
        anim.setup(self._config, self._led_positions)
        self._current_anim = anim
        self._current_id = anim_id

        self._thread = threading.Thread(
            target=anim.run,
            args=(self._strip, self._led_count, self._stop_event),
            daemon=True,
            name=f"anim-{anim_id}",
        )
        self._thread.start()
        logger.info("アニメーション切り替え: ID=%d (%s)", anim_id, cls.ANIMATION_NAME)
        return True

    def keycode_for_position(self, key: str) -> str:
        with self._semantic_config_lock:
            for layer in self._active_layers:
                if not 0 <= layer < len(self._keycode_layers_by_position):
                    continue
                action = self._keycode_layers_by_position[layer].get(key, "KC_TRNS")
                if action == "KC_TRNS":
                    continue
                return action
            return self._keycode_by_position.get(key, key)

    def semantic_role_for_position(self, key: str) -> str:
        return self._semantic_roles.role_for_keycode(self.keycode_for_position(key))

    def _mark_vialrgb_overlay_dirty(self) -> None:
        with self._vialrgb_lock:
            self._vialrgb_overlay_dirty = True

    def set_state_overlay(self, name: str, active: bool) -> None:
        """Enable or disable one semantic state overlay.

        ``name`` is generic (`caps_lock`, `layer_1`, `ctrl_lock`, ...) so logicd
        can feed host and layer state without coupling messages to renderers.
        """
        with self._semantic_config_lock:
            if name not in self._semantic_roles.state_overlays:
                logger.debug("unknown semantic LED state overlay ignored: %s", name)
                return
            before = set(self._active_semantic_states)
            if active:
                self._active_semantic_states.add(name)
            else:
                self._active_semantic_states.discard(name)
            if before != self._active_semantic_states:
                logger.debug("semantic LED overlay %s=%s", name, "on" if active else "off")
                self._mark_vialrgb_overlay_dirty()
                self._vialrgb_wake.set()
                self._show_with_state_overlays()

    def set_active_layer(self, layer: int) -> None:
        layer = max(0, int(layer))
        if layer == self._active_layer:
            return
        old_names = {f"layer_{self._active_layer}", f"layer:{self._active_layer}"}
        new_names = {f"layer_{layer}", f"layer:{layer}"}
        self._active_layer = layer
        self._active_layers = [layer, 0] if layer > 0 else [0]
        self._active_semantic_states.difference_update(old_names)
        if layer > 0:
            self._active_semantic_states.update(
                name for name in new_names if name in self._semantic_roles.state_overlays
            )
        self._mark_vialrgb_overlay_dirty()
        self._vialrgb_wake.set()
        self._show_with_state_overlays()

    def _toggle_lock_overlay_for_keycode(self, keycode: str) -> None:
        if not self._semantic_roles.fallback_internal_lock_toggle:
            return
        state_name = lock_state_for_keycode(keycode)
        if state_name and state_name in self._semantic_roles.state_overlays:
            self.set_state_overlay(state_name, state_name not in self._active_semantic_states)

    def _active_overlay_color_for_position(self, key: str) -> list[int] | None:
        keycode = self.keycode_for_position(key)
        idx = self._led_index_by_key.get(key)
        if idx is None or idx >= self._led_count:
            return None
        base = _color_to_rgb(self._semantic_base_pixels[idx])
        return self._semantic_roles.blended_color_for_position(key, keycode, self._active_semantic_states, base)

    def _set_base_pixel(self, idx: int, color: int) -> None:
        if 0 <= idx < self._led_count:
            self._semantic_base_pixels[idx] = int(color)
            self._raw_strip.setPixelColor(idx, color)

    def _restore_base_pixels_to_strip(self) -> None:
        for idx, color in enumerate(self._semantic_base_pixels[: self._led_count]):
            self._raw_strip.setPixelColor(idx, color)

    def _clear_base_and_strip(self) -> None:
        off = Color(0, 0, 0)
        for idx in range(self._led_count):
            self._semantic_base_pixels[idx] = off
            self._raw_strip.setPixelColor(idx, off)
        self._show_raw_strip(force=True)

    def _apply_state_overlays_to_strip(self) -> None:
        if not self._active_semantic_states:
            return
        for key, idx in self._led_index_by_key.items():
            if idx >= self._led_count:
                continue
            color = self._active_overlay_color_for_position(key)
            if color is None:
                continue
            self._raw_strip.setPixelColor(idx, Color(int(color[0]), int(color[1]), int(color[2])))

    def _apply_morse_feedback_overlays_to_strip(self) -> None:
        if not self._morse_flash_overlays:
            return
        now = time.monotonic()
        expired: list[int] = []
        for idx, (color, expires_at) in self._morse_flash_overlays.items():
            if expires_at <= now:
                expired.append(idx)
                continue
            if 0 <= idx < self._led_count:
                self._raw_strip.setPixelColor(idx, color)
        for idx in expired:
            self._morse_flash_overlays.pop(idx, None)

    def _show_with_state_overlays(self) -> None:
        with self._semantic_config_lock:
            self._restore_base_pixels_to_strip()
            self._apply_state_overlays_to_strip()
            self._apply_morse_feedback_overlays_to_strip()
            self._show_raw_strip()

    def _show_raw_strip(self, *, force: bool = False) -> None:
        now = time.monotonic()
        delay = self._show_min_interval_sec - (now - self._last_show_at)
        if force or self._show_min_interval_sec <= 0.0 or delay <= 0.0:
            with self._show_lock:
                self._raw_strip.show()
                self._last_show_at = time.monotonic()
            return
        self._schedule_deferred_show(delay)

    def _schedule_deferred_show(self, delay: float) -> None:
        with self._deferred_show_lock:
            if self._deferred_show_timer is not None:
                return
            timer = threading.Timer(max(0.001, delay), self._run_deferred_show)
            timer.daemon = True
            self._deferred_show_timer = timer
            timer.start()

    def _run_deferred_show(self) -> None:
        with self._deferred_show_lock:
            self._deferred_show_timer = None
        with self._semantic_config_lock:
            with self._show_lock:
                self._raw_strip.show()
                self._last_show_at = time.monotonic()

    def _direct_frame_overlay_active(self) -> bool:
        return self._vialrgb_mode in VIALRGB_DIRECT_SPLASH_MODES

    def _direct_frame_with_splashes(self, base_rgb: list[tuple[int, int, int]], now: float) -> list[list[float]]:
        rgb = [[float(r), float(g), float(b)] for r, g, b in base_rgb[: self._led_count]]
        if len(rgb) < self._led_count:
            rgb.extend([[0.0, 0.0, 0.0] for _ in range(self._led_count - len(rgb))])
        if not self._led_coords:
            return rgb

        _h, s, v = self._vialrgb_hsv
        speed = 120.0 + self._vialrgb_speed * 1.8
        width = 25.0
        led_coords = self._led_coords[: self._led_count]
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
        return rgb

    def _render_direct_frame_overlay_locked(self) -> None:
        rgb = self._direct_frame_with_splashes(self._direct_frame_base_rgb, time.monotonic())
        for idx, (r, g, b) in enumerate(rgb):
            self._strip.setPixelColor(idx, Color(int(r), int(g), int(b)))
        self._strip.show()

    def _render_direct_frame_overlay(self) -> None:
        with self._direct_frame_lock:
            if not self._direct_frame_active:
                return
            self._render_direct_frame_overlay_locked()

    def on_morse_feedback(self, event: Mapping[str, Any]) -> None:
        if self._direct_frame_active:
            return
        phase = str(event.get("phase", "")).lower()
        color = _MORSE_LED_COLORS.get(phase)
        if color is None:
            return
        try:
            row = int(event["row"])
            col = int(event["col"])
        except (KeyError, TypeError, ValueError):
            return
        idx = self._led_index_by_key.get(f"{row},{col}")
        if idx is None or idx >= self._led_count:
            return
        try:
            duration = float(event.get("duration", _MORSE_LED_DURATIONS.get(phase, 0.22)))
        except (TypeError, ValueError):
            duration = _MORSE_LED_DURATIONS.get(phase, 0.22)
        duration = max(0.03, min(duration, 1.0))
        expires_at = time.monotonic() + duration
        with self._semantic_config_lock:
            self._morse_flash_overlays[idx] = (color, expires_at)
            self._show_with_state_overlays()
        logger.info("MORSE feedback LED flash: phase=%s key=%s idx=%d", phase, f"{row},{col}", idx)

        timer = threading.Timer(duration, self._expire_morse_feedback_overlay, args=(idx, expires_at))
        timer.daemon = True
        timer.start()

    def _expire_morse_feedback_overlay(self, idx: int, expires_at: float) -> None:
        with self._semantic_config_lock:
            current = self._morse_flash_overlays.get(idx)
            if current is None or current[1] != expires_at:
                return
            self._morse_flash_overlays.pop(idx, None)
            self._show_with_state_overlays()

    def apply_direct_frame(self, frame: DirectFramePacket) -> None:
        """Apply one validated direct-frame packet to the LED strip."""
        if frame.led_count != self._led_count:
            logger.warning("direct-frame ignored: led_count mismatch frame=%d expected=%d", frame.led_count, self._led_count)
            with self._direct_frame_lock:
                self._direct_frame_ignored_frames += 1
            return
        with self._direct_frame_lock:
            if self._direct_frame_last_id is not None and frame.frame_id <= self._direct_frame_last_id:
                logger.debug("direct-frame stale frame ignored: frame_id=%d last=%d", frame.frame_id, self._direct_frame_last_id)
                self._direct_frame_ignored_frames += 1
                return
            if not self._direct_frame_active:
                if not self._direct_frame_overlay_active():
                    self._vialrgb_mode = 1
                self._stop_current_animation()
                self._direct_frame_active = True
                logger.info(
                    "direct-frame mode entered%s",
                    " with multisplash overlay" if self._direct_frame_overlay_active() else "",
                )

            payload = frame.payload_rgb()
            base_rgb = []
            for idx in range(self._led_count):
                base = idx * 3
                r, g, b = payload[base], payload[base + 1], payload[base + 2]
                base_rgb.append((r, g, b))
            self._direct_frame_base_rgb = base_rgb
            if self._direct_frame_overlay_active():
                self._render_direct_frame_overlay_locked()
            else:
                for idx, (r, g, b) in enumerate(base_rgb):
                    self._strip.setPixelColor(idx, Color(r, g, b))
                self._strip.show()
            self._direct_frame_last_id = frame.frame_id
            self._direct_frame_applied_frames += 1

    def on_direct_frame_producer_connected(self) -> None:
        """Start a new producer sequence without blanking the previous frame."""
        with self._direct_frame_lock:
            self._direct_frame_last_id = None

    def on_direct_frame_producer_disconnected(self) -> None:
        """Apply configured fallback after a direct-frame producer disconnects."""
        with self._direct_frame_lock:
            if not self._direct_frame_active:
                return
            policy = self._direct_frame_fallback
            logger.info("direct-frame producer disconnected; fallback=%s", policy)
            if policy == "keep_last_frame":
                return
            self._direct_frame_active = False
            self._direct_frame_last_id = None
            if policy == "off":
                self._clear_base_and_strip()
                return
            if policy == "restore_default":
                # Avoid switching while holding the direct-frame lock because
                # switch() joins animation threads.  Release first via a helper.
                pass
        if policy == "restore_default":
            if not self.switch(self._default_anim_id):
                self.switch(0)
            self._show_with_state_overlays()

    def on_key_event(self, row: int, col: int, is_press: bool) -> None:
        """キーイベントを現在のアニメーションに転送する。"""
        key = f"{row},{col}"
        keycode = self.keycode_for_position(key)
        if is_press:
            self._toggle_lock_overlay_for_keycode(keycode)
        self._on_vialrgb_key_event(row, col, is_press)
        if self._current_anim is None:
            return
        pos = self._led_positions.get(key)
        led_pos: tuple[float, float] | None = (pos["x"], pos["y"]) if pos else None
        self._current_anim.on_key_event(row, col, is_press, led_pos)

    def on_layer_state(self, active_layers: list[int]) -> None:
        """Track active layers as semantic overlay state names."""
        active = sorted({max(0, int(layer)) for layer in active_layers})
        before = set(self._active_semantic_states)
        previous_layers = list(self._active_layers)
        self._active_semantic_states = {
            state
            for state in self._active_semantic_states
            if not (state.startswith("layer_") or state.startswith("layer:"))
        }
        for layer in active:
            if layer <= 0:
                continue
            for name in (f"layer_{layer}", f"layer:{layer}"):
                if name in self._semantic_roles.state_overlays:
                    self._active_semantic_states.add(name)
        self._active_layers = sorted(set(active + [0]), reverse=True)
        self._active_layer = self._active_layers[0] if self._active_layers else 0
        if before != self._active_semantic_states or previous_layers != self._active_layers:
            self._mark_vialrgb_overlay_dirty()
            self._vialrgb_wake.set()
            self._show_with_state_overlays()

    def set_semantic_overlay_state(self, state: str, enabled: bool) -> None:
        """Set one named semantic overlay state from logicd notifications."""
        self.set_state_overlay(state, enabled)

    def _keycode_for_led_index(self, idx: int) -> str:
        if 0 <= idx < len(self._led_keys):
            return self.keycode_for_position(self._led_keys[idx])
        return ""

    def _semantic_overlay_color_for_index(self, idx: int) -> int | None:
        if not 0 <= idx < len(self._led_keys):
            return None
        key = self._led_keys[idx]
        keycode = self.keycode_for_position(key)
        if not keycode:
            return None
        color = self._semantic_roles.restore_color_for_position(key, keycode, self._active_semantic_states)
        if color is None:
            return None
        return Color(int(color[0]), int(color[1]), int(color[2]))

    def _semantic_base_color_for_index(self, idx: int, fallback: int) -> int:
        color = self._semantic_overlay_color_for_index(idx)
        return fallback if color is None else color

    def _semantic_base_rgb_for_index(self, idx: int, fallback: tuple[float, float, float]) -> list[float]:
        color = self._semantic_overlay_color_for_index(idx)
        if color is None:
            return [fallback[0], fallback[1], fallback[2]]
        return [float((color >> 16) & 0xFF), float((color >> 8) & 0xFF), float(color & 0xFF)]

    def _on_vialrgb_key_event(self, row: int, col: int, is_press: bool) -> None:
        if not is_press:
            return
        key = f"{row},{col}"
        keycode = self.keycode_for_position(key)
        role = self._semantic_roles.role_for_keycode(keycode)
        key_banner_event = self._vialrgb_mode in VIALRGB_RENDER_GROUPS["key_banner"]
        if not self._semantic_roles.reactive_enabled_for_keycode(keycode) and not key_banner_event:
            logger.debug(
                "reactive LED trigger skipped for role=%s keycode=%s key=%s",
                role,
                keycode,
                key,
            )
            return
        now = time.monotonic()
        render_direct_overlay = False
        banner_keycode: str | None = None
        with self._vialrgb_lock:
            if self._vialrgb_mode in VIALRGB_REACTIVE_MODES:
                idx = self._led_index_by_key.get(key)
                if idx is not None:
                    pos = self._led_positions.get(key) or {}
                    self._vialrgb_reactive_hits.append({
                        "idx": idx,
                        "start": now,
                        "x": float(pos.get("x", idx)),
                        "y": float(pos.get("y", 0.0)),
                        "h": (self._vialrgb_hsv[0] + len(self._vialrgb_reactive_hits) * 29) % 256,
                    })
                    self._vialrgb_wake.set()
            elif self._vialrgb_mode in VIALRGB_SPLASH_MODES or self._vialrgb_mode in VIALRGB_DIRECT_SPLASH_MODES:
                pos = self._led_positions.get(key)
                if pos is not None:
                    hue = self._vialrgb_hsv[0]
                    if self._vialrgb_mode in VIALRGB_MULTI_SPLASH_MODES or self._vialrgb_mode in VIALRGB_DIRECT_MULTI_SPLASH_MODES:
                        hue = (hue + len(self._vialrgb_splashes) * 37) % 256
                    self._vialrgb_splashes.append({
                        "x": float(pos["x"]),
                        "y": float(pos["y"]),
                        "start": now,
                        "h": hue,
                    })
                    render_direct_overlay = self._vialrgb_mode in VIALRGB_DIRECT_SPLASH_MODES
                    self._vialrgb_wake.set()
            elif self._vialrgb_mode in VIALRGB_RENDER_GROUPS["life_game"]:
                idx = self._led_index_by_key.get(key)
                if idx is not None:
                    self._vialrgb_life_game.queue_seed_index(idx, radius=0)
                    self._vialrgb_wake.set()
            elif self._vialrgb_mode in VIALRGB_RENDER_GROUPS["key_banner"]:
                if role == "modifier" or not self._vialrgb_key_banner_has_text(keycode):
                    pos = self._led_positions.get(key)
                    if pos is not None:
                        self._vialrgb_splashes.append({
                            "x": float(pos["x"]),
                            "y": float(pos["y"]),
                            "start": now,
                            "h": (self._vialrgb_hsv[0] + len(self._vialrgb_splashes) * 37) % 256,
                        })
                        self._vialrgb_wake.set()
                else:
                    banner_keycode = keycode
        if banner_keycode is not None:
            self._vialrgb_queue_key_banner(banner_keycode)
        if render_direct_overlay:
            self._render_direct_frame_overlay()

    def _push_life_game_oled_debug(self, tick: int, alive: int, fps: float) -> None:
        if not self._life_game_oled_debug:
            return
        if not hasattr(socket, "AF_UNIX"):
            logger.debug("Life Game OLED debug update skipped; Unix sockets unavailable")
            return
        duration = max(0.8, min(3.0, (1.0 / max(0.1, fps)) + 0.25))
        payload = {
            "t": "alert",
            "msg": f"Life #{tick}\nalive {alive}",
            "sec": duration,
            "immediate": True,
        }
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.05)
                sock.connect(self._i2cd_socket_path)
                sock.sendall((json.dumps(payload, separators=(",", ":")) + "\n").encode())
        except OSError:
            logger.debug("Life Game OLED debug update skipped; i2cd socket unavailable")

    def stop(self) -> None:
        """現在のアニメーションを停止し、全 LED を消灯する"""
        self._stop_bt_indicator()
        self._stop_event.set()
        self._vialrgb_wake.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._clear_base_and_strip()
        self._current_anim = None
        self._current_id = -1
        self._direct_frame_active = False
        self._direct_frame_last_id = None

    def apply_bt_pairing_indicator(self, phase: str, digits: str = "") -> None:
        """Show a temporary Bluetooth pairing indicator.

        `pairing` scans the top row, `passkey` lights the number row, and
        terminal phases briefly flash before returning to the previous effect.
        """
        normalized = (phase or "off").strip().lower()
        if normalized in {"off", "idle", "connected"}:
            self._stop_bt_indicator()
            self._resume_after_bt_indicator()
            return
        if normalized in {"failed", "error"}:
            self._run_bt_flash(Color(255, 0, 0), duration=0.7)
            self._resume_after_bt_indicator()
            return
        if normalized in {"success", "paired"}:
            self._run_bt_flash(Color(0, 180, 40), duration=0.7)
            self._resume_after_bt_indicator()
            return

        indices = self._bt_digit_indices if normalized in {"passkey", "passkey_wait", "digits"} else self._bt_top_indices
        if not indices:
            logger.warning("BT pairing indicator has no LED indices for phase=%s", normalized)
            return
        self._start_bt_indicator(normalized, indices, digits)

    def _indicator_indices(self, group: str) -> list[int]:
        configured = (self._config.get("bt_indicator") or {}).get(group)
        keys: list[str]
        if isinstance(configured, list) and configured:
            keys = [str(key) for key in configured]
        else:
            keys = self._default_indicator_keys(group)
        out: list[int] = []
        for key in keys:
            idx = self._led_index_by_key.get(key)
            if idx is not None and idx < self._led_count:
                out.append(idx)
        return out

    def _default_indicator_keys(self, group: str) -> list[str]:
        if group == "digits":
            return [key for key in self._led_keys if key.startswith("0,") and key != "0,0"]
        if not self._led_positions:
            return []
        min_y = min(float(pos.get("y", 0.0)) for pos in self._led_positions.values())
        top: list[tuple[float, str]] = []
        for key, pos in self._led_positions.items():
            y = float(pos.get("y", 0.0))
            if y <= min_y + 25.0:
                top.append((float(pos.get("x", 0.0)), key))
        return [key for _x, key in sorted(top)]

    def _start_bt_indicator(self, phase: str, indices: list[int], digits: str) -> None:
        if self._bt_indicator_thread is None:
            if self._current_id >= 0:
                self._bt_indicator_resume_id = self._current_id
                self._bt_indicator_resume_vialrgb = None
            else:
                h, s, v = self._vialrgb_hsv
                self._bt_indicator_resume_vialrgb = (self._vialrgb_mode, self._vialrgb_speed, h, s, v)
                self._bt_indicator_resume_id = None
        self._stop_bt_indicator()
        self._stop_current_animation()
        stop_event = threading.Event()
        self._bt_indicator_stop = stop_event
        target = self._run_bt_digit_wait if phase in {"passkey", "passkey_wait", "digits"} else self._run_bt_top_scan
        self._bt_indicator_thread = threading.Thread(
            target=target,
            args=(indices, digits, stop_event),
            daemon=True,
            name=f"bt-indicator-{phase}",
        )
        self._bt_indicator_thread.start()

    def _stop_bt_indicator(self) -> None:
        stop_event = self._bt_indicator_stop
        thread = self._bt_indicator_thread
        self._bt_indicator_stop = None
        self._bt_indicator_thread = None
        if stop_event is not None:
            stop_event.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

    def _resume_after_bt_indicator(self) -> None:
        resume_id = self._bt_indicator_resume_id
        resume_vialrgb = self._bt_indicator_resume_vialrgb
        self._bt_indicator_resume_id = None
        self._bt_indicator_resume_vialrgb = None
        if resume_id is not None and resume_id in REGISTRY:
            self.switch(resume_id)
        elif resume_vialrgb is not None:
            self.apply_vialrgb(*resume_vialrgb)

    def _run_bt_top_scan(self, indices: list[int], _digits: str, stop_event: threading.Event) -> None:
        pos = 0
        direction = 1
        while not stop_event.is_set():
            for idx in range(self._led_count):
                self._strip.setPixelColor(idx, Color(0, 0, 0))
            for tail in range(4):
                scan_pos = pos - direction * tail
                if 0 <= scan_pos < len(indices):
                    factor = max(0.2, (4 - tail) / 4.0)
                    self._strip.setPixelColor(indices[scan_pos], Color(0, int(80 * factor), int(255 * factor)))
            self._strip.show()
            stop_event.wait(0.08)
            pos += direction
            if pos >= len(indices):
                pos = max(0, len(indices) - 2)
                direction = -1
            elif pos < 0:
                pos = 1 if len(indices) > 1 else 0
                direction = 1

    def _run_bt_digit_wait(self, indices: list[int], digits: str, stop_event: threading.Event) -> None:
        brightness = 0
        direction = 12
        entered = min(len(digits), len(indices))
        while not stop_event.is_set():
            brightness += direction
            if brightness >= 180:
                brightness = 180
                direction = -12
            elif brightness <= 40:
                brightness = 40
                direction = 12
            for idx in range(self._led_count):
                self._strip.setPixelColor(idx, Color(0, 0, 0))
            for offset, idx in enumerate(indices):
                blue = 255 if offset < entered else brightness
                green = 70 if offset < entered else max(20, brightness // 3)
                self._strip.setPixelColor(idx, Color(0, green, blue))
            self._strip.show()
            stop_event.wait(0.08)

    def _run_bt_flash(self, color: int, *, duration: float) -> None:
        self._stop_bt_indicator()
        self._stop_current_animation()
        deadline = time.monotonic() + duration
        on = True
        while time.monotonic() < deadline:
            for idx in range(self._led_count):
                self._strip.setPixelColor(idx, color if on else Color(0, 0, 0))
            self._strip.show()
            on = not on
            time.sleep(0.12)

    def _stop_current_animation(self) -> None:
        self._stop_event.set()
        self._vialrgb_wake.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._current_anim = None
        self._current_id = -1


def main() -> None:
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        print(_HELP.rstrip())
        return

    logger.info("ledd 起動")

    try:
        config = load_config(_CONFIG_PATH)
    except FileNotFoundError:
        logger.error("設定ファイルが見つかりません: %s", _CONFIG_PATH)
        raise
    logger.info("設定ファイル読み込み完了: %s", _CONFIG_PATH)

    led_order = get_led_chain_order(config)
    logger.info("LEDチェーン順: %s ... %s (計%d個)", led_order[:3], led_order[-3:], len(led_order))

    strip = init_strip(config)
    led_cfg = config["led"]
    logger.info(
        "LEDストリップ初期化完了 (GPIO BCM: %d, LED数: %d, 輝度: %d, カラーオーダー: %s)",
        led_cfg["gpio_bcm"],
        len(config["leds"]),
        led_cfg.get("brightness", 128),
        led_cfg.get("color_order", "GRB"),
    )

    led_positions: dict[str, dict] = config.get("leds", {})
    led_count = len(led_positions)

    manager = AnimationManager(strip, led_count, config, led_positions)
    if not apply_startup_effect(manager, config):
        default_anim_id: int = int(config.get("animation", {}).get("default_id", 0))
        if not manager.switch(default_anim_id):
            logger.warning("デフォルトアニメーション ID=%d が見つかりません。ID=0 を使用します", default_anim_id)
            manager.switch(0)

    ipc_cfg = config.get("ipc", {})
    logicd_sock = ipc_cfg.get("socket_path", "/tmp/ledd_events.sock")
    direct_frame_sock = ipc_cfg.get("direct_frame_socket_path", os.environ.get("LEDD_DIRECT_FRAME_SOCK", DEFAULT_DIRECT_FRAME_SOCKET))
    direct_frame_status_path = os.environ.get("LEDD_DIRECT_FRAME_STATUS", DEFAULT_DIRECT_FRAME_STATUS_PATH)

    stop_event = threading.Event()

    def handle_shutdown(signum: int, frame: Any) -> None:
        logger.info("シグナル %d を受信。シャットダウンします", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    receiver_thread = threading.Thread(
        target=logicd_receiver,
        args=(logicd_sock, manager, stop_event),
        daemon=True,
        name="logicd-receiver",
    )
    receiver_thread.start()

    direct_frame_stats = DirectFrameReceiverStats()
    direct_frame_thread = threading.Thread(
        target=direct_frame_receiver,
        args=(direct_frame_sock, led_count, stop_event),
        kwargs={
            "stats": direct_frame_stats,
            "on_frame": manager.apply_direct_frame,
            "on_producer_connected": manager.on_direct_frame_producer_connected,
            "on_producer_disconnected": manager.on_direct_frame_producer_disconnected,
        },
        daemon=True,
        name="direct-frame-receiver",
    )
    direct_frame_thread.start()

    write_direct_frame_status(
        direct_frame_status_path,
        direct_frame_stats,
        led_count=led_count,
        socket_path=direct_frame_sock,
        fallback=manager.direct_frame_fallback,
        runtime=manager.direct_frame_runtime_status(),
    )
    direct_frame_status_thread = threading.Thread(
        target=direct_frame_status_writer,
        args=(direct_frame_status_path, direct_frame_stats, stop_event),
        kwargs={
            "led_count": led_count,
            "socket_path": direct_frame_sock,
            "fallback": manager.direct_frame_fallback,
            "runtime_getter": manager.direct_frame_runtime_status,
        },
        daemon=True,
        name="direct-frame-status",
    )
    direct_frame_status_thread.start()

    logger.info(
        "起動完了。アニメーション ID=%d、logicd ソケット: %s、direct-frame ソケット: %s、fallback: %s",
        manager.current_id,
        logicd_sock,
        direct_frame_sock,
        manager.direct_frame_fallback,
    )

    try:
        stop_event.wait()
    finally:
        logger.info(
            "direct-frame stats accepted=%d rejected=%d bytes=%d last_frame_id=%s last_error=%s connects=%d disconnects=%d",
            direct_frame_stats.accepted_frames,
            direct_frame_stats.rejected_frames,
            direct_frame_stats.bytes_received,
            direct_frame_stats.last_frame_id,
            direct_frame_stats.last_error,
            direct_frame_stats.producer_connects,
            direct_frame_stats.producer_disconnects,
        )
        logger.info("全 LED を消灯してシャットダウン")
        manager.stop()


if __name__ == "__main__":
    main()
