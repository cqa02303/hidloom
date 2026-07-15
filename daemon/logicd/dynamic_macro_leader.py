"""Runtime-only Dynamic Macro / Leader groundwork helpers.

This module does not dispatch HID reports.  It fixes the state owner, record
filter, playback exclusion, and Leader matching boundaries before the helpers
are wired into the live InteractionEngine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from .shared_action_defs import (
    is_layer_action,
    is_macro_action,
    is_script_action,
    is_unicode_action,
    is_wrapper_action,
    shared_connectivity_actions,
)

DYNAMIC_MACRO_SCHEMA = "dynamic_macro.runtime.v1"
LEADER_SCHEMA = "leader.runtime.v1"
DYNAMIC_MACRO_SLOTS = (1, 2)
DYNAMIC_MACRO_CONTROLS = {
    "DM_REC1": ("record", 1),
    "DM_REC2": ("record", 2),
    "DM_RSTP": ("stop", None),
    "DM_PLY1": ("play", 1),
    "DM_PLY2": ("play", 2),
    "DYN_REC_START1": ("record", 1),
    "DYN_REC_START2": ("record", 2),
    "DYN_REC_STOP": ("stop", None),
    "DYN_MACRO_PLAY1": ("play", 1),
    "DYN_MACRO_PLAY2": ("play", 2),
}
LEADER_CONTROLS = {"QK_LEAD", "LEADER"}

_SAFE_KC_RE = re.compile(r"^KC_[A-Z0-9_]+$")
_MOUSE_ACTION_RE = re.compile(r"^(MS_|KC_MS_|KC_BTN|KC_WH_)[A-Z0-9_]*$")
_SYSTEM_ACTION_RE = re.compile(r"^(KC_SHUTDOWN|QK_BOOT|RESET|EEP_RST|MAGIC_|BOOT|SYS_)")
_POWER_ACTIONS = {"POWER_OFF", "REBOOT", "SHUTDOWN", "KC_SYSTEM_SLEEP", "KC_SYSTEM_WAKE", "KC_SYSTEM_POWER"}
_OUTPUT_ACTIONS = {"KC_CONNAUTO", "KC_CONSOLE", "KC_USB", "KC_BT", "OUTPUT_AUTO", "OUTPUT_USB", "OUTPUT_BT"}
_INTERNAL_ACTIONS = {
    "CAPS_WORD",
    "REPEAT_KEY",
    "ALT_REPEAT_KEY",
    "TEXT_SEND_CANCEL",
    "MORSE_FEEDBACK",
    "TOUCH_FLICK",
}
_LEADER_SEQUENCE_RE = re.compile(r"^[A-Z0-9_(),:+.-]+$")


def dynamic_macro_control(action: str) -> tuple[str, int | None] | None:
    """Return the Dynamic Macro control operation for known aliases."""
    return DYNAMIC_MACRO_CONTROLS.get(action)


def is_leader_control(action: str) -> bool:
    """Return whether an action starts Leader sequence capture."""
    return action in LEADER_CONTROLS


def dynamic_macro_record_filter(action: str) -> dict[str, Any]:
    """Return read-only metadata describing whether a final action is recordable."""
    if not isinstance(action, str) or not action:
        return {"recordable": False, "reason": "empty_action"}
    if action in DYNAMIC_MACRO_CONTROLS:
        return {"recordable": False, "reason": "dynamic_macro_control"}
    if action in LEADER_CONTROLS:
        return {"recordable": False, "reason": "leader_control"}
    if action in _INTERNAL_ACTIONS:
        return {"recordable": False, "reason": "internal_control"}
    if action in _OUTPUT_ACTIONS:
        return {"recordable": False, "reason": "output_switch_action"}
    if action in _POWER_ACTIONS or _SYSTEM_ACTION_RE.match(action):
        return {"recordable": False, "reason": "system_or_power_action"}
    if action in shared_connectivity_actions():
        return {"recordable": False, "reason": "connectivity_action"}
    if is_script_action(action):
        return {"recordable": False, "reason": "script_action"}
    if is_macro_action(action):
        return {"recordable": False, "reason": "named_macro_action"}
    if is_layer_action(action):
        return {"recordable": False, "reason": "layer_action"}
    if action.startswith(("TD(", "MORSE(", "COMBO(", "KEY_OVERRIDE(")):
        return {"recordable": False, "reason": "intermediate_state_action"}
    if is_wrapper_action(action) or is_unicode_action(action) or _SAFE_KC_RE.match(action) or _MOUSE_ACTION_RE.match(action):
        return {"recordable": True, "reason": "recordable_final_action"}
    return {"recordable": False, "reason": "unsupported_action"}


@dataclass
class DynamicMacroRuntime:
    """Two-slot runtime-only Dynamic Macro state."""

    max_actions_per_slot: int = 64
    buffers: dict[int, list[str]] = field(default_factory=lambda: {1: [], 2: []})
    state: str = "idle"
    active_slot: int | None = None
    last_cancel_reason: str | None = None
    warnings: list[str] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema": DYNAMIC_MACRO_SCHEMA,
            "state": self.state,
            "active_slot": self.active_slot,
            "slot_lengths": {slot: len(self.buffers.get(slot, [])) for slot in DYNAMIC_MACRO_SLOTS},
            "persistent": False,
            "sends_hid_reports": False,
            "last_cancel_reason": self.last_cancel_reason,
            "warnings": tuple(self.warnings),
        }

    def start_recording(self, slot: int) -> dict[str, Any]:
        if slot not in DYNAMIC_MACRO_SLOTS:
            return self._blocked("invalid_slot")
        if self.state == "playing":
            return self._blocked("playback_active")
        self.state = "recording"
        self.active_slot = slot
        self.buffers[slot] = []
        self.last_cancel_reason = None
        return self.snapshot() | {"accepted": True, "event": "record_started"}

    def record_action(self, action: str) -> dict[str, Any]:
        if self.state != "recording" or self.active_slot not in DYNAMIC_MACRO_SLOTS:
            return self._blocked("not_recording")
        record_filter = dynamic_macro_record_filter(action)
        if not record_filter["recordable"]:
            self.warnings.append(str(record_filter["reason"]))
            return self.snapshot() | {"accepted": False, **record_filter}
        buffer = self.buffers[self.active_slot]
        if len(buffer) >= self.max_actions_per_slot:
            self.warnings.append("slot_full")
            return self.snapshot() | {"accepted": False, "recordable": False, "reason": "slot_full"}
        buffer.append(action)
        return self.snapshot() | {"accepted": True, "recordable": True, "action": action}

    def stop_recording(self) -> dict[str, Any]:
        if self.state != "recording":
            return self._blocked("not_recording")
        slot = self.active_slot
        self.state = "idle"
        self.active_slot = None
        return self.snapshot() | {"accepted": True, "event": "record_stopped", "slot": slot}

    def plan_playback(self, slot: int) -> dict[str, Any]:
        if slot not in DYNAMIC_MACRO_SLOTS:
            return self._blocked("invalid_slot")
        if self.state == "recording":
            return self._blocked("recording_active")
        if self.state == "playing":
            return self._blocked("playback_active")
        actions = tuple(self.buffers.get(slot, ()))
        if not actions:
            return self._blocked("empty_slot")
        self.state = "playing"
        self.active_slot = slot
        return self.snapshot() | {"accepted": True, "event": "playback_planned", "actions": actions}

    def finish_playback(self) -> dict[str, Any]:
        if self.state != "playing":
            return self._blocked("not_playing")
        slot = self.active_slot
        self.state = "idle"
        self.active_slot = None
        return self.snapshot() | {"accepted": True, "event": "playback_finished", "slot": slot}

    def cancel(self, reason: str, *, clear_buffers: bool = True) -> dict[str, Any]:
        self.state = "idle"
        self.active_slot = None
        self.last_cancel_reason = reason
        if clear_buffers:
            self.buffers = {1: [], 2: []}
        return self.snapshot() | {"accepted": True, "event": "cancelled", "reason": reason}

    def handle_control(self, action: str) -> dict[str, Any]:
        control = dynamic_macro_control(action)
        if control is None:
            return self._blocked("not_dynamic_macro_control")
        op, slot = control
        if op == "record" and slot is not None:
            return self.start_recording(slot)
        if op == "stop":
            return self.stop_recording()
        if op == "play" and slot is not None:
            return self.plan_playback(slot)
        return self._blocked("unsupported_control")

    def _blocked(self, reason: str) -> dict[str, Any]:
        return self.snapshot() | {"accepted": False, "reason": reason}


def validate_leader_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Validate read-only Leader settings and normalize sequence keys."""
    raw = settings if isinstance(settings, dict) else {}
    leader = raw.get("leader", raw) if isinstance(raw.get("leader", raw), dict) else {}
    enabled = bool(leader.get("enabled", False))
    timeout = leader.get("timeout", 0.7)
    sequences_raw = leader.get("sequences", {})
    errors: list[str] = []
    sequences: dict[tuple[str, ...], str] = {}
    if not isinstance(timeout, (int, float)) or not (0.05 <= float(timeout) <= 5.0):
        errors.append("leader_timeout_out_of_range")
        timeout = 0.7
    if not isinstance(sequences_raw, dict):
        errors.append("leader_sequences_must_be_object")
        sequences_raw = {}
    for sequence_text, action in sequences_raw.items():
        if not isinstance(sequence_text, str) or not isinstance(action, str):
            errors.append("leader_sequence_and_action_must_be_strings")
            continue
        parts = tuple(part.strip() for part in sequence_text.split(",") if part.strip())
        if not parts or any(not _LEADER_SEQUENCE_RE.fullmatch(part) for part in parts):
            errors.append(f"invalid_leader_sequence:{sequence_text}")
            continue
        if not dynamic_macro_record_filter(action)["recordable"]:
            errors.append(f"invalid_leader_action:{sequence_text}")
            continue
        sequences[parts] = action
    return {
        "schema": LEADER_SCHEMA,
        "enabled": enabled,
        "timeout": float(timeout),
        "sequences": sequences,
        "valid": not errors,
        "errors": tuple(errors),
        "default_disabled": not enabled,
        "sends_hid_reports": False,
    }


@dataclass
class LeaderRuntime:
    """Read-only Leader sequence matcher."""

    settings: dict[str, Any] | None
    pending: bool = False
    sequence: tuple[str, ...] = ()
    deadline: float | None = None
    last_cancel_reason: str | None = None

    def __post_init__(self) -> None:
        self.validation = validate_leader_settings(self.settings)

    def start(self, now: float) -> dict[str, Any]:
        if not self.validation["enabled"] or not self.validation["valid"]:
            return self.snapshot() | {"accepted": False, "reason": "leader_disabled_or_invalid"}
        self.pending = True
        self.sequence = ()
        self.deadline = now + self.validation["timeout"]
        self.last_cancel_reason = None
        return self.snapshot() | {"accepted": True, "event": "leader_pending"}

    def input_action(self, action: str, now: float) -> dict[str, Any]:
        if not self.pending:
            return self.snapshot() | {"accepted": False, "reason": "leader_not_pending"}
        if self.deadline is not None and now > self.deadline:
            return self.cancel("timeout")
        if not dynamic_macro_record_filter(action)["recordable"]:
            return self.cancel("non_recordable_action")
        next_sequence = (*self.sequence, action)
        sequences: dict[tuple[str, ...], str] = self.validation["sequences"]
        if next_sequence in sequences:
            matched = sequences[next_sequence]
            self.pending = False
            self.sequence = ()
            self.deadline = None
            return self.snapshot() | {"accepted": True, "event": "leader_matched", "action": matched}
        if any(seq[: len(next_sequence)] == next_sequence for seq in sequences):
            self.sequence = next_sequence
            return self.snapshot() | {"accepted": True, "event": "leader_progress"}
        return self.cancel("unmatched_sequence")

    def cancel(self, reason: str) -> dict[str, Any]:
        self.pending = False
        self.sequence = ()
        self.deadline = None
        self.last_cancel_reason = reason
        return self.snapshot() | {"accepted": True, "event": "leader_cancelled", "reason": reason}

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema": LEADER_SCHEMA,
            "enabled": self.validation["enabled"],
            "valid": self.validation["valid"],
            "pending": self.pending,
            "sequence": self.sequence,
            "deadline": self.deadline,
            "sends_hid_reports": False,
            "last_cancel_reason": self.last_cancel_reason,
            "errors": self.validation["errors"],
        }
