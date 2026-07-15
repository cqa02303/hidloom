"""Helpers for deriving UI control metadata from keymap definitions."""
from __future__ import annotations

from typing import Any, Dict

JOYSTICK_LABEL_DIRECTIONS = {
    "UP": "up",
    "DOWN": "down",
    "LEFT": "left",
    "RIGHT": "right",
}


def matrix_key(row: int, col: int) -> str:
    return f"{row},{col}"


def control_metadata_from_keymap(keymap: Dict[str, Any]) -> Dict[str, Any]:
    layout_def = keymap.get("_layout_def", {})
    if not isinstance(layout_def, dict):
        return {
            "joystick_directions": {},
            "encoder_directions": {},
            "encoder_actions": {},
            "encoder_click_keys": [],
        }

    joystick_directions: Dict[str, str] = {}
    stick_entries = layout_def.get("stick", [])
    if isinstance(stick_entries, list):
        for entry in stick_entries:
            if not isinstance(entry, list) or len(entry) < 3:
                continue
            try:
                row, col, label = int(entry[0]), int(entry[1]), str(entry[2]).upper()
            except (TypeError, ValueError):
                continue
            for suffix, direction in JOYSTICK_LABEL_DIRECTIONS.items():
                if label.endswith(suffix):
                    joystick_directions[matrix_key(row, col)] = direction
                    break

    encoder_directions: Dict[str, str] = {}
    encoder_actions: Dict[str, Dict[str, str]] = {}
    encoder_click_keys: list[str] = []
    encoder_groups = sorted(
        (item for item in layout_def.items() if isinstance(item[0], str) and item[0].startswith("encoder")),
        key=lambda item: item[0],
    )
    for encoder_index, (group, entries) in enumerate(encoder_groups):
        if not isinstance(group, str) or not group.startswith("encoder"):
            continue
        if not isinstance(entries, list):
            continue
        actions: Dict[str, str] = {}
        for entry in entries:
            if not isinstance(entry, list) or len(entry) < 3:
                continue
            try:
                row, col, label = int(entry[0]), int(entry[1]), str(entry[2])
            except (TypeError, ValueError):
                continue
            key = matrix_key(row, col)
            if label.endswith("A"):
                encoder_directions[key] = "cw"
                actions["cw"] = key
            elif label.endswith("B"):
                encoder_directions[key] = "ccw"
                actions["ccw"] = key
            else:
                encoder_click_keys.append(key)
        if actions:
            encoder_actions[str(encoder_index)] = actions

    return {
        "joystick_directions": joystick_directions,
        "encoder_directions": encoder_directions,
        "encoder_actions": encoder_actions,
        "encoder_click_keys": sorted(set(encoder_click_keys)),
    }
