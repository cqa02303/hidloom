"""Summary helpers for Interaction inspector payloads.

These helpers are intentionally read-only and UI-oriented.  They derive warning
counts, section status, and a save-safety hint from an inspector payload without
changing the settings or rewriting warnings.
"""
from __future__ import annotations

from typing import Any, Mapping

_SEVERITIES = ("error", "warning", "info")


def severity_counts(warnings: list[Mapping[str, Any]]) -> dict[str, int]:
    """Count inspector warnings by severity."""
    counts = {severity: 0 for severity in _SEVERITIES}
    for warning in warnings:
        severity = str(warning.get("severity", "warning"))
        if severity not in counts:
            severity = "warning"
        counts[severity] += 1
    return counts


def section_status(items: list[Mapping[str, Any]]) -> str:
    """Return aggregate section status from item statuses."""
    statuses = {str(item.get("status", "ok")) for item in items}
    if "error" in statuses:
        return "error"
    if "warning" in statuses:
        return "warning"
    return "ok"


def build_interaction_validation_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Build compact UI summary from an interaction inspector payload.

    The summary intentionally does not include action names or raw config
    fragments beyond the section names that already exist in the payload.
    """
    warnings = payload.get("warnings", [])
    if not isinstance(warnings, list):
        warnings = []
    counts = severity_counts(warnings)
    sections = payload.get("sections", {})
    if not isinstance(sections, dict):
        sections = {}
    section_summary: dict[str, dict[str, Any]] = {}
    for name in ("combos", "tap_dances", "key_overrides"):
        raw_items = sections.get(name, [])
        items = raw_items if isinstance(raw_items, list) else []
        item_warnings = [
            warning
            for item in items
            if isinstance(item, dict)
            for warning in item.get("warnings", []) or []
            if isinstance(warning, dict)
        ]
        section_summary[name] = {
            "items": len(items),
            "status": section_status(items),
            "warnings": len(item_warnings),
        }
    return {
        "schema": "interaction.inspector.validation_summary.v1",
        "read_only": True,
        "severity_counts": counts,
        "total_warnings": sum(counts.values()),
        "has_errors": counts["error"] > 0,
        "has_warnings": counts["warning"] > 0,
        "save_hint": "blocked" if counts["error"] else ("review" if counts["warning"] else "ok"),
        "sections": section_summary,
    }


def attach_interaction_validation_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of payload with validation_summary attached."""
    result = dict(payload)
    result["validation_summary"] = build_interaction_validation_summary(payload)
    return result
