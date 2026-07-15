"""Read-only inspector for MORSE interaction behaviors."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from aiohttp import web

from interaction_api import build_interaction_payload

MORSE_INSPECTOR_ROUTE = "/api/interaction/morse-inspector"


def build_morse_inspector_payload(config_json: Path, vial_json: Path) -> dict[str, Any]:
    """Build a read-only tree view for settings.interaction.morse_behaviors."""
    interaction = build_interaction_payload(config_json, vial_json)
    settings = interaction.get("settings", {}) if isinstance(interaction, dict) else {}
    behaviors = settings.get("morse_behaviors", {}) if isinstance(settings, dict) else {}
    if not isinstance(behaviors, dict):
        behaviors = {}

    inspected = []
    summary = {
        "behaviors": 0,
        "mapped_sequences": 0,
        "force_commit_sequences": 0,
        "warnings": 0,
    }
    warnings: list[str] = []

    for name in sorted(behaviors):
        raw = behaviors[name]
        if not isinstance(raw, dict):
            continue
        item = inspect_morse_behavior(name, raw)
        inspected.append(item)
        summary["behaviors"] += 1
        summary["mapped_sequences"] += item["summary"]["mapped_sequences"]
        summary["force_commit_sequences"] += item["summary"]["force_commit_sequences"]
        warnings.extend(item["warnings"])

    summary["warnings"] = len(warnings)
    return {
        "result": "ok",
        "behaviors": inspected,
        "summary": summary,
        "warnings": warnings,
        "schema": {
            "route": MORSE_INSPECTOR_ROUTE,
            "states": ["root", "leaf", "prefix", "force_commit", "cancel", "unassigned_prefix"],
            "editor": "read_only",
            "force_commit_name": "force_commit",
            "legacy_aliases": ["terminal", "terminal_sequences"],
        },
        "interaction_warnings": interaction.get("warnings", []),
    }


def inspect_morse_behavior(name: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Return one behavior as a tree plus summary/warnings."""
    mapping = raw.get("map", {})
    if not isinstance(mapping, dict):
        mapping = {}
    actions = {str(seq): str(action) for seq, action in mapping.items() if _valid_sequence(str(seq))}
    force_commit = raw.get("force_commit", raw.get("terminal", raw.get("terminal_sequences", [])))
    force_commit_set = _sequence_set(force_commit)
    try:
        max_depth = max(1, int(raw.get("max_depth", max([len(seq) for seq in actions] + [1]))))
    except (TypeError, ValueError):
        max_depth = max([len(seq) for seq in actions] + [1])
    max_depth = min(max_depth, 8)

    warnings: list[str] = []
    for seq in sorted(force_commit_set):
        if seq not in actions:
            warnings.append(f"{name}: force_commit {seq} has no mapped action")
        deeper = [candidate for candidate in actions if candidate.startswith(seq) and candidate != seq]
        if deeper:
            warnings.append(f"{name}: force_commit {seq} hides deeper branch(es): {', '.join(sorted(deeper))}")

    root = _build_node("", actions, force_commit_set, max_depth=max_depth)
    return {
        "name": name,
        "dot_threshold": raw.get("dot_threshold", 0.180),
        "sequence_timeout": raw.get("sequence_timeout", 0.700),
        "max_depth": max_depth,
        "tree": root,
        "summary": {
            "mapped_sequences": len(actions),
            "force_commit_sequences": len([seq for seq in force_commit_set if seq in actions]),
            "leaf_sequences": sum(1 for seq in actions if not _has_deeper(seq, actions)),
            "prefix_sequences": sum(1 for seq in actions if _has_deeper(seq, actions)),
        },
        "warnings": warnings,
    }


def _build_node(sequence: str, actions: dict[str, str], force_commit: set[str], *, max_depth: int) -> dict[str, Any]:
    action = actions.get(sequence)
    has_deeper = _has_deeper(sequence, actions)
    is_force_commit = sequence in force_commit and action is not None
    if sequence == "":
        state = "root"
    elif is_force_commit:
        state = "force_commit"
    elif action is not None and has_deeper:
        state = "prefix"
    elif action is not None:
        state = "leaf"
    elif has_deeper:
        state = "unassigned_prefix"
    else:
        state = "cancel"

    node = {
        "sequence": sequence,
        "stroke": sequence[-1:] if sequence else "",
        "depth": len(sequence),
        "action": action,
        "state": state,
        "force_commit": is_force_commit,
        "has_deeper_branch": has_deeper,
        "children": [],
    }

    if len(sequence) >= max_depth:
        return node

    child_sequences = _child_sequences(sequence, actions, include_cancel_children=(sequence == "" or has_deeper or action is not None))
    for child in child_sequences:
        child_node = _build_node(child, actions, force_commit, max_depth=max_depth)
        if is_force_commit and child_node["state"] != "cancel":
            child_node["reachable"] = False
            child_node["hidden_by_force_commit"] = sequence
        else:
            child_node["reachable"] = True
        node["children"].append(child_node)
    return node


def _child_sequences(sequence: str, actions: dict[str, str], *, include_cancel_children: bool) -> list[str]:
    candidates = {candidate[: len(sequence) + 1] for candidate in actions if candidate.startswith(sequence) and len(candidate) > len(sequence)}
    if include_cancel_children:
        candidates.add(sequence + ".")
        candidates.add(sequence + "-")
    return sorted(candidates, key=lambda value: (value[-1] == "-", value))


def _has_deeper(sequence: str, actions: dict[str, str]) -> bool:
    return any(candidate != sequence and candidate.startswith(sequence) for candidate in actions)


def _valid_sequence(sequence: str) -> bool:
    return bool(sequence) and all(ch in ".-" for ch in sequence)


def _sequence_set(raw: Any) -> set[str]:
    if raw in (None, "", []):
        return set()
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, list):
        values = raw
    else:
        return set()
    return {str(value).strip() for value in values if _valid_sequence(str(value).strip())}


async def morse_inspector_response(config_json: Path, vial_json: Path) -> web.Response:
    try:
        return web.json_response(build_morse_inspector_payload(config_json, vial_json))
    except Exception as exc:
        return web.json_response({"result": "error", "msg": str(exc)}, status=500)


def register_morse_inspector_route(app: web.Application, config_json: Path, vial_json: Path) -> None:
    async def _handle(_request: web.Request) -> web.Response:
        return await morse_inspector_response(config_json, vial_json)

    app.router.add_get(MORSE_INSPECTOR_ROUTE, _handle)
