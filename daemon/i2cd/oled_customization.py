"""Persistent OLED icon and Ready-screen customization helpers."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Mapping

from hidloom_paths import default_config_file, runtime_file
from .connectivity import OUTPUT_MODE_ICONS
from .status_display import DAEMON_STATUS_ICONS


SCHEMA = "hidloom.oled.customization.v1"
MAX_ICON_WIDTH = 8
ICON_HEIGHT = 8

LAYOUT_FILE = default_config_file("oled-layout.json")


def _load_layout_definition(path: Path = LAYOUT_FILE) -> tuple[tuple[dict[str, str], ...], tuple[dict[str, Any], ...]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != "hidloom.oled.layout.v1":
        raise ValueError(f"invalid OLED layout schema: {path}")
    ready = value.get("ready")
    items = ready.get("items") if isinstance(ready, dict) else None
    if not isinstance(items, list) or not items:
        raise ValueError(f"OLED layout ready.items must be a non-empty array: {path}")
    catalog: list[dict[str, str]] = []
    defaults: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"OLED layout item {index} must be object: {path}")
        item_id = item.get("id")
        label = item.get("label")
        description = item.get("description", "")
        if not isinstance(item_id, str) or not item_id or item_id in seen:
            raise ValueError(f"OLED layout item {index} has invalid id: {path}")
        if not isinstance(label, str) or not label or not isinstance(description, str):
            raise ValueError(f"OLED layout item {item_id} has invalid metadata: {path}")
        if not isinstance(item.get("enabled"), bool) or not isinstance(item.get("separator_after"), bool):
            raise ValueError(f"OLED layout item {item_id} has invalid defaults: {path}")
        seen.add(item_id)
        catalog.append({"id": item_id, "label": label, "description": description})
        defaults.append({
            "id": item_id,
            "enabled": item["enabled"],
            "separator_after": item["separator_after"],
        })
    return tuple(catalog), tuple(defaults)


READY_ITEM_CATALOG, DEFAULT_READY_ITEMS = _load_layout_definition()

_DAEMON_ICON_NAMES = tuple(icon_name for _service, icon_name in DAEMON_STATUS_ICONS)
_OUTPUT_ICON_COMBINATIONS = (
    ("auto", "usb", "wifi3"),
    ("auto", "bt", "wifi3"),
    ("auto", "pi", "wifi3"),
    ("usb", "wifi3"),
    ("bt", "wifi3"),
    ("pi", "wifi3"),
)
_CACHE: dict[str, tuple[tuple[bool, int, int], str, dict[str, Any], str, list[str]]] = {}


def icon_group_catalog(default_icons: Mapping[str, Any]) -> list[dict[str, Any]]:
    known_icons = {str(name) for name in default_icons}
    daemon_items = [
        {"name": icon_name, "label": service}
        for service, icon_name in DAEMON_STATUS_ICONS
        if icon_name in known_icons
    ]
    output_items = [
        {"name": icon_name, "label": label}
        for icon_name, label in OUTPUT_MODE_ICONS
        if icon_name in known_icons
    ]
    assigned = {item["name"] for item in daemon_items + output_items}
    other_items = [
        {"name": name, "label": "Combined logicd" if name == "lgc" else "Other icon"}
        for name in default_icons
        if name not in assigned
    ]
    groups: list[dict[str, Any]] = [
        {
            "id": "daemon_status",
            "label": "Daemon status",
            "description": "Ready画面でのdaemon表示順",
            "items": daemon_items,
        },
        {
            "id": "output_mode",
            "label": "Output mode",
            "description": "Auto、出力先、Wi-Fiの表示順",
            "items": output_items,
        },
    ]
    if other_items:
        groups.append({
            "id": "other",
            "label": "Other",
            "description": "現在のReady status行では未使用",
            "items": other_items,
        })
    return groups


def customization_path() -> Path:
    override = os.environ.get("HIDLOOM_OLED_CUSTOMIZATION_FILE")
    return Path(override) if override else runtime_file("oled_customization.json")


def icon_payload(icons: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    payload: dict[str, dict[str, Any]] = {}
    for name, icon in icons.items():
        if isinstance(icon, Mapping):
            rows = [str(row) for row in icon["rows"]]
            width = int(icon["width"])
            height = int(icon["height"])
        else:
            rows = [str(row) for row in icon.rows]
            width = int(icon.width)
            height = int(icon.height)
        payload[str(name)] = {
            "width": width,
            "height": height,
            "rows": rows,
        }
    return payload


def default_document(default_icons: Mapping[str, Any]) -> dict[str, Any]:
    icons = icon_payload(default_icons)
    return {
        "schema": SCHEMA,
        "icons": icons,
        "ready": {"items": copy.deepcopy(list(DEFAULT_READY_ITEMS))},
    }


def _normalize_icon(name: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"icons.{name} must be object")
    rows = value.get("rows")
    if not isinstance(rows, list) or not all(isinstance(row, str) for row in rows):
        raise ValueError(f"icons.{name}.rows must be string array")
    if len(rows) != ICON_HEIGHT:
        raise ValueError(f"icons.{name} must have exactly {ICON_HEIGHT} rows")
    width = value.get("width", len(rows[0]) if rows else 0)
    height = value.get("height", len(rows))
    if isinstance(width, bool) or not isinstance(width, int) or not 1 <= width <= MAX_ICON_WIDTH:
        raise ValueError(f"icons.{name}.width must be 1..{MAX_ICON_WIDTH}")
    if height != ICON_HEIGHT:
        raise ValueError(f"icons.{name}.height must be {ICON_HEIGHT}")
    for row in rows:
        if len(row) != width:
            raise ValueError(f"icons.{name} row width must be {width}")
        if any(pixel not in {"0", "1"} for pixel in row):
            raise ValueError(f"icons.{name} rows must contain only 0/1")
    return {"width": width, "height": ICON_HEIGHT, "rows": list(rows)}


def _row_width(names: tuple[str, ...], icons: Mapping[str, dict[str, Any]]) -> int:
    return sum(int(icons[name]["width"]) + 3 for name in names) - 1


def _validate_icon_rows_fit(icons: Mapping[str, dict[str, Any]], max_width: int = 58) -> None:
    missing = sorted(set(_DAEMON_ICON_NAMES) - set(icons))
    if missing:
        raise ValueError(f"required OLED icons are missing: {', '.join(missing)}")
    split_at = (len(_DAEMON_ICON_NAMES) + 1) // 2
    daemon_rows = (_DAEMON_ICON_NAMES[:split_at], _DAEMON_ICON_NAMES[split_at:])
    for names in daemon_rows:
        if _row_width(names, icons) > max_width:
            raise ValueError("daemon status icons do not fit OLED width")
    for names in _OUTPUT_ICON_COMBINATIONS:
        if any(name not in icons for name in names):
            raise ValueError(f"required OLED icons are missing: {', '.join(name for name in names if name not in icons)}")
        if _row_width(names, icons) > max_width:
            raise ValueError("output status icons do not fit OLED width")


def _normalize_ready(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("ready must be object")
    items = value.get("items")
    if not isinstance(items, list):
        raise ValueError("ready.items must be array")
    known = {entry["id"] for entry in READY_ITEM_CATALOG}
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"ready.items[{index}] must be object")
        item_id = item.get("id")
        if item_id not in known:
            raise ValueError(f"ready.items[{index}].id is unknown: {item_id}")
        if item_id in seen:
            raise ValueError(f"ready item is duplicated: {item_id}")
        if not isinstance(item.get("enabled"), bool):
            raise ValueError(f"ready.items[{index}].enabled must be boolean")
        if not isinstance(item.get("separator_after", False), bool):
            raise ValueError(f"ready.items[{index}].separator_after must be boolean")
        seen.add(item_id)
        normalized.append({
            "id": item_id,
            "enabled": item["enabled"],
            "separator_after": item.get("separator_after", False),
        })
    missing = sorted(known - seen)
    if missing:
        raise ValueError(f"ready items are missing: {', '.join(missing)}")
    return {"items": normalized}


def normalize_document(value: Any, default_icons: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("OLED customization must be object")
    schema = value.get("schema", SCHEMA)
    if schema != SCHEMA:
        raise ValueError(f"unsupported OLED customization schema: {schema}")
    defaults = default_document(default_icons)
    raw_icons = value.get("icons")
    if not isinstance(raw_icons, dict):
        raise ValueError("icons must be object")
    unknown_icons = sorted(set(raw_icons) - set(defaults["icons"]))
    if unknown_icons:
        raise ValueError(f"unknown OLED icons: {', '.join(unknown_icons)}")
    missing_icons = sorted(set(defaults["icons"]) - set(raw_icons))
    if missing_icons:
        raise ValueError(f"OLED icons are missing: {', '.join(missing_icons)}")
    icons = {name: _normalize_icon(name, raw_icons[name]) for name in defaults["icons"]}
    _validate_icon_rows_fit(icons)
    ready = _normalize_ready(value.get("ready"))
    return {"schema": SCHEMA, "icons": icons, "ready": ready}


def _path_fingerprint(path: Path) -> tuple[bool, int, int]:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return False, 0, 0
    return True, stat.st_mtime_ns, stat.st_size


def _default_signature(defaults: dict[str, Any]) -> str:
    return json.dumps(defaults, sort_keys=True, separators=(",", ":"))


def load_effective_document(
    default_icons: Mapping[str, Any],
    path: Path | None = None,
) -> tuple[dict[str, Any], str, list[str]]:
    target = path or customization_path()
    defaults = default_document(default_icons)
    fingerprint = _path_fingerprint(target)
    signature = _default_signature(defaults)
    cache_key = str(target)
    cached = _CACHE.get(cache_key)
    if cached is not None and cached[0] == fingerprint and cached[1] == signature:
        return copy.deepcopy(cached[2]), cached[3], list(cached[4])

    source = "default"
    errors: list[str] = []
    document = defaults
    if fingerprint[0]:
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
            document = normalize_document(raw, default_icons)
            source = "runtime"
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(str(exc))
            source = "invalid-runtime-fallback"
    _CACHE[cache_key] = (
        fingerprint,
        signature,
        copy.deepcopy(document),
        source,
        list(errors),
    )
    return copy.deepcopy(document), source, errors


def atomic_write_document(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
    invalidate_cache(path)


def reset_document(path: Path) -> bool:
    try:
        path.unlink()
    except FileNotFoundError:
        removed = False
    else:
        removed = True
    invalidate_cache(path)
    return removed


def invalidate_cache(path: Path | None = None) -> None:
    if path is None:
        _CACHE.clear()
        return
    _CACHE.pop(str(path), None)
