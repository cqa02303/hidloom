"""Script file discovery and runtime script writes for the HTTP UI."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict

_HERE = Path(__file__).parent
_REPO_ROOT = _HERE.parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hidloom_paths import default_config_dir, default_config_file, runtime_script_dir as default_runtime_script_dir
from script_metadata import analyze_script_safety

CONFIG_JSON = default_config_file("config.json")
KEYCODES_JSON = default_config_file("keycodes.json")
DEFAULT_SCRIPT_DIR = default_runtime_script_dir()
FALLBACK_SCRIPT_DIR = default_config_dir() / "script"

log = logging.getLogger("httpd")


def configure_paths(config_json: Path, default_script_dir: Path, fallback_script_dir: Path) -> None:
    """Update path dependencies supplied by the HTTP app wiring layer.

    ``httpd.py`` owns the app-level path wiring, while this module owns script
    discovery and persistence.  Keep the mutable path update here so callers do
    not reach into this module's globals directly.
    """

    global CONFIG_JSON, DEFAULT_SCRIPT_DIR, FALLBACK_SCRIPT_DIR
    CONFIG_JSON = config_json
    DEFAULT_SCRIPT_DIR = default_script_dir
    FALLBACK_SCRIPT_DIR = fallback_script_dir


def script_dirs() -> list[Path]:
    script_dirs: list[Path] = []
    try:
        cfg = json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
        configured_dir = cfg.get("settings", {}).get("script_dir")
        if configured_dir:
            script_dirs.append(Path(configured_dir))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("Cannot load config.json for script labels: %s", e)
    for path in (DEFAULT_SCRIPT_DIR, FALLBACK_SCRIPT_DIR):
        if path not in script_dirs:
            script_dirs.append(path)
    return script_dirs


def runtime_script_dir() -> Path:
    try:
        cfg = json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
        configured_dir = cfg.get("settings", {}).get("script_dir")
        if configured_dir:
            return Path(configured_dir)
    except (OSError, json.JSONDecodeError):
        pass
    return DEFAULT_SCRIPT_DIR


def _script_number(keycode: str) -> int:
    match = re.fullmatch(r"KC_SH(\d+)", keycode or "")
    if not match:
        raise ValueError("invalid keycode")
    return int(match.group(1))


def script_keycodes() -> list[str]:
    try:
        keycodes = json.loads(KEYCODES_JSON.read_text(encoding="utf-8"))
        names = [
            name for name in keycodes
            if isinstance(name, str) and re.fullmatch(r"KC_SH\d+", name)
        ]
        if names:
            return sorted(names, key=_script_number)
    except (OSError, json.JSONDecodeError) as e:
        log.warning("Cannot load keycodes.json for script keycodes: %s", e)
    return [f"KC_SH{i}" for i in range(11)]


def valid_script_keycode(keycode: str) -> bool:
    return bool(re.fullmatch(r"KC_SH\d+", keycode or "")) and keycode in set(script_keycodes())


def _read_script_text(script_path: Path) -> str:
    try:
        return script_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def script_label(script_path: Path) -> str:
    for line in _read_script_text(script_path).splitlines():
        match = re.match(r"^\s*#\s*@label\s+(.+?)\s*$", line)
        if match:
            return match.group(1)
    return ""


def script_safety_for_content(content: str) -> Dict[str, Any]:
    return analyze_script_safety(content).as_dict()


def script_safety(script_path: Path) -> Dict[str, Any]:
    return script_safety_for_content(_read_script_text(script_path))


def iter_script_entries() -> list[Dict[str, Any]]:
    return [script_entry(keycode) for keycode in script_keycodes()]


def script_entry(keycode: str) -> Dict[str, Any]:
    if not valid_script_keycode(keycode):
        raise ValueError("invalid keycode")
    runtime_dir = runtime_script_dir()
    filename = f"{keycode}.sh"
    for script_dir in script_dirs():
        script_path = script_dir / filename
        if not script_path.exists():
            continue
        content = _read_script_text(script_path)
        return {
            "keycode": keycode,
            "filename": filename,
            "label": script_label(script_path),
            "path": str(script_path),
            "source": "runtime" if script_dir == runtime_dir else "fallback",
            "exists": True,
            "safety": script_safety_for_content(content),
        }
    path = runtime_script_path(keycode)
    return {
        "keycode": keycode,
        "filename": filename,
        "label": "",
        "path": str(path),
        "source": "missing",
        "exists": False,
        "safety": script_safety_for_content(default_script_content(keycode)),
    }


def default_script_content(keycode: str) -> str:
    if not valid_script_keycode(keycode):
        raise ValueError("invalid keycode")
    return (
        "#!/bin/bash\n"
        "# @label (コマンド説明)\n"
        "\n"
        "set -euo pipefail\n"
        "\n"
        'hidloom-notify alert "message" 2\n'
    )


def load_script_label_overrides() -> Dict[str, str]:
    labels: Dict[str, str] = {}
    for entry in iter_script_entries():
        label = entry.get("label")
        if isinstance(label, str) and label:
            labels[str(entry["keycode"])] = label
    return labels


def runtime_script_path(keycode: str) -> Path:
    if not valid_script_keycode(keycode):
        raise ValueError("invalid keycode")
    return runtime_script_dir() / f"{keycode}.sh"


def fallback_script_path(keycode: str) -> Path:
    if not valid_script_keycode(keycode):
        raise ValueError("invalid keycode")
    return FALLBACK_SCRIPT_DIR / f"{keycode}.sh"


def write_runtime_script(keycode: str, content: str) -> Path:
    path = runtime_script_path(keycode)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    os.chmod(path, 0o755)
    return path


def delete_runtime_script(keycode: str) -> bool:
    path = runtime_script_path(keycode)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
