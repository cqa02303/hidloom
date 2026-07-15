"""Layout payload assembly for the HTTP API."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

_HERE = Path(__file__).parent
_REPO_ROOT = _HERE.parents[1]
_DAEMON_ROOT = _REPO_ROOT / "daemon"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_DAEMON_ROOT) not in sys.path:
    sys.path.insert(0, str(_DAEMON_ROOT))

from layout_controls import control_metadata_from_keymap
from script_store import load_script_label_overrides
from vil_layout import load_keymap_layers
from hidloom_paths import default_config_dir, default_config_file, runtime_file

_CONF_DIR = default_config_dir(_REPO_ROOT)

LAYOUT_JSON = Path(os.environ.get("HTTPD_LAYOUT_JSON", str(runtime_file("keyboard-layout.json"))))
if not LAYOUT_JSON.exists():
    LAYOUT_JSON = default_config_file("keyboard-layout.json", _REPO_ROOT)
VIAL_JSON = Path(os.environ.get("HTTPD_VIAL_JSON", str(runtime_file("vial.json"))))
if not VIAL_JSON.exists():
    VIAL_JSON = default_config_file("vial.json", _REPO_ROOT)
KEY_LABELS_JSON = default_config_file("key_labels.json", _REPO_ROOT)
DEFAULT_KEYMAP_JSON = default_config_file("keymap.json", _REPO_ROOT)
KEYMAP_JSON = Path(os.environ.get("HTTPD_KEYMAP_JSON", str(runtime_file("keymap.json"))))
if not KEYMAP_JSON.exists():
    KEYMAP_JSON = DEFAULT_KEYMAP_JSON
KEYCODES_JSON = default_config_file("keycodes.json", _REPO_ROOT)

log = logging.getLogger("httpd")


async def build_layer0_from_keymap_file(path: Path) -> Dict[str, str]:
    layer0: Dict[str, str] = {}
    try:
        km = json.loads(path.read_text(encoding="utf-8"))
        layout_def = km.get("_layout_def", {})
        layers = km.get("layers", [])
        if layers:
            l0 = layers[0]
            for grp, positions in layout_def.items():
                if grp.startswith("_"):
                    continue
                keycodes = l0.get(grp, [])
                for i, pos in enumerate(positions):
                    if i < len(keycodes):
                        layer0[f"{pos[0]},{pos[1]}"] = keycodes[i]
    except OSError as e:
        log.warning("Cannot load keymap.json: %s", e)
    return layer0


async def build_layer0_from_file() -> Dict[str, str]:
    return await build_layer0_from_keymap_file(KEYMAP_JSON)


async def current_keymap_layers(
    query_logicd_layers: Callable[[], Awaitable[Optional[Dict[str, Any]]]],
) -> list[dict[str, str]]:
    logicd_data = await query_logicd_layers()
    if logicd_data is not None:
        layers = logicd_data.get("layers", [])
        if isinstance(layers, list):
            return [{str(k): str(v) for k, v in layer.items()} for layer in layers if isinstance(layer, dict)]
    return load_keymap_layers(KEYMAP_JSON)


def load_available_keycodes() -> list[str]:
    try:
        raw = json.loads(KEYCODES_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("Cannot load keycodes.json: %s", e)
        return []
    if not isinstance(raw, dict):
        return []
    return sorted(k for k in raw if isinstance(k, str) and not k.startswith("_"))


async def build_layout_payload(
    query_logicd_layers: Callable[[], Awaitable[Optional[Dict[str, Any]]]],
) -> Dict[str, Any]:
    layout: Any = []
    vial: Dict[str, Any] = {}
    labels: Dict[str, str] = {}
    layer0: Dict[str, str] = {}
    all_layers: list = []
    logicd_active: Optional[Dict[str, Any]] = None
    default_layer0: Dict[str, str] = {}
    default_layers: list[dict[str, str]] = []
    controls: Dict[str, Any] = {"joystick_directions": {}, "encoder_directions": {}, "encoder_click_keys": []}
    try:
        layout = json.loads(LAYOUT_JSON.read_text(encoding="utf-8"))
    except OSError as e:
        log.warning("Cannot load keyboard-layout.json: %s", e)
    try:
        vial = json.loads(VIAL_JSON.read_text(encoding="utf-8"))
    except OSError as e:
        log.warning("Cannot load vial.json: %s", e)
    try:
        raw = json.loads(KEY_LABELS_JSON.read_text(encoding="utf-8"))
        labels = {k: v for k, v in raw.items() if not k.startswith("_")}
    except OSError as e:
        log.warning("Cannot load key_labels.json: %s", e)
    labels.update(load_script_label_overrides())
    logicd_data = await query_logicd_layers()
    if logicd_data is not None:
        all_layers = logicd_data.get("layers", [])
        logicd_active = logicd_data.get("active")
        if all_layers:
            layer0 = all_layers[0]
    else:
        log.info("logicd unavailable, falling back to keymap.json")
        layer0 = await build_layer0_from_file()
    try:
        keymap_doc = json.loads(KEYMAP_JSON.read_text(encoding="utf-8"))
        controls = control_metadata_from_keymap(keymap_doc)
    except (OSError, json.JSONDecodeError) as e:
        log.warning("Cannot load keymap control metadata: %s", e)
    default_layer0 = await build_layer0_from_keymap_file(DEFAULT_KEYMAP_JSON)
    default_layers = load_keymap_layers(DEFAULT_KEYMAP_JSON)
    return {
        "layout": layout,
        "keymap": vial.get("layouts", {}).get("keymap", []),
        "matrix": vial.get("matrix", {}),
        "controls": controls,
        "labels": labels,
        "keycodes": load_available_keycodes(),
        "layer0": layer0,
        "default_layer0": default_layer0,
        "default_layers": default_layers,
        "all_layers": all_layers,
        "logicd_active": logicd_active,
    }
