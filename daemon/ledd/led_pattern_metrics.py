"""Read-only LED pattern editor / long-run metrics groundwork helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

LED_PATTERN_DRAFT_SCHEMA = "led_pattern_editor.draft.v1"
LED_PATTERN_PREVIEW_SCHEMA = "led_pattern_editor.preview_plan.v1"
LED_LONG_RUN_METRICS_SCHEMA = "led_long_run.metrics.v1"

PATTERN_KINDS = {"pattern", "splash", "reactive"}
PATTERN_NAMES = {"rainbow", "pulse", "solid", "gradient", "digital_rain"}
DEFAULT_BRIGHTNESS_CEILING = 128
HARD_BRIGHTNESS_CEILING = 192
DEFAULT_TIMEOUT_SEC = 30
HARD_TIMEOUT_SEC = 300


@dataclass(frozen=True)
class LedPatternDraft:
    name: str
    kind: str
    pattern: str
    brightness: int
    fps: int
    timeout_sec: int
    speed: int | None = None
    hue: int | None = None
    saturation: int | None = None
    value: int | None = None


def validate_led_pattern_draft(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Validate one pattern editor draft without touching LED configuration."""
    data = raw if isinstance(raw, dict) else {}
    errors: list[str] = []
    warnings: list[str] = []
    name = data.get("name", "draft")
    kind = data.get("kind")
    pattern = data.get("pattern")
    brightness = _int(data.get("brightness", 96), default=96)
    fps = _int(data.get("fps", 24), default=24)
    timeout_sec = _int(data.get("timeout_sec", DEFAULT_TIMEOUT_SEC), default=DEFAULT_TIMEOUT_SEC)

    if not isinstance(name, str) or not (1 <= len(name) <= 64):
        errors.append("invalid_draft_name")
        name = "draft"
    if kind not in PATTERN_KINDS:
        errors.append("invalid_pattern_kind")
        kind = "pattern"
    if pattern not in PATTERN_NAMES:
        errors.append("invalid_pattern_name")
        pattern = "solid"
    if not (1 <= brightness <= HARD_BRIGHTNESS_CEILING):
        errors.append("brightness_out_of_range")
        brightness = max(1, min(HARD_BRIGHTNESS_CEILING, brightness))
    elif brightness > DEFAULT_BRIGHTNESS_CEILING:
        warnings.append("brightness_requires_explicit_confirm")
    if not (1 <= fps <= 60):
        errors.append("fps_out_of_range")
        fps = max(1, min(60, fps))
    if not (1 <= timeout_sec <= HARD_TIMEOUT_SEC):
        errors.append("timeout_out_of_range")
        timeout_sec = max(1, min(HARD_TIMEOUT_SEC, timeout_sec))

    optional = {
        "speed": _optional_byte(data.get("speed"), "speed", errors),
        "hue": _optional_byte(data.get("hue"), "hue", errors),
        "saturation": _optional_byte(data.get("saturation"), "saturation", errors),
        "value": _optional_byte(data.get("value"), "value", errors),
    }
    draft = LedPatternDraft(
        name=name,
        kind=str(kind),
        pattern=str(pattern),
        brightness=brightness,
        fps=fps,
        timeout_sec=timeout_sec,
        **optional,
    )
    return {
        "schema": LED_PATTERN_DRAFT_SCHEMA,
        "valid": not errors,
        "draft": draft,
        "errors": tuple(errors),
        "warnings": tuple(warnings),
        "storage_owner": "/mnt/p3/led_pattern_editor.json",
        "writes_conf_ledd_json": False,
    }


def build_led_pattern_preview_plan(
    raw: dict[str, Any] | None,
    *,
    current_effect: dict[str, Any] | None = None,
    confirmed_brightness: bool = False,
) -> dict[str, Any]:
    """Return a side-effect-free preview plan for a pattern draft."""
    validation = validate_led_pattern_draft(raw)
    draft: LedPatternDraft = validation["draft"]
    blocking = list(validation["errors"])
    if "brightness_requires_explicit_confirm" in validation["warnings"] and not confirmed_brightness:
        blocking.append("brightness_confirmation_required")
    return {
        "schema": LED_PATTERN_PREVIEW_SCHEMA,
        "validation": validation,
        "preview_allowed": not blocking,
        "blocking_reasons": tuple(blocking),
        "save_current_effect_snapshot": True,
        "restore_on_timeout": True,
        "restore_on_disconnect": True,
        "restore_on_http_error": True,
        "restore_on_daemon_reload": True,
        "timeout_sec": draft.timeout_sec,
        "brightness_ceiling": DEFAULT_BRIGHTNESS_CEILING if not confirmed_brightness else HARD_BRIGHTNESS_CEILING,
        "hard_timeout_sec": HARD_TIMEOUT_SEC,
        "uses_direct_frame_preview_path": draft.kind == "pattern",
        "uses_vialrgb_preview_path": draft.kind in {"splash", "reactive"},
        "writes_conf_ledd_json": False,
        "current_effect_snapshot": current_effect or {},
    }


def summarize_long_run_metrics(
    samples: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    expected_fps: float,
    duration_sec: float,
) -> dict[str, Any]:
    """Summarize long-run direct-frame metrics from status samples."""
    if duration_sec <= 0:
        duration_sec = 1.0
    first = samples[0] if samples else {}
    last = samples[-1] if samples else {}
    accepted = _counter_delta(first, last, "accepted_frames")
    applied = _counter_delta(first, last, "applied_frames")
    rejected = _counter_delta(first, last, "rejected_frames")
    ignored = _counter_delta(first, last, "ignored_frames")
    bytes_received = _counter_delta(first, last, "bytes_received")
    dropped = max(0, accepted - applied)
    expected_frames = max(0, int(round(expected_fps * duration_sec)))
    warnings: list[str] = []
    if rejected:
        warnings.append("rejected_frames_present")
    if dropped:
        warnings.append("dropped_frames_present")
    if applied < expected_frames * 0.8:
        warnings.append("applied_fps_below_expected")
    return {
        "schema": LED_LONG_RUN_METRICS_SCHEMA,
        "sample_count": len(samples),
        "duration_sec": duration_sec,
        "expected_fps": float(expected_fps),
        "accepted_frames": accepted,
        "applied_frames": applied,
        "ignored_frames": ignored,
        "rejected_frames": rejected,
        "bytes_received": bytes_received,
        "accepted_fps": accepted / duration_sec,
        "applied_fps": applied / duration_sec,
        "dropped_frames": dropped,
        "last_error": last.get("last_error") or last.get("error") or None,
        "warnings": tuple(warnings),
        "requires_real_led_visual_check": True,
    }


def _int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_byte(value: Any, field: str, errors: list[str]) -> int | None:
    if value is None:
        return None
    number = _int(value, default=-1)
    if not (0 <= number <= 255):
        errors.append(f"{field}_out_of_range")
        return None
    return number


def _counter_delta(first: dict[str, Any], last: dict[str, Any], key: str) -> int:
    return max(0, _int(last.get(key, 0), default=0) - _int(first.get(key, 0), default=0))
