"""Runtime keymap persistence helpers."""
from __future__ import annotations

import json
import os
import tempfile

from . import config_loader
from .keymap import LayerManager


def save_runtime_keymap(layers: list[dict[str, str]], *, preferred: str, fallback: str) -> str:
    template_path = preferred if os.path.exists(preferred) else fallback
    with open(template_path, encoding="utf-8") as fh:
        template = json.load(fh)
    keymap = config_loader.layers_to_keymap_json(layers, template)

    os.makedirs(os.path.dirname(preferred), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".keymap.", suffix=".tmp", dir=os.path.dirname(preferred))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(keymap, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp_path, preferred)
        os.chmod(preferred, 0o644)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    return preferred


def reset_runtime_keymap(layer_manager: LayerManager, *, runtime_path: str, default_path: str) -> dict:
    with open(default_path, encoding="utf-8") as fh:
        template = json.load(fh)
    layers = config_loader.keymap_json_to_layers(template)
    if not layers:
        raise ValueError(f"default keymap has no layers: {default_path}")

    layer_manager.load(layers)
    layer_manager._momentary.clear()
    layer_manager._toggled.clear()

    removed_runtime = False
    try:
        os.unlink(runtime_path)
        removed_runtime = True
    except FileNotFoundError:
        pass

    return {
        "layers": len(layers),
        "default_path": os.path.abspath(default_path),
        "runtime_path": runtime_path,
        "removed_runtime": removed_runtime,
    }
