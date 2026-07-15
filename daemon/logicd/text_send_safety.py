"""Read-only safety metadata for Unicode / Send String style actions."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


DEFAULT_UNICODE_MODE = "none"
DEFAULT_SEND_STRING_MAX_LENGTH = 80
DEFAULT_TEXT_SEND_RUNNER_TIMEOUT_SEC = 2.0
SUPPORTED_UNICODE_MODES = (
    "none",
    "linux_ctrl_shift_u",
    "mac_unicode_hex",
    "win_alt_code",
    "windows_ime_hex_f5",
    "tap_sequence",
)
TEXT_SEND_CANCEL_TRIGGERS = (
    "output_switch",
    "config_reload",
    "keymap_reload",
    "emergency_release",
    "daemon_shutdown",
    "explicit_cancel",
    "runner_timeout",
)
TEXT_SEND_HTTP_WARNING_SCOPE = (
    "interaction_summary",
    "touch_flick_preview",
    "keymap_action_preview",
)
TEXT_SEND_REAL_SEND_STEP_SCOPE = (
    "begin_runtime_state",
    "emit_keyboard_taps_only",
    "cancel_on_output_switch",
    "cancel_on_config_reload",
    "cancel_on_emergency_release",
    "cancel_on_runner_timeout",
    "send_zero_report_on_cancel",
)
TEXT_SEND_FORBIDDEN_REAL_SEND_STEPS = (
    "shell_script",
    "system_action",
    "connectivity_action",
    "power_action",
    "direct_text_in_keymap",
    "vial_macro_buffer",
    "newline_codepoint",
)
TEXT_SEND_RUNNER_SCHEMA = "text_send.runner_connection.v1"
TEXT_SEND_TAP_DRY_RUN_SCHEMA = "text_send.tap_dry_run.v1"
TEXT_SEND_TAP_DRY_RUN_SUPPORTED_MODES = ("linux_ctrl_shift_u", "windows_ime_hex_f5")
TEXT_SEND_RUNNER_METHOD = "logicd_keyboard_tap_runner"
TEXT_SEND_RUNNER_TARGET = "active_output_keyboard"
TEXT_SEND_RUNNER_CANCEL_PATH = "text_send_runtime_state"
TEXT_SEND_NO_OP_RELEASE_CONDITIONS = (
    "explicit_host_profile",
    "unicode_mode_not_none",
    "runner_connected",
    "runner_method_logicd_keyboard_tap_runner",
    "runner_target_active_output_keyboard",
    "runner_cancel_path_text_send_runtime_state",
    "runner_zero_report_on_cancel",
    "runner_timeout_configured",
    "named_entry_valid_when_required",
)
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,48}$")
_UNICODE_RE = re.compile(r"^U\+([0-9A-Fa-f]{4,6})$")
_SEND_STRING_RE = re.compile(r"^(SEND_STRING|TEXT)\(([A-Za-z0-9_.-]{1,48})\)$")
_UC_MODE_RE = re.compile(r"^UC_MODE\(([A-Za-z0-9_.-]+)\)$")
_ZERO_WIDTH_CODEPOINTS = {0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF}
_HEX_KEYCODES = {ch: f"KC_{ch}" for ch in "0123456789ABCDEF"}


@dataclass(frozen=True)
class TextSendActionStatus:
    action: str
    family: str
    supported: bool
    executable: bool
    warning: str
    normalized: str | None = None
    name: str | None = None
    codepoint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "action": self.action,
            "family": self.family,
            "supported": self.supported,
            "executable": self.executable,
            "warning": self.warning,
        }
        if self.normalized is not None:
            data["normalized"] = self.normalized
        if self.name is not None:
            data["name"] = self.name
        if self.codepoint is not None:
            data["codepoint"] = self.codepoint
        return data


@dataclass
class TextSendRuntimeState:
    """Cancel and timeout state shared with the text-send runner."""

    active: bool = False
    active_name: str | None = None
    active_started_at: float | None = None
    runner_timeout_sec: float | None = None
    deadline_at: float | None = None
    last_cancel_reason: str | None = None
    cancel_count: int = 0
    timeout_count: int = 0
    last_zero_report_reason: str | None = None
    zero_report_count: int = 0

    def begin(
        self,
        name: str | None = None,
        *,
        now: float | None = None,
        timeout_sec: float | None = DEFAULT_TEXT_SEND_RUNNER_TIMEOUT_SEC,
    ) -> dict[str, Any]:
        self.active = True
        self.active_name = name
        self.active_started_at = now
        self.runner_timeout_sec = normalize_text_send_runner_timeout(timeout_sec)
        self.deadline_at = (
            now + self.runner_timeout_sec
            if now is not None and self.runner_timeout_sec is not None
            else None
        )
        self.last_cancel_reason = None
        return self.to_dict()

    def cancel(self, reason: str) -> dict[str, Any]:
        normalized = normalize_text_send_cancel_reason(reason)
        was_active = self.active
        self.active = False
        self.active_name = None
        self.active_started_at = None
        self.runner_timeout_sec = None
        self.deadline_at = None
        self.last_cancel_reason = normalized
        if was_active:
            self.cancel_count += 1
        if normalized == "runner_timeout":
            self.timeout_count += 1
        data = self.to_dict()
        data["canceled"] = was_active
        data["zero_report_required"] = was_active or normalized == "emergency_release"
        data["zero_report_sent"] = False
        return data

    def finish(self) -> dict[str, Any]:
        was_active = self.active
        self.active = False
        self.active_name = None
        self.active_started_at = None
        self.runner_timeout_sec = None
        self.deadline_at = None
        data = self.to_dict()
        data["finished"] = was_active
        return data

    def timeout_due(self, now: float) -> bool:
        return bool(self.active and self.deadline_at is not None and now >= self.deadline_at)

    def cancel_if_timed_out(self, now: float) -> dict[str, Any] | None:
        if not self.timeout_due(now):
            return None
        return self.cancel("runner_timeout")

    def mark_zero_report_sent(self, reason: str) -> dict[str, Any]:
        normalized = normalize_text_send_cancel_reason(reason)
        self.last_zero_report_reason = normalized
        self.zero_report_count += 1
        data = self.to_dict()
        data["zero_report_required"] = False
        data["zero_report_sent"] = True
        return data

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "active_name": self.active_name,
            "active_started_at": self.active_started_at,
            "runner_timeout_sec": self.runner_timeout_sec,
            "deadline_at": self.deadline_at,
            "last_cancel_reason": self.last_cancel_reason,
            "cancel_count": self.cancel_count,
            "timeout_count": self.timeout_count,
            "last_zero_report_reason": self.last_zero_report_reason,
            "zero_report_count": self.zero_report_count,
        }


def normalize_unicode_mode(value: object) -> str:
    mode = str(value or DEFAULT_UNICODE_MODE).strip().lower()
    return mode if mode in SUPPORTED_UNICODE_MODES else DEFAULT_UNICODE_MODE


def normalize_text_send_cancel_reason(value: object) -> str:
    reason = str(value or "explicit_cancel").strip().lower()
    return reason if reason in TEXT_SEND_CANCEL_TRIGGERS else "explicit_cancel"


def normalize_text_send_runner_timeout(value: object) -> float | None:
    if value is None:
        return None
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        return DEFAULT_TEXT_SEND_RUNNER_TIMEOUT_SEC
    if timeout <= 0:
        return DEFAULT_TEXT_SEND_RUNNER_TIMEOUT_SEC
    return min(timeout, 30.0)


def send_string_name_valid(name: object) -> bool:
    return bool(_NAME_RE.fullmatch(str(name or "")))


def _has_zero_width(text: str) -> bool:
    return any(ord(ch) in _ZERO_WIDTH_CODEPOINTS for ch in text)


def validate_send_string_entry(name: object, entry: object, *, max_length: int = DEFAULT_SEND_STRING_MAX_LENGTH) -> dict[str, Any]:
    """Validate a named text snippet without executing it."""
    warnings: list[str] = []
    errors: list[str] = []
    name_text = str(name or "")
    if not send_string_name_valid(name_text):
        errors.append("invalid name")

    if isinstance(entry, str):
        text = entry
        allow_newline = False
        enabled = True
        confirm = False
    elif isinstance(entry, dict):
        text = entry.get("text")
        allow_newline = bool(entry.get("allow_newline", False))
        enabled = bool(entry.get("enabled", True))
        confirm = bool(entry.get("confirm", False))
    else:
        text = None
        allow_newline = False
        enabled = False
        confirm = False
        errors.append("entry must be string or object")

    if not isinstance(text, str):
        text = ""
        errors.append("text must be string")

    if len(text) > max_length:
        errors.append("text too long")
    if any(ord(ch) < 0x20 and ch not in {"\n", "\t"} for ch in text):
        errors.append("control character")
    if "\n" in text and not allow_newline:
        errors.append("newline requires allow_newline")
    if "\t" in text:
        warnings.append("tab requires explicit review")
    if _has_zero_width(text):
        warnings.append("zero-width character")
    if confirm:
        warnings.append("confirmation required")
    if not enabled:
        warnings.append("disabled")

    return {
        "name": name_text,
        "valid": not errors,
        "enabled": enabled,
        "confirm": confirm,
        "allow_newline": allow_newline,
        "length": len(text),
        "max_length": max_length,
        "errors": errors,
        "warnings": warnings,
    }


def validate_send_string_settings(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings or {}
    entries = settings.get("send_strings")
    if entries is None:
        entries = {}
    if not isinstance(entries, dict):
        return {
            "valid": False,
            "entry_count": 0,
            "error_count": 1,
            "warning_count": 0,
            "entries": [],
            "errors": ["settings.send_strings must be object"],
        }
    results = [validate_send_string_entry(name, entry) for name, entry in sorted(entries.items(), key=lambda item: str(item[0]))]
    return {
        "valid": all(item["valid"] for item in results),
        "entry_count": len(results),
        "error_count": sum(len(item["errors"]) for item in results),
        "warning_count": sum(len(item["warnings"]) for item in results),
        "entries": results,
        "errors": [],
    }


def get_send_string_entry(settings: dict[str, Any] | None, name: str | None) -> object | None:
    entries = (settings or {}).get("send_strings")
    if not isinstance(entries, dict) or not name:
        return None
    return entries.get(name)


def explicit_text_send_host_profile(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings or {}
    unicode_settings = settings.get("unicode") if isinstance(settings.get("unicode"), dict) else {}
    raw = (
        unicode_settings.get("host_profile")
        or unicode_settings.get("profile")
        or unicode_settings.get("manual_host_profile")
    )
    profile = str(raw or "").strip()
    explicit = bool(profile)
    return {
        "required_for_real_send": True,
        "explicit": explicit,
        "profile": profile or None,
        "source": "settings.unicode.host_profile" if explicit else None,
        "auto_detection": False,
        "reason": "configured" if explicit else "explicit_host_profile_required",
    }


def text_send_runner_connection(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Describe whether the configured text-send runner can execute safely."""
    settings = settings or {}
    runner_settings = settings.get("text_send_runner") if isinstance(settings.get("text_send_runner"), dict) else {}
    method = str(runner_settings.get("method") or "").strip()
    target = str(runner_settings.get("target") or "").strip()
    cancel_path = str(runner_settings.get("cancel_path") or "").strip()
    timeout_sec = normalize_text_send_runner_timeout(
        runner_settings.get("timeout_sec", DEFAULT_TEXT_SEND_RUNNER_TIMEOUT_SEC)
    )
    connected = bool(runner_settings.get("connected", False))
    zero_report = bool(runner_settings.get("zero_report_on_cancel", False))
    blocking: list[str] = []
    if not connected:
        blocking.append("send_string_runner_not_connected")
    if method != TEXT_SEND_RUNNER_METHOD:
        blocking.append("text_send_runner_method_not_supported")
    if target != TEXT_SEND_RUNNER_TARGET:
        blocking.append("text_send_runner_target_not_active_output_keyboard")
    if cancel_path != TEXT_SEND_RUNNER_CANCEL_PATH:
        blocking.append("text_send_runner_cancel_path_not_wired")
    if not zero_report:
        blocking.append("text_send_runner_zero_report_not_wired")
    if timeout_sec is None:
        blocking.append("text_send_runner_timeout_not_configured")
    return {
        "schema": TEXT_SEND_RUNNER_SCHEMA,
        "connected": connected,
        "ready": not blocking,
        "method": method or None,
        "required_method": TEXT_SEND_RUNNER_METHOD,
        "target": target or None,
        "required_target": TEXT_SEND_RUNNER_TARGET,
        "cancel_path": cancel_path or None,
        "required_cancel_path": TEXT_SEND_RUNNER_CANCEL_PATH,
        "zero_report_on_cancel": zero_report,
        "timeout_sec": timeout_sec,
        "blocking_reasons": blocking,
        "no_op_release_conditions": list(TEXT_SEND_NO_OP_RELEASE_CONDITIONS),
    }


def _linux_ctrl_shift_u_sequence(codepoint: str) -> list[dict[str, Any]]:
    taps: list[dict[str, Any]] = [
        {"type": "tap", "key": "KC_U", "modifiers": ["KC_LCTRL", "KC_LSHIFT"]},
    ]
    taps.extend({"type": "tap", "key": _HEX_KEYCODES[ch]} for ch in codepoint.upper())
    taps.append({"type": "tap", "key": "KC_ENTER"})
    return taps


def _unicode_tap_sequence(mode: str, codepoint: str) -> tuple[list[dict[str, Any]], list[str]]:
    if mode == "linux_ctrl_shift_u":
        return _linux_ctrl_shift_u_sequence(codepoint), []
    if mode == "windows_ime_hex_f5":
        taps = [{"type": "tap", "key": _HEX_KEYCODES[ch]} for ch in codepoint.upper()]
        taps.extend([
            {"type": "tap", "key": "KC_F5"},
            {"type": "tap", "key": "KC_ENTER"},
        ])
        return taps, []
    return [], [f"unicode_mode_{mode}_dry_run_not_defined"]


def build_text_send_tap_dry_run(action: object, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the keyboard tap sequence inspected before runner execution."""
    settings = settings or {}
    unicode_settings = settings.get("unicode") if isinstance(settings.get("unicode"), dict) else {}
    mode = normalize_unicode_mode(unicode_settings.get("mode"))
    host_profile = explicit_text_send_host_profile(settings)
    status = classify_text_send_action(
        action,
        unicode_mode=mode,
        require_explicit_host_profile=True,
        host_profile_explicit=bool(host_profile["explicit"]),
    ).to_dict()
    sequences: list[dict[str, Any]] = []
    blocking: list[str] = []

    if status["family"] == "unicode":
        taps, errors = _unicode_tap_sequence(mode, status.get("codepoint") or "")
        blocking.extend(errors)
        if taps:
            sequences.append({"source": status["normalized"], "codepoint": status.get("codepoint"), "taps": taps})
    elif status["family"] == "send_string":
        entry = get_send_string_entry(settings, status.get("name"))
        entry_status = validate_send_string_entry(status.get("name"), entry)
        if not entry_status["valid"] or not entry_status["enabled"] or entry_status["confirm"]:
            blocking.append("send_string_entry_not_dry_runnable")
        text = entry if isinstance(entry, str) else entry.get("text") if isinstance(entry, dict) else ""
        if isinstance(text, str) and not blocking:
            for index, ch in enumerate(text):
                if ch == "\n":
                    blocking.append("newline_requires_key_action")
                    continue
                codepoint = f"{ord(ch):04X}"
                taps, errors = _unicode_tap_sequence(mode, codepoint)
                blocking.extend(errors)
                if taps:
                    sequences.append({"source": status["normalized"], "index": index, "codepoint": codepoint, "taps": taps})
    else:
        blocking.append("unsupported_text_send_action")

    if mode == DEFAULT_UNICODE_MODE:
        blocking.append("unicode_mode_none")
    blocking = list(dict.fromkeys(blocking))
    return {
        "schema": TEXT_SEND_TAP_DRY_RUN_SCHEMA,
        "read_only": True,
        "sends_hid_reports": False,
        "action": status,
        "unicode_mode": mode,
        "available": not blocking,
        "blocking_reasons": blocking,
        "sequence_count": len(sequences),
        "sequences": sequences,
        "notes": [
            "Dry-run only; no keyboard report is emitted.",
            "Newline is represented as a key action outside Unicode text dry-run.",
        ],
    }


def classify_text_send_action(
    action: object,
    *,
    unicode_mode: object = DEFAULT_UNICODE_MODE,
    require_explicit_host_profile: bool = False,
    host_profile_explicit: bool = False,
) -> TextSendActionStatus:
    raw = str(action or "").strip()
    mode = normalize_unicode_mode(unicode_mode)
    if not raw:
        return TextSendActionStatus("", "empty", False, False, "empty action")

    unicode_match = _UNICODE_RE.fullmatch(raw)
    if unicode_match:
        codepoint = unicode_match.group(1).upper()
        executable = mode != "none" and (not require_explicit_host_profile or host_profile_explicit)
        if executable:
            warning = ""
        elif mode == "none":
            warning = "unicode mode is none; action is preview/no-op"
        else:
            warning = "explicit host profile is required; action is preview/no-op"
        return TextSendActionStatus(
            raw,
            "unicode",
            True,
            executable,
            warning,
            normalized=f"U+{codepoint}",
            codepoint=codepoint,
        )

    send_match = _SEND_STRING_RE.fullmatch(raw)
    if send_match:
        family, name = send_match.groups()
        normalized = f"SEND_STRING({name})"
        return TextSendActionStatus(
            raw,
            "send_string",
            True,
            False,
            "named Send String storage is design-only; action is preview/no-op",
            normalized=normalized,
            name=name,
        )

    mode_match = _UC_MODE_RE.fullmatch(raw)
    if mode_match:
        requested = normalize_unicode_mode(mode_match.group(1))
        supported = requested == mode_match.group(1).strip().lower()
        return TextSendActionStatus(
            raw,
            "unicode_mode",
            supported,
            False,
            "UC_MODE is runtime-only and is not persisted",
            normalized=f"UC_MODE({requested})" if supported else None,
            name=requested if supported else None,
        )

    return TextSendActionStatus(raw, "other", False, False, "not a text-send action")


def text_send_execution_gate(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings or {}
    unicode_settings = settings.get("unicode") if isinstance(settings.get("unicode"), dict) else {}
    mode = normalize_unicode_mode(unicode_settings.get("mode"))
    host_profile = explicit_text_send_host_profile(settings)
    runner = text_send_runner_connection(settings)
    mode_ready = mode != DEFAULT_UNICODE_MODE
    host_ready = bool(host_profile["explicit"])
    unicode_ready = mode_ready and host_ready
    blocking: list[str] = []
    if not host_ready:
        blocking.append("explicit_host_profile_required")
    if not mode_ready:
        blocking.append("unicode_mode_none")
    blocking.extend(runner["blocking_reasons"])
    blocking = list(dict.fromkeys(blocking))
    return {
        "real_send_allowed": unicode_ready and runner["ready"],
        "unicode_actions_executable": unicode_ready,
        "send_string_runner_connected": runner["connected"],
        "send_string_runner_ready": runner["ready"],
        "send_string_actions_executable": unicode_ready and runner["ready"],
        "blocking_reasons": blocking,
        "no_op_release_conditions": list(TEXT_SEND_NO_OP_RELEASE_CONDITIONS),
        "cancel_required_before_real_send": list(TEXT_SEND_CANCEL_TRIGGERS),
    }


def build_text_send_real_send_plan(action: object, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the smallest allowed real-send step plan without executing it."""
    settings = settings or {}
    unicode_settings = settings.get("unicode") if isinstance(settings.get("unicode"), dict) else {}
    mode = normalize_unicode_mode(unicode_settings.get("mode"))
    host_profile = explicit_text_send_host_profile(settings)
    status = classify_text_send_action(
        action,
        unicode_mode=mode,
        require_explicit_host_profile=True,
        host_profile_explicit=bool(host_profile["explicit"]),
    ).to_dict()
    gate = text_send_execution_gate(settings)
    blocking = list(gate["blocking_reasons"])
    steps: list[dict[str, Any]] = []

    family = status["family"]
    allowed_family = family in {"unicode", "send_string"}
    if not allowed_family:
        blocking.append("unsupported_text_send_action")

    entry_status: dict[str, Any] | None = None
    if family == "send_string":
        entry = get_send_string_entry(settings, status.get("name"))
        entry_status = validate_send_string_entry(status.get("name"), entry)
        if entry is None:
            blocking.append("send_string_entry_missing")
        if not entry_status["valid"]:
            blocking.append("send_string_entry_invalid")
        if not entry_status["enabled"]:
            blocking.append("send_string_entry_disabled")
        if entry_status["confirm"]:
            blocking.append("send_string_entry_requires_confirmation")
        steps.append({"type": "resolve_named_text", "name": status.get("name")})

    if family == "unicode":
        steps.append({"type": "unicode_mode_sequence", "mode": mode, "codepoint": status.get("codepoint")})

    steps.extend(
        [
            {"type": "begin_runtime_state", "timeout_sec": DEFAULT_TEXT_SEND_RUNNER_TIMEOUT_SEC},
            {"type": "emit_keyboard_taps_only"},
            {"type": "finish_or_cancel", "cancel_triggers": list(TEXT_SEND_CANCEL_TRIGGERS)},
            {"type": "zero_report_on_cancel"},
        ]
    )

    # Keep order stable while preserving first occurrence.
    blocking = list(dict.fromkeys(blocking))
    return {
        "schema": "text_send.real_send_plan.v1",
        "read_only": True,
        "action": status,
        "entry": entry_status,
        "tap_dry_run": build_text_send_tap_dry_run(action, settings) if allowed_family else None,
        "real_send_allowed": allowed_family and not blocking,
        "blocking_reasons": blocking,
        "step_scope": list(TEXT_SEND_REAL_SEND_STEP_SCOPE),
        "forbidden_steps": list(TEXT_SEND_FORBIDDEN_REAL_SEND_STEPS),
        "steps": steps,
        "notes": [
            "This plan is metadata only; it does not send HID reports.",
            "Real send must use keyboard tap reports only and share the cancel/zero-report path.",
            "Newline remains a key action such as KC_ENTER, not a Unicode code point.",
        ],
    }


def text_send_safety_policy(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings or {}
    unicode_settings = settings.get("unicode") if isinstance(settings.get("unicode"), dict) else {}
    mode = normalize_unicode_mode(unicode_settings.get("mode"))
    host_profile = explicit_text_send_host_profile(settings)
    execution_gate = text_send_execution_gate(settings)
    examples = [
        classify_text_send_action(
            "U+3042",
            unicode_mode=mode,
            require_explicit_host_profile=True,
            host_profile_explicit=bool(host_profile["explicit"]),
        ).to_dict(),
        classify_text_send_action(
            "SEND_STRING(kana_a)",
            unicode_mode=mode,
            require_explicit_host_profile=True,
            host_profile_explicit=bool(host_profile["explicit"]),
        ).to_dict(),
        classify_text_send_action(
            "TEXT(kana_a)",
            unicode_mode=mode,
            require_explicit_host_profile=True,
            host_profile_explicit=bool(host_profile["explicit"]),
        ).to_dict(),
        classify_text_send_action(
            "UC_MODE(linux_ctrl_shift_u)",
            unicode_mode=mode,
            require_explicit_host_profile=True,
            host_profile_explicit=bool(host_profile["explicit"]),
        ).to_dict(),
    ]
    return {
        "schema": "text_send.safety.v2",
        "read_only": True,
        "unicode": {
            "mode": mode,
            "default_mode": DEFAULT_UNICODE_MODE,
            "supported_modes": list(SUPPORTED_UNICODE_MODES),
            "auto_os_detection": False,
        },
        "host_profile": host_profile,
        "execution_gate": execution_gate,
        "runner_connection": text_send_runner_connection(settings),
        "send_string": {
            "storage_owner": "settings.send_strings",
            "named_entries_only": True,
            "direct_text_in_keymap": False,
            "default_executable": False,
            "max_length": DEFAULT_SEND_STRING_MAX_LENGTH,
            "newline_requires_allow_newline": True,
            "control_characters_allowed": False,
            "zero_width_warning": True,
        },
        "real_send_step": {
            "schema": "text_send.real_send_plan.v1",
            "read_only": True,
            "minimal_scope": list(TEXT_SEND_REAL_SEND_STEP_SCOPE),
            "forbidden_steps": list(TEXT_SEND_FORBIDDEN_REAL_SEND_STEPS),
            "example": build_text_send_real_send_plan("TEXT(kana_a)", settings),
        },
        "tap_dry_run": {
            "schema": TEXT_SEND_TAP_DRY_RUN_SCHEMA,
            "read_only": True,
            "sends_hid_reports": False,
            "supported_modes": list(TEXT_SEND_TAP_DRY_RUN_SUPPORTED_MODES),
            "unsupported_modes": [
                item for item in SUPPORTED_UNICODE_MODES
                if item not in TEXT_SEND_TAP_DRY_RUN_SUPPORTED_MODES and item != DEFAULT_UNICODE_MODE
            ],
            "example": build_text_send_tap_dry_run("U+3042", settings),
        },
        "send_string_validation": validate_send_string_settings(settings),
        "cancel_triggers": list(TEXT_SEND_CANCEL_TRIGGERS),
        "http_warning": {
            "required": bool(execution_gate["blocking_reasons"]),
            "scope": list(TEXT_SEND_HTTP_WARNING_SCOPE),
            "blocking_reasons": list(execution_gate["blocking_reasons"]),
            "message": "Text send remains preview/no-op until host profile, mode, runner, and cancel path are ready",
        },
        "warnings": [
            "host IME / layout is not auto-detected",
            "explicit host profile is required before real text send",
            "unicode mode none makes Unicode actions preview/no-op",
            "named Send String execution requires an explicitly connected runner",
            "Vial raw macro buffer is not Send String storage",
            "secret / password text is out of scope",
        ],
        "examples": examples,
    }
