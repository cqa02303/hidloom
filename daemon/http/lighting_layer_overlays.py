"""HTTP helpers for persistent layer LED overlay settings."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Awaitable, Callable, Mapping, Optional

from aiohttp import web

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hidloom_paths import default_config_file

LEDD_JSON = default_config_file("ledd.json", _REPO_ROOT)
SendCtrlCommand = Callable[[dict[str, Any]], Awaitable[Optional[dict[str, Any]]]]

LAYER_RANGE = range(1, 8)
VALID_EFFECT_BLEND = ("replace", "max", "add", "alpha")
DEFAULT_LAYER_COLORS = (
    [0, 80, 0],
    [0, 48, 120],
    [96, 0, 96],
    [120, 60, 0],
    [0, 96, 96],
    [120, 0, 48],
)


def _load_ledd(path: Path = LEDD_JSON) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_ledd(data: Mapping[str, Any], path: Path = LEDD_JSON) -> None:
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


async def _request_ledd_reload(send_ctrl_command: SendCtrlCommand | None) -> dict[str, Any]:
    if send_ctrl_command is None:
        return {"requested": False, "result": "unavailable"}
    resp = await send_ctrl_command({"t": "LEDD_RELOAD", "target": "semantic_roles"})
    if resp is None:
        return {"requested": True, "result": "error", "msg": "logicd unavailable"}
    return {
        "requested": True,
        "result": "ok" if resp.get("result") == "ok" else "error",
        "response": resp,
    }


def default_layer_color(layer: int) -> list[int]:
    return list(DEFAULT_LAYER_COLORS[(layer - 1) % len(DEFAULT_LAYER_COLORS)])


def _layer_name(layer: int) -> str:
    return f"layer:{layer}"


def _layer_index_from_overlay_name(name: str) -> int | None:
    for prefix in ("layer:", "layer_"):
        if name.startswith(prefix):
            try:
                layer = int(name[len(prefix) :])
            except ValueError:
                return None
            return layer if layer > 0 else None
    return None


def _color(value: Any, *, field: str) -> list[int]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{field} must be [r,g,b]")
    out = []
    for item in value:
        if not isinstance(item, int) or item < 0 or item > 255:
            raise ValueError(f"{field} must be [r,g,b] bytes")
        out.append(int(item))
    return out


def _string_list(value: Any, *, field: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.replace(";", "\n").split() if part.strip()]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of strings")
    return [item.strip() for item in value if item.strip()]


def _overlay_for_layer(overlays: Mapping[str, Any], layer: int) -> tuple[str | None, Mapping[str, Any]]:
    for name, value in overlays.items():
        if isinstance(name, str) and _layer_index_from_overlay_name(name) == layer and isinstance(value, Mapping):
            return name, value
    return None, {}


def build_layer_overlay_payload(ledd: Mapping[str, Any]) -> dict[str, Any]:
    semantic = ledd.get("semantic_roles", {})
    if not isinstance(semantic, Mapping):
        semantic = {}
    overlays = semantic.get("state_overlays", {})
    if not isinstance(overlays, Mapping):
        overlays = {}
    layers = []
    for layer in LAYER_RANGE:
        name, overlay = _overlay_for_layer(overlays, layer)
        color = overlay.get("color", default_layer_color(layer))
        try:
            normalized_color = _color(color, field=f"{_layer_name(layer)}.color")
        except ValueError:
            normalized_color = default_layer_color(layer)
        effect_blend = str(overlay.get("effect_blend", "max")).strip().lower()
        if effect_blend not in VALID_EFFECT_BLEND:
            effect_blend = "max"
        effect_alpha = overlay.get("effect_alpha", 0.65)
        try:
            effect_alpha = float(effect_alpha)
        except (TypeError, ValueError):
            effect_alpha = 0.65
        effect_alpha = max(0.0, min(1.0, effect_alpha))
        layers.append({
            "layer": layer,
            "name": name or _layer_name(layer),
            "enabled": bool(name),
            "color": normalized_color,
            "effect_blend": effect_blend,
            "effect_alpha": effect_alpha,
            "include_layer_changes": bool(overlay.get("include_layer_changes", True)),
            "keys": _string_list(overlay.get("keys", []), field=f"{_layer_name(layer)}.keys"),
            "extra_leds": _string_list(
                overlay.get("extra_leds", overlay.get("leds", [])),
                field=f"{_layer_name(layer)}.extra_leds",
            ),
            "priority": int(overlay.get("priority", 30)) if isinstance(overlay.get("priority", 30), int) else 30,
        })
    return {
        "result": "ok",
        "layers": layers,
        "blend_modes": list(VALID_EFFECT_BLEND),
        "palette": {str(layer): default_layer_color(layer) for layer in LAYER_RANGE},
    }


def normalize_layer_overlay_update(body: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw_layers = body.get("layers")
    if not isinstance(raw_layers, list):
        raise ValueError("layers must be a list")
    current_by_layer = {
        item["layer"]: item
        for item in build_layer_overlay_payload(current)["layers"]
    }
    normalized: dict[str, dict[str, Any]] = {}
    seen: set[int] = set()
    for raw in raw_layers:
        if not isinstance(raw, Mapping):
            raise ValueError("layers[] must be objects")
        layer = raw.get("layer")
        if not isinstance(layer, int) or layer not in LAYER_RANGE:
            raise ValueError("layer must be 1..7")
        if layer in seen:
            raise ValueError(f"duplicate layer: {layer}")
        seen.add(layer)
        if not bool(raw.get("enabled", False)):
            continue
        previous = current_by_layer.get(layer, {})
        blend = str(raw.get("effect_blend", previous.get("effect_blend", "max"))).strip().lower()
        if blend not in VALID_EFFECT_BLEND:
            raise ValueError("effect_blend must be replace, max, add, or alpha")
        overlay = {
            "keys": _string_list(raw.get("keys", previous.get("keys", [])), field=f"layers.{layer}.keys"),
            "include_layer_changes": bool(raw.get("include_layer_changes", previous.get("include_layer_changes", True))),
            "color": _color(raw.get("color", previous.get("color", default_layer_color(layer))), field=f"layers.{layer}.color"),
            "effect_blend": blend,
            "priority": 30,
        }
        if blend == "alpha":
            alpha = raw.get("effect_alpha", previous.get("effect_alpha", 0.65))
            if not isinstance(alpha, (int, float)) or alpha < 0 or alpha > 1:
                raise ValueError("effect_alpha must be 0..1")
            overlay["effect_alpha"] = float(alpha)
        extra_leds = _string_list(
            raw.get("extra_leds", previous.get("extra_leds", [])),
            field=f"layers.{layer}.extra_leds",
        )
        if extra_leds:
            overlay["extra_leds"] = extra_leds
        normalized[_layer_name(layer)] = overlay
    return normalized


def apply_layer_overlay_update(ledd: dict[str, Any], update: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    semantic = ledd.setdefault("semantic_roles", {})
    if not isinstance(semantic, dict):
        raise ValueError("semantic_roles must be an object")
    overlays = semantic.setdefault("state_overlays", {})
    if not isinstance(overlays, dict):
        raise ValueError("semantic_roles.state_overlays must be an object")
    for name in list(overlays):
        if isinstance(name, str) and _layer_index_from_overlay_name(name) in LAYER_RANGE:
            overlays.pop(name, None)
    overlays.update({str(name): dict(value) for name, value in update.items()})
    return ledd


async def lighting_layer_overlays_get_response() -> web.Response:
    try:
        return web.json_response(build_layer_overlay_payload(_load_ledd()))
    except OSError as exc:
        return web.json_response({"result": "error", "msg": str(exc)}, status=500)


async def lighting_layer_overlays_put_response(
    request: web.Request,
    send_ctrl_command: SendCtrlCommand | None = None,
) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"result": "error", "msg": "Invalid JSON"}, status=400)
    if not isinstance(body, Mapping):
        return web.json_response({"result": "error", "msg": "Invalid JSON"}, status=400)
    try:
        ledd = _load_ledd()
        update = normalize_layer_overlay_update(body, ledd)
        ledd = apply_layer_overlay_update(ledd, update)
        _write_ledd(ledd)
        payload = build_layer_overlay_payload(ledd)
    except (OSError, ValueError, TypeError) as exc:
        return web.json_response({"result": "error", "msg": str(exc)}, status=400)
    reload_result = await _request_ledd_reload(send_ctrl_command)
    return web.json_response({**payload, "saved": True, "reload": reload_result})
