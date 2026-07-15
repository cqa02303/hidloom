"""Read-only KML / QMK macro integration groundwork helpers."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from hidloom_paths import default_config_dir

MACRO_LOOKUP_SCHEMA = "macro_integration.lookup.v1"
MACRO_RUNNER_PLAN_SCHEMA = "macro_integration.runner_plan.v1"
VIAL_MACRO_BOUNDARY_SCHEMA = "vial_macro.boundary.v1"

MACRO_KINDS = {
    "kml": {
        "action": "KML",
        "extension": ".kml",
        "runtime_dir": "kml",
        "factory_dir": "kml",
    },
    "qmk": {
        "action": "QMK_MACRO",
        "extension": ".qmk",
        "runtime_dir": "qmk",
        "factory_dir": "qmk",
    },
}
_ACTION_RE = re.compile(r"^(KML|QMK_MACRO)\(([A-Za-z0-9_.-]{1,64})\)$")
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_KC_RE = r"KC_[A-Z0-9_]+"
_QMK_COMMAND_RE = re.compile(
    rf'^(SEND_STRING\("[^"\r\n]{{0,256}}"\)|TAP_CODE\({_KC_RE}\)|TAP_CODE16\((TO|MO|TG|DF)\([0-9]{{1,2}}\)\)|REGISTER_CODE\({_KC_RE}\)|UNREGISTER_CODE\({_KC_RE}\)|WAIT_MS\([0-9]{{1,5}}\))$'
)
_KML_COMMAND_RE = re.compile(
    rf"^(tap {_KC_RE}|down {_KC_RE}|up {_KC_RE}|delay [0-9]{{1,5}}|text [^\r\n]{{1,256}})$",
    re.IGNORECASE,
)
_FORBIDDEN_TOKENS = (
    "SCRIPT(",
    "KC_SHUTDOWN",
    "QK_BOOT",
    "RESET",
    "BT_POWER_",
    "BT_FORGET",
    "WIFI_POWER_",
    "POWER_OFF",
    "REBOOT",
    "SHUTDOWN",
    "system(",
    "shell(",
    "subprocess",
    "#include",
    "while(",
    "for(",
)


@dataclass(frozen=True)
class MacroAction:
    kind: str
    name: str


def parse_macro_runner_action(action: str) -> MacroAction | None:
    """Parse supported first-slice macro runner actions."""
    if not isinstance(action, str):
        return None
    match = _ACTION_RE.fullmatch(action)
    if not match:
        return None
    action_name, name = match.groups()
    kind = "kml" if action_name == "KML" else "qmk"
    return MacroAction(kind=kind, name=name)


def validate_macro_name(name: str) -> dict[str, Any]:
    """Return read-only validation metadata for a macro file name."""
    valid = isinstance(name, str) and bool(_NAME_RE.fullmatch(name))
    return {"valid": valid, "reason": None if valid else "invalid_macro_name"}


def macro_lookup_candidates(
    kind: str,
    name: str,
    *,
    runtime_root: Path | str = Path("/mnt/p3/macros"),
    factory_root: Path | str | None = None,
) -> tuple[Path, Path]:
    """Return the supported runtime/factory lookup candidates."""
    if kind not in MACRO_KINDS:
        raise ValueError(f"unsupported macro kind: {kind}")
    name_validation = validate_macro_name(name)
    if not name_validation["valid"]:
        raise ValueError("invalid macro name")
    if factory_root is None:
        factory_root = default_config_dir() / "macros"
    spec = MACRO_KINDS[kind]
    filename = name + spec["extension"]
    runtime = Path(runtime_root) / spec["runtime_dir"] / filename
    factory = Path(factory_root) / spec["factory_dir"] / filename
    return runtime, factory


def resolve_macro_file(
    kind: str,
    name: str,
    *,
    runtime_root: Path | str = Path("/mnt/p3/macros"),
    factory_root: Path | str | None = None,
) -> dict[str, Any]:
    """Resolve a named macro without reading legacy paths."""
    try:
        candidates = macro_lookup_candidates(
            kind,
            name,
            runtime_root=runtime_root,
            factory_root=factory_root,
        )
    except ValueError as exc:
        return {
            "schema": MACRO_LOOKUP_SCHEMA,
            "kind": kind,
            "name": name,
            "found": False,
            "path": None,
            "source": None,
            "searched": (),
            "legacy_paths_read": False,
            "error": str(exc),
        }
    for source, candidate in zip(("runtime", "factory"), candidates):
        if candidate.is_file():
            return {
                "schema": MACRO_LOOKUP_SCHEMA,
                "kind": kind,
                "name": name,
                "found": True,
                "path": str(candidate),
                "source": source,
                "searched": tuple(str(path) for path in candidates),
                "legacy_paths_read": False,
                "error": None,
            }
    return {
        "schema": MACRO_LOOKUP_SCHEMA,
        "kind": kind,
        "name": name,
        "found": False,
        "path": None,
        "source": None,
        "searched": tuple(str(path) for path in candidates),
        "legacy_paths_read": False,
        "error": "macro_file_not_found",
    }


def validate_macro_text(kind: str, text: str) -> dict[str, Any]:
    """Validate the first read-only syntax subset for a KML or QMK macro."""
    errors: list[str] = []
    warnings: list[str] = []
    if kind not in MACRO_KINDS:
        errors.append("unsupported_macro_kind")
    if not isinstance(text, str):
        errors.append("macro_text_must_be_string")
        text = ""
    if any(token in text for token in _FORBIDDEN_TOKENS):
        errors.append("forbidden_action_or_code")
    commands = _logical_lines(text)
    if not commands:
        errors.append("macro_empty")
    command_re = _KML_COMMAND_RE if kind == "kml" else _QMK_COMMAND_RE
    for command in commands:
        if command.startswith("//") or command.startswith("#"):
            warnings.append("comment_ignored")
            continue
        if not command_re.fullmatch(command):
            errors.append(f"unsupported_command:{command}")
    return {
        "kind": kind,
        "valid": not errors,
        "commands": tuple(commands),
        "errors": tuple(errors),
        "warnings": tuple(warnings),
        "sends_hid_reports": False,
    }


def build_macro_runner_plan(
    action: str,
    *,
    runtime_root: Path | str = Path("/mnt/p3/macros"),
    factory_root: Path | str | None = None,
) -> dict[str, Any]:
    """Build a read-only runner preflight plan for KML(name) / QMK_MACRO(name)."""
    parsed = parse_macro_runner_action(action)
    if parsed is None:
        return _blocked_plan(action, "unsupported_macro_action")
    lookup = resolve_macro_file(
        parsed.kind,
        parsed.name,
        runtime_root=runtime_root,
        factory_root=factory_root,
    )
    if not lookup["found"]:
        return _blocked_plan(action, lookup["error"] or "macro_file_not_found", parsed=parsed, lookup=lookup)
    try:
        text = Path(lookup["path"]).read_text(encoding="utf-8")
    except OSError as exc:
        return _blocked_plan(action, f"macro_file_read_failed:{exc}", parsed=parsed, lookup=lookup)
    validation = validate_macro_text(parsed.kind, text)
    blocking = list(validation["errors"])
    return {
        "schema": MACRO_RUNNER_PLAN_SCHEMA,
        "action": action,
        "kind": parsed.kind,
        "name": parsed.name,
        "lookup": lookup,
        "validation": validation,
        "dry_run": True,
        "real_run_allowed": False,
        "sends_hid_reports": False,
        "uses_logicd_output_path": True,
        "direct_key_events_sock_write": False,
        "vial_macro_buffer_source": False,
        "fixed_slot_keycode_added": False,
        "blocking_reasons": tuple(blocking),
    }


def vial_macro_boundary(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Summarize Vial raw-buffer vs local macro ownership."""
    raw = settings if isinstance(settings, dict) else {}
    settings_obj = raw.get("settings", raw)
    if not isinstance(settings_obj, dict):
        settings_obj = {}
    macros = raw.get("macros", {})
    if not isinstance(macros, dict):
        macros = {}
    raw_buffer = settings_obj.get("vial_macro_buffer")
    return {
        "schema": VIAL_MACRO_BOUNDARY_SCHEMA,
        "raw_buffer_present": isinstance(raw_buffer, str) and bool(raw_buffer),
        "expanded_macro_count": len(macros),
        "raw_buffer_executable": False,
        "runtime_source": "expanded_local_macros",
        "import_export_source": "settings.vial_macro_buffer",
        "auto_converts_system_actions": False,
    }


def _logical_lines(text: str) -> list[str]:
    commands: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        commands.extend(part.strip() for part in line.split(";") if part.strip())
    return commands


def _blocked_plan(
    action: str,
    reason: str,
    *,
    parsed: MacroAction | None = None,
    lookup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": MACRO_RUNNER_PLAN_SCHEMA,
        "action": action,
        "kind": None if parsed is None else parsed.kind,
        "name": None if parsed is None else parsed.name,
        "lookup": lookup,
        "validation": None,
        "dry_run": True,
        "real_run_allowed": False,
        "sends_hid_reports": False,
        "uses_logicd_output_path": True,
        "direct_key_events_sock_write": False,
        "vial_macro_buffer_source": False,
        "fixed_slot_keycode_added": False,
        "blocking_reasons": (reason,),
    }
