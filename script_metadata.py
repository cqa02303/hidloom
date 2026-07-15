#!/usr/bin/env python3
"""Metadata and conservative safety checks for editable KC_SH scripts."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_DANGER_LINE_RE = re.compile(r"^\s*#\s*@danger\s+([A-Za-z0-9_.:-]+)(?:\s+(.*))?$", re.MULTILINE)
_CONFIRM_LINE_RE = re.compile(r"^\s*#\s*@confirm\s+(.+)$", re.MULTILINE)
_PIN_LINE_RE = re.compile(r"^\s*#\s*@pin\b", re.MULTILINE)
_HIDDEN_LINE_RE = re.compile(r"^\s*#\s*@hidden\b", re.MULTILINE)

# Keep this intentionally conservative.  False positives are safer than letting
# a check-run reboot or shut the device down without an explicit second action.
_DANGEROUS_COMMAND_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("reboot", re.compile(r"(^|[;&|`$()\s])(?:sudo\s+)?(?:systemctl\s+)?reboot(?:\s|$)", re.MULTILINE)),
    ("shutdown", re.compile(r"(^|[;&|`$()\s])(?:sudo\s+)?(?:shutdown|poweroff|halt)(?:\s|$)", re.MULTILINE)),
    ("systemctl-power", re.compile(r"(^|[;&|`$()\s])(?:sudo\s+)?systemctl\s+(?:poweroff|halt|reboot)(?:\s|$)", re.MULTILINE)),
    ("destructive-rm", re.compile(r"(^|[;&|`$()\s])(?:sudo\s+)?rm\s+-[A-Za-z]*r[fA-Za-z]*\s+/(?:\s|$|[^/])", re.MULTILINE)),
)


@dataclass(frozen=True)
class ScriptSafetyMetadata:
    dangers: tuple[str, ...]
    confirmations: tuple[str, ...]
    auto_dangers: tuple[str, ...]
    pinned: bool
    hidden: bool

    @property
    def dangerous(self) -> bool:
        return bool(self.dangers or self.auto_dangers)

    @property
    def confirm_message(self) -> str:
        if self.confirmations:
            return "\n".join(self.confirmations)
        if self.dangers:
            return f"Dangerous script metadata: {', '.join(self.dangers)}"
        if self.auto_dangers:
            return f"Potentially dangerous commands detected: {', '.join(self.auto_dangers)}"
        return ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "dangerous": self.dangerous,
            "dangers": list(self.dangers),
            "confirmations": list(self.confirmations),
            "auto_dangers": list(self.auto_dangers),
            "confirm_message": self.confirm_message,
            "pinned": self.pinned,
            "hidden": self.hidden,
        }


def analyze_script_safety(content: str) -> ScriptSafetyMetadata:
    """Parse script metadata comments and detect dangerous commands."""

    text = content or ""
    dangers = tuple(dict.fromkeys(match.group(1).strip() for match in _DANGER_LINE_RE.finditer(text)))
    confirmations = tuple(dict.fromkeys(match.group(1).strip() for match in _CONFIRM_LINE_RE.finditer(text)))
    command_text = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    auto = []
    for name, pattern in _DANGEROUS_COMMAND_PATTERNS:
        if pattern.search(command_text):
            auto.append(name)
    return ScriptSafetyMetadata(
        dangers=dangers,
        confirmations=confirmations,
        auto_dangers=tuple(dict.fromkeys(auto)),
        pinned=bool(_PIN_LINE_RE.search(text)),
        hidden=bool(_HIDDEN_LINE_RE.search(text)),
    )
