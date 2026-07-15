#!/usr/bin/env python3
"""Apply or inspect a board wiring profile.

Board profile selection is intentionally conservative:

* Missing marker file falls back to ver1.0.
* ver0.1 is prototype hardware and requires --prototype for writes.
* Runtime keymap reset is explicit because /mnt/p3/keymap.json overrides config/default/keymap.json.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hidloom_paths import board_profiles_dir, default_config_dir, runtime_file  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BOARDS_DIR = board_profiles_dir(ROOT)
DEFAULT_BOARD_VERSION = "ver1.0"
PROTOTYPE_BOARD_VERSION = "ver0.1"
DEFAULT_MARKER_PATH = runtime_file("board_profile.json")
DEFAULT_RUNTIME_KEYMAP_PATH = runtime_file("keymap.json")

PROFILE_CONF_FILES = (
    "matrixd.json",
    "keymap.json",
    "keyboard-layout.json",
    "vial.json",
    "ledd.json",
    "i2cd.json",
)

RESTART_SERVICES = (
    "matrixd",
    "logicd",
    "ledd",
    "i2cd",
    "viald",
    "httpd",
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _board_dir(version: str) -> Path:
    path = BOARDS_DIR / version
    if not path.is_dir():
        raise SystemExit(f"unknown board profile: {version}")
    return path


def _manifest(version: str) -> dict[str, Any]:
    path = _board_dir(version) / "board.json"
    if not path.exists():
        raise SystemExit(f"missing board manifest: {path}")
    data = _load_json(path)
    if data.get("board_version") != version:
        raise SystemExit(f"board manifest version mismatch: {path}")
    return data


def _validate_profile_files(version: str) -> None:
    conf_dir = _board_dir(version) / "conf"
    missing = [name for name in PROFILE_CONF_FILES if not (conf_dir / name).exists()]
    if missing:
        raise SystemExit(f"board profile {version} is missing conf files: {', '.join(missing)}")


def read_active_marker(marker_path: Path) -> tuple[str, str, dict[str, Any]]:
    if not marker_path.exists():
        return DEFAULT_BOARD_VERSION, "fallback", {}
    data = _load_json(marker_path)
    version = data.get("board_version")
    if not isinstance(version, str) or not version:
        raise SystemExit(f"invalid board marker: {marker_path}")
    _manifest(version)
    return version, "marker", data


def apply_repo_conf(version: str) -> None:
    _validate_profile_files(version)
    src_dir = _board_dir(version) / "conf"
    dst_dir = default_config_dir(ROOT)
    for name in PROFILE_CONF_FILES:
        shutil.copy2(src_dir / name, dst_dir / name)
        print(f"copied {src_dir / name} -> {dst_dir / name}")


def write_marker(version: str, marker_path: Path, device_name: str | None, prototype_ok: bool) -> None:
    manifest = _manifest(version)
    if version == PROTOTYPE_BOARD_VERSION and not prototype_ok:
        raise SystemExit("ver0.1 is prototype hardware; rerun with --prototype to select it")
    data: dict[str, Any] = {
        "board_version": version,
        "prototype": bool(manifest.get("prototype", False)),
        "selected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "selected_by": "script/apply_board_profile.py",
    }
    if device_name:
        data["device_name"] = device_name
    _atomic_write_json(marker_path, data)
    print(f"wrote {marker_path}: {version}")


def reset_runtime_keymap(path: Path) -> None:
    if not path.exists():
        print(f"runtime keymap is already absent: {path}")
        return
    backup = path.with_name(f"{path.name}.bak.{time.strftime('%Y%m%d%H%M%S', time.gmtime())}")
    shutil.move(str(path), str(backup))
    print(f"moved runtime keymap {path} -> {backup}")


def restart_services() -> None:
    cmd = ["systemctl", "restart", *RESTART_SERVICES]
    print("running:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def list_profiles() -> None:
    for path in sorted(BOARDS_DIR.iterdir()):
        if not path.is_dir():
            continue
        manifest = _manifest(path.name)
        marker = " default" if manifest.get("default") else ""
        prototype = " prototype" if manifest.get("prototype") else ""
        print(f"{path.name}:{marker}{prototype} - {manifest.get('title', '')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply or inspect HIDloom board profiles")
    parser.add_argument("board_version", nargs="?", help="board profile version, for example ver1.0")
    parser.add_argument("--status", action="store_true", help="print active marker or fallback")
    parser.add_argument("--list", action="store_true", help="list available board profiles")
    parser.add_argument("--repo-conf", action="store_true", help="copy config/boards/<version>/conf files into config/default/")
    parser.add_argument("--write-marker", action="store_true", help="write /mnt/p3/board_profile.json")
    parser.add_argument("--marker-path", type=Path, default=DEFAULT_MARKER_PATH)
    parser.add_argument("--device-name", help="device name to record in the marker")
    parser.add_argument("--prototype", action="store_true", help="allow selecting prototype ver0.1")
    parser.add_argument("--reset-runtime-keymap", action="store_true", help="backup and remove /mnt/p3/keymap.json")
    parser.add_argument("--runtime-keymap-path", type=Path, default=DEFAULT_RUNTIME_KEYMAP_PATH)
    parser.add_argument("--restart-services", action="store_true", help="restart services that read board config")
    args = parser.parse_args()

    if args.list:
        list_profiles()

    if args.status:
        version, source, data = read_active_marker(args.marker_path)
        print(json.dumps({"board_version": version, "source": source, "marker": data}, ensure_ascii=False))

    if args.list or args.status:
        if not args.board_version and not args.repo_conf and not args.write_marker and not args.reset_runtime_keymap and not args.restart_services:
            return

    version = args.board_version or DEFAULT_BOARD_VERSION
    _manifest(version)
    _validate_profile_files(version)

    if version == PROTOTYPE_BOARD_VERSION and (args.repo_conf or args.write_marker) and not args.prototype:
        raise SystemExit("ver0.1 is prototype hardware; rerun with --prototype to select it")

    if args.repo_conf:
        apply_repo_conf(version)
    if args.write_marker:
        write_marker(version, args.marker_path, args.device_name, args.prototype)
    if args.reset_runtime_keymap:
        reset_runtime_keymap(args.runtime_keymap_path)
    if args.restart_services:
        restart_services()


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(f"command failed: {exc}", file=sys.stderr)
        raise SystemExit(exc.returncode)
