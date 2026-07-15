"""Read-only QMK Unicode map and mode groundwork helpers."""
from __future__ import annotations

import re
from typing import Any

from .text_send_safety import (
    DEFAULT_UNICODE_MODE,
    build_text_send_tap_dry_run,
    explicit_text_send_host_profile,
    normalize_unicode_mode,
)

QMK_UNICODE_MAP_SCHEMA = "qmk_unicode.map.v1"
QMK_UNICODE_ACTION_SCHEMA = "qmk_unicode.action_plan.v1"
QMK_UNICODE_MODE_ACTIONS = {
    "UC_LINX": "linux_ctrl_shift_u",
    "UC_WIN": "windows_ime_hex_f5",
    "UC_WINC": "windows_ime_hex_f5",
    "UC_MAC": "unsupported",
    "UC_EMAC": "unsupported",
    "UC_NEXT": "cycle_not_supported",
    "UC_PREV": "cycle_not_supported",
}

_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,48}$")
_UC_RE = re.compile(r"^UC\(([0-9A-Fa-f]{1,6})\)$")
_UM_RE = re.compile(r"^UM\(([A-Za-z0-9_.-]{1,48})\)$")
_UP_RE = re.compile(r"^UP\(([A-Za-z0-9_.-]{1,48}),\s*([A-Za-z0-9_.-]{1,48})\)$")


def _settings_unicode_map(settings: dict[str, Any] | None) -> dict[str, Any]:
    settings = settings or {}
    raw = settings.get("unicode_map")
    if raw is None:
        unicode_settings = settings.get("unicode") if isinstance(settings.get("unicode"), dict) else {}
        raw = unicode_settings.get("map")
    return raw if isinstance(raw, dict) else {}


def normalize_qmk_unicode_codepoint(value: object) -> str | None:
    """Return uppercase 4-6 digit hex codepoint, or None when invalid."""
    if isinstance(value, int):
        codepoint = value
    else:
        text = str(value or "").strip()
        if text.upper().startswith("U+"):
            text = text[2:]
        if not re.fullmatch(r"[0-9A-Fa-f]{1,6}", text):
            return None
        codepoint = int(text, 16)
    if codepoint < 0 or codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
        return None
    return f"{codepoint:04X}" if codepoint <= 0xFFFF else f"{codepoint:06X}"


def validate_qmk_unicode_map(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    raw_map = _settings_unicode_map(settings)
    entries: list[dict[str, Any]] = []
    for name, value in sorted(raw_map.items(), key=lambda item: str(item[0])):
        name_text = str(name or "")
        errors: list[str] = []
        if not _NAME_RE.fullmatch(name_text):
            errors.append("invalid_name")
        codepoint = normalize_qmk_unicode_codepoint(value)
        if codepoint is None:
            errors.append("invalid_codepoint")
        entries.append({
            "name": name_text,
            "codepoint": codepoint,
            "valid": not errors,
            "errors": errors,
        })
    return {
        "schema": QMK_UNICODE_MAP_SCHEMA,
        "read_only": True,
        "entry_count": len(entries),
        "valid": all(entry["valid"] for entry in entries),
        "entries": entries,
        "errors": [error for entry in entries for error in entry["errors"]],
    }


def _lookup_unicode_map_codepoint(settings: dict[str, Any] | None, name: str) -> str | None:
    return normalize_qmk_unicode_codepoint(_settings_unicode_map(settings).get(name))


def qmk_unicode_mode_gate(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings or {}
    unicode_settings = settings.get("unicode") if isinstance(settings.get("unicode"), dict) else {}
    mode = normalize_unicode_mode(unicode_settings.get("mode"))
    host_profile = explicit_text_send_host_profile(settings)
    blocking: list[str] = []
    if mode == DEFAULT_UNICODE_MODE:
        blocking.append("unicode_mode_none")
    if not host_profile["explicit"]:
        blocking.append("explicit_host_profile_required")
    return {
        "mode": mode,
        "host_profile": host_profile,
        "ready_for_preview": not blocking,
        "blocking_reasons": blocking,
        "auto_mode_switching": False,
        "persistent_mode_mutation": False,
    }


def build_qmk_unicode_action_plan(action: object, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = str(action or "").strip()
    gate = qmk_unicode_mode_gate(settings)
    blocking = list(gate["blocking_reasons"])
    codepoints: list[str] = []
    family = "unsupported"
    normalized: str | None = None

    if m := _UC_RE.fullmatch(raw):
        family = "uc"
        codepoint = normalize_qmk_unicode_codepoint(m.group(1))
        if codepoint is None:
            blocking.append("invalid_codepoint")
        else:
            codepoints.append(codepoint)
            normalized = f"UC({codepoint})"
    elif m := _UM_RE.fullmatch(raw):
        family = "um"
        name = m.group(1)
        codepoint = _lookup_unicode_map_codepoint(settings, name)
        if codepoint is None:
            blocking.append("unicode_map_entry_missing_or_invalid")
        else:
            codepoints.append(codepoint)
        normalized = f"UM({name})"
    elif m := _UP_RE.fullmatch(raw):
        family = "up"
        names = [m.group(1), m.group(2)]
        for name in names:
            codepoint = _lookup_unicode_map_codepoint(settings, name)
            if codepoint is None:
                blocking.append("unicode_map_entry_missing_or_invalid")
            else:
                codepoints.append(codepoint)
        normalized = f"UP({names[0]},{names[1]})"
    elif raw in QMK_UNICODE_MODE_ACTIONS:
        family = "unicode_mode"
        target = QMK_UNICODE_MODE_ACTIONS[raw]
        normalized = raw
        blocking.append("unicode_mode_action_is_preview_only")
        if target in {"unsupported", "cycle_not_supported"}:
            blocking.append(f"unicode_mode_{target}")
    else:
        blocking.append("unsupported_qmk_unicode_action")

    previews: list[dict[str, Any]] = []
    if codepoints and not blocking:
        for codepoint in codepoints:
            previews.append(build_text_send_tap_dry_run(f"U+{codepoint}", settings))

    blocking = list(dict.fromkeys(blocking))
    return {
        "schema": QMK_UNICODE_ACTION_SCHEMA,
        "read_only": True,
        "sends_hid_reports": False,
        "action": raw,
        "family": family,
        "normalized": normalized,
        "codepoints": codepoints,
        "gate": gate,
        "preview_available": bool(previews) and not blocking,
        "blocking_reasons": blocking,
        "tap_previews": previews,
    }
