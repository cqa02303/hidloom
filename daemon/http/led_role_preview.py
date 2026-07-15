"""Build temporary LED role-preview frames for HTTP Lighting UI.

This module is intentionally side-effect free.  It reads the static keymap and
LED order and builds the HSV pixel list consumed by the HTTP preview handler
through logicd's existing `vialrgb_direct` ctrl operation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DAEMON_ROOT = _REPO_ROOT / "daemon"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_DAEMON_ROOT) not in sys.path:
    sys.path.insert(0, str(_DAEMON_ROOT))

from hidloom_paths import default_config_dir, default_config_file
from ledd.semantic_roles import infer_role_from_keycode, normalize_led_semantic_role_config

CONF_DIR = default_config_dir(_REPO_ROOT)
KEYMAP_JSON = default_config_file("keymap.json", _REPO_ROOT)
LEDD_JSON = default_config_file("ledd.json", _REPO_ROOT)

ROLE_PREVIEW_HSV = {
    "normal": [0, 0, 18],
    "modifier": [150, 180, 96],
    "function": [170, 160, 96],
    "layer": [92, 200, 96],
    "lock": [32, 220, 110],
    "script": [224, 180, 96],
    "system": [0, 210, 110],
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _base_layer_keycodes_by_position(keymap: Mapping[str, Any]) -> dict[str, str]:
    layout = keymap.get("_layout_def", {})
    layers = keymap.get("layers", [])
    if not isinstance(layout, Mapping) or not isinstance(layers, list) or not layers:
        return {}
    base = layers[0]
    if not isinstance(base, Mapping):
        return {}
    result: dict[str, str] = {}
    for group, positions in layout.items():
        if str(group).startswith("_") or not isinstance(positions, list):
            continue
        keycodes = base.get(group, [])
        if not isinstance(keycodes, list):
            continue
        for idx, pos in enumerate(positions):
            if idx >= len(keycodes):
                continue
            if not isinstance(pos, list) or len(pos) < 2:
                continue
            keycode = keycodes[idx]
            if not isinstance(keycode, str):
                continue
            try:
                row = int(pos[0])
                col = int(pos[1])
            except (TypeError, ValueError):
                continue
            result[f"{row},{col}"] = keycode
    return result


def _semantic_config_from_ledd(ledd_config: Mapping[str, Any]):
    raw = ledd_config.get("semantic_roles") or ledd_config.get("led_semantic_roles") or {}
    if not isinstance(raw, Mapping):
        raw = {}
    return normalize_led_semantic_role_config(raw)


def role_for_preview_keycode(keycode: str, semantic_config: Any | None = None) -> str:
    role = semantic_config.role_for_keycode(keycode) if semantic_config is not None else infer_role_from_keycode(keycode)
    return role if role in ROLE_PREVIEW_HSV else "normal"


def build_role_preview_frame(*, brightness: int = 96) -> dict[str, Any]:
    """Return a role-preview VialRGB direct frame.

    The returned `pixels` list uses the LED chain order from `config/default/ledd.json`
    and HSV triples expected by logicd's `vialrgb_direct` ctrl operation.
    """
    brightness = max(1, min(255, int(brightness)))
    keymap = _load_json(KEYMAP_JSON)
    ledd_config = _load_json(LEDD_JSON)
    leds = ledd_config.get("leds", {})
    if not isinstance(leds, Mapping):
        raise ValueError("config/default/ledd.json leds must be an object")
    order = [str(key) for key in leds.keys()]
    keycodes = _base_layer_keycodes_by_position(keymap)
    semantic = _semantic_config_from_ledd(ledd_config)
    counts = {role: 0 for role in ROLE_PREVIEW_HSV}
    pixels: list[list[int]] = []
    roles_by_position: dict[str, str] = {}
    for pos in order:
        keycode = keycodes.get(pos, "")
        role = role_for_preview_keycode(keycode, semantic)
        counts[role] = counts.get(role, 0) + 1
        roles_by_position[pos] = role
        h, s, v = ROLE_PREVIEW_HSV[role]
        if role == "normal":
            v = max(8, min(48, brightness // 4))
        else:
            v = brightness
        pixels.append([int(h), int(s), int(v)])
    return {
        "pixels": pixels,
        "count": len(pixels),
        "counts": counts,
        "roles_by_position": roles_by_position,
    }
