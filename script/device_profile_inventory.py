#!/usr/bin/env python3
"""List and validate device profile metadata without changing runtime state."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "config" / "device-profiles"
SCHEMA = "cqa02303v5.device-profile.v1"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _required_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{key} must be a list of non-empty strings")
    return value


def _validate_profile(path: Path) -> dict[str, Any]:
    data = _load_json(path)
    profile_id = data.get("id")
    if data.get("schema") != SCHEMA:
        raise ValueError(f"{path}: unsupported schema")
    if not isinstance(profile_id, str) or not profile_id:
        raise ValueError(f"{path}: missing id")
    if path.stem != profile_id:
        raise ValueError(f"{path}: file name must match id")
    if data.get("kind") not in {"keyboard", "touch-panel"}:
        raise ValueError(f"{path}: unsupported kind")

    runtime_files = data.get("runtime_files")
    if not isinstance(runtime_files, dict) or not runtime_files:
        raise ValueError(f"{path}: runtime_files must be a non-empty object")
    for dest, rel in runtime_files.items():
        if not isinstance(dest, str) or "/" in dest or not dest.endswith(".json"):
            raise ValueError(f"{path}: invalid runtime file destination {dest!r}")
        src = ROOT / str(rel)
        if not src.is_file():
            raise ValueError(f"{path}: missing runtime source {rel}")

    config_files = data.get("config_files", {})
    if not isinstance(config_files, dict):
        raise ValueError(f"{path}: config_files must be an object")
    for dest, rel in config_files.items():
        if not isinstance(dest, str) or "/" in dest or not dest.endswith(".json"):
            raise ValueError(f"{path}: invalid config file destination {dest!r}")
        src = ROOT / str(rel)
        if not src.is_file():
            raise ValueError(f"{path}: missing config source {rel}")

    services = data.get("services")
    if not isinstance(services, dict):
        raise ValueError(f"{path}: services must be an object")
    enable = _required_list(services, "enable")
    disable = _required_list(services, "disable")
    overlap = set(enable) & set(disable)
    if overlap:
        raise ValueError(f"{path}: services listed as both enable and disable: {sorted(overlap)}")

    return data


def load_profiles(profile_dir: Path = PROFILE_DIR) -> list[dict[str, Any]]:
    profiles = [_validate_profile(path) for path in sorted(profile_dir.glob("*.json"))]
    ids = [str(profile["id"]) for profile in profiles]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate device profile id")
    return profiles


def main() -> None:
    parser = argparse.ArgumentParser(description="List HIDloom device profiles")
    parser.add_argument("--json", action="store_true", help="print full JSON inventory")
    parser.add_argument("--profile-dir", type=Path, default=PROFILE_DIR)
    args = parser.parse_args()

    try:
        profiles = load_profiles(args.profile_dir)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)

    if args.json:
        print(json.dumps({"profiles": profiles}, ensure_ascii=False, indent=2))
        return
    for profile in profiles:
        print(f"{profile['id']}\t{profile['kind']}\t{profile.get('label', '')}")


if __name__ == "__main__":
    main()
