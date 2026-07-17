#!/usr/bin/env python3
"""Apply HIDloom device profile runtime files and service policy."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hidloom_paths import environment_value  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REPO_PROFILE_DIR = ROOT / "config" / "device-profiles"
INSTALLED_PROFILE_DIR = Path("/usr/share/hidloom/profiles")
RUNTIME_DIR = Path(environment_value("RUNTIME_DIR", "/mnt/p3"))
SYSTEMD_ETC_DIR = Path(environment_value("SYSTEMD_ETC_DIR", "/etc/systemd/system"))
SCHEMA = "cqa02303v5.device-profile.v1"
READY_SOCKET_TIMEOUT_SEC = 15.0
READY_SOCKET_POLL_SEC = 0.1


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def profile_locations(profile_dir: Path) -> list[tuple[str, Path, Path]]:
    locations: list[tuple[str, Path, Path]] = []
    if profile_dir == INSTALLED_PROFILE_DIR:
        for path in sorted(profile_dir.glob("*/profile.json")):
            locations.append((path.parent.name, path, path.parent))
    else:
        for path in sorted(profile_dir.glob("*.json")):
            locations.append((path.stem, path, ROOT))
        for path in sorted(profile_dir.glob("*/profile.json")):
            locations.append((path.parent.name, path, path.parent))
    return locations


def load_profiles(profile_dir: Path) -> dict[str, tuple[dict[str, Any], Path]]:
    profiles: dict[str, tuple[dict[str, Any], Path]] = {}
    for expected_id, path, base_dir in profile_locations(profile_dir):
        data = load_json(path)
        profile_id = data.get("id")
        if data.get("schema") != SCHEMA:
            raise SystemExit(f"invalid profile schema: {path}")
        if profile_id != expected_id:
            raise SystemExit(f"profile id mismatch: {path}: {profile_id!r} != {expected_id!r}")
        if not isinstance(profile_id, str) or not profile_id:
            raise SystemExit(f"invalid profile id: {path}")
        profiles[profile_id] = (data, base_dir)
    return profiles


def resolve_profile_dir(profile_dir: Path | None) -> Path:
    if profile_dir is not None:
        return profile_dir
    if INSTALLED_PROFILE_DIR.is_dir():
        return INSTALLED_PROFILE_DIR
    return REPO_PROFILE_DIR


def source_path(base_dir: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return base_dir / path


def backup_path(path: Path, timestamp: str) -> Path:
    return path.with_name(f"{path.name}.bak.{timestamp}")


def copy_file(src: Path, dst: Path, *, dry_run: bool, backup: bool, timestamp: str) -> None:
    if not src.exists():
        raise SystemExit(f"missing profile source file: {src}")
    if dry_run:
        if dst.exists() and backup:
            print(f"backup {dst} -> {backup_path(dst, timestamp)}")
        print(f"copy {src} -> {dst}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and backup:
        shutil.copy2(dst, backup_path(dst, timestamp))
    shutil.copy2(src, dst)
    os.chmod(dst, 0o644)
    print(f"copied {src} -> {dst}")


def remove_runtime_file(path: Path, *, dry_run: bool, backup: bool, timestamp: str) -> None:
    if not path.exists():
        return
    if dry_run:
        if backup:
            print(f"backup {path} -> {backup_path(path, timestamp)}")
        print(f"remove {path}")
        return
    if backup:
        shutil.copy2(path, backup_path(path, timestamp))
    path.unlink()
    print(f"removed {path}")


def render_dropin(unit: str, spec: dict[str, Any]) -> str:
    lines: list[str] = []
    for section in ("Unit", "Service"):
        values = spec.get(section)
        if not isinstance(values, dict) or not values:
            continue
        lines.append(f"[{section}]")
        for key, value in values.items():
            if section == "Service" and key == "Environment" and isinstance(value, dict):
                for env_key, env_value in value.items():
                    lines.append(f'Environment="{env_key}={env_value}"')
                continue
            if isinstance(value, list):
                lines.append(f"{key}=")
                if value:
                    lines.append(f"{key}={' '.join(str(item) for item in value)}")
                continue
            lines.append(f"{key}={value}")
        lines.append("")
    if not lines:
        legacy_env = {key: value for key, value in spec.items() if isinstance(value, (str, int, float, bool))}
        if legacy_env:
            lines.append("[Service]")
            for key, value in legacy_env.items():
                lines.append(f'Environment="{key}={value}"')
            lines.append("")
    if not lines:
        raise SystemExit(f"empty drop-in for {unit}")
    return "\n".join(lines).rstrip() + "\n"


def write_dropins(profile: dict[str, Any], *, dry_run: bool) -> None:
    dropins = profile.get("dropins", {})
    if not isinstance(dropins, dict):
        raise SystemExit("profile dropins must be an object")
    for unit, spec in dropins.items():
        if not isinstance(spec, dict):
            raise SystemExit(f"drop-in spec must be an object: {unit}")
        content = render_dropin(unit, spec)
        path = SYSTEMD_ETC_DIR / f"{unit}.d" / "10-hidloom-device-profile.conf"
        if dry_run:
            print(f"write-dropin {path}")
            for line in content.splitlines():
                print(f"  {line}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        os.chmod(path, 0o644)
        print(f"wrote drop-in {path}")


def systemctl(args: list[str], *, dry_run: bool) -> None:
    cmd = ["systemctl", *args]
    if dry_run:
        print("systemctl", " ".join(args))
        return
    subprocess.run(cmd, check=True)


def wait_for_sockets(
    paths: list[Path],
    *,
    timeout_sec: float = READY_SOCKET_TIMEOUT_SEC,
    poll_sec: float = READY_SOCKET_POLL_SEC,
) -> None:
    deadline = time.monotonic() + timeout_sec
    pending = list(paths)
    while pending:
        next_pending: list[Path] = []
        for path in pending:
            try:
                if stat.S_ISSOCK(path.stat().st_mode):
                    continue
            except FileNotFoundError:
                pass
            next_pending.append(path)
        pending = next_pending
        if not pending:
            return
        if time.monotonic() >= deadline:
            names = ", ".join(str(path) for path in pending)
            raise SystemExit(f"service readiness timeout waiting for socket(s): {names}")
        time.sleep(poll_sec)


def warn_shadowed_units(units: list[str]) -> None:
    for unit in units:
        path = SYSTEMD_ETC_DIR / unit
        if path.exists():
            print(f"warning: {unit} is shadowed by {path}; package unit may not be active", file=sys.stderr)


def apply_profile(
    profile_id: str,
    profile: dict[str, Any],
    base_dir: Path,
    *,
    runtime_dir: Path,
    dry_run: bool,
    backup: bool,
    restart: bool,
) -> None:
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    runtime_files = profile.get("runtime_files", {})
    config_files = profile.get("config_files", {})
    if not isinstance(runtime_files, dict) or not isinstance(config_files, dict):
        raise SystemExit("runtime_files and config_files must be objects")

    runtime_dir.mkdir(parents=True, exist_ok=True) if not dry_run else None
    for dest_name, src_name in runtime_files.items():
        copy_file(
            source_path(base_dir, str(src_name)),
            runtime_dir / str(dest_name),
            dry_run=dry_run,
            backup=backup,
            timestamp=timestamp,
        )
    if "flick.json" not in runtime_files:
        remove_runtime_file(runtime_dir / "flick.json", dry_run=dry_run, backup=backup, timestamp=timestamp)
    for dest_name, src_name in config_files.items():
        copy_file(
            source_path(base_dir, str(src_name)),
            runtime_dir / str(dest_name),
            dry_run=dry_run,
            backup=backup,
            timestamp=timestamp,
        )

    marker = {
        "schema": SCHEMA,
        "id": profile_id,
        "kind": profile.get("kind"),
        "selected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "selected_by": "script/apply_device_profile.py",
    }
    if dry_run:
        print(f"write-marker {runtime_dir / 'device_profile.json'}")
    else:
        write_json(runtime_dir / "device_profile.json", marker)
        print(f"wrote {runtime_dir / 'device_profile.json'}")

    write_dropins(profile, dry_run=dry_run)

    services = profile.get("services", {})
    enable = list(services.get("enable", [])) if isinstance(services, dict) else []
    disable = list(services.get("disable", [])) if isinstance(services, dict) else []
    mask = list(services.get("mask", [])) if isinstance(services, dict) else []
    ready_sockets = (
        [Path(str(path)) for path in services.get("ready_sockets", [])]
        if isinstance(services, dict)
        else []
    )
    for path in ready_sockets:
        if not path.is_absolute():
            raise SystemExit(f"service ready socket must be absolute: {path}")
    warn_shadowed_units([*enable, *disable, *mask])
    systemctl(["daemon-reload"], dry_run=dry_run)
    if enable:
        systemctl(["unmask", *enable], dry_run=dry_run)
    if disable:
        systemctl(["disable", *disable], dry_run=dry_run)
        if restart:
            systemctl(["stop", *disable], dry_run=dry_run)
    if mask:
        systemctl(["mask", *mask], dry_run=dry_run)
        if restart:
            systemctl(["stop", *mask], dry_run=dry_run)
    if enable:
        systemctl(["enable", *enable], dry_run=dry_run)
    if restart and enable:
        systemctl(["restart", *enable], dry_run=dry_run)
    final_stop = [*disable, *mask]
    if restart and final_stop:
        systemctl(["stop", *final_stop], dry_run=dry_run)
    if restart and ready_sockets:
        if dry_run:
            for path in ready_sockets:
                print(f"wait-socket {path}")
        else:
            wait_for_sockets(ready_sockets)


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply or inspect HIDloom device profiles")
    parser.add_argument("profile", nargs="?", help="profile id, for example touch-waveshare-8.8")
    parser.add_argument("--list", action="store_true", help="list available profiles")
    parser.add_argument("--json", action="store_true", help="print profiles as JSON when used with --list")
    parser.add_argument("--profile-dir", type=Path, help="profile metadata directory")
    parser.add_argument("--runtime-dir", type=Path, default=RUNTIME_DIR)
    parser.add_argument("--dry-run", action="store_true", help="show planned file and service changes")
    parser.add_argument("--apply", action="store_true", help="write files and apply service policy")
    parser.add_argument("--backup", action="store_true", help="backup existing runtime files before overwrite")
    parser.add_argument("--restart", action="store_true", help="restart enabled services and stop disabled services")
    args = parser.parse_args()

    profile_dir = resolve_profile_dir(args.profile_dir)
    profiles = load_profiles(profile_dir)
    if args.list:
        if args.json:
            print(json.dumps({"profiles": [profiles[key][0] for key in sorted(profiles)]}, ensure_ascii=False, indent=2))
        else:
            for key in sorted(profiles):
                profile = profiles[key][0]
                print(f"{key}\t{profile.get('kind', '')}\t{profile.get('label', '')}")
        if not args.profile:
            return
    if not args.profile:
        raise SystemExit("profile id is required unless --list is used")
    if args.dry_run == args.apply:
        raise SystemExit("choose exactly one of --dry-run or --apply")
    if args.profile not in profiles:
        raise SystemExit(f"unknown profile: {args.profile}")
    profile, base_dir = profiles[args.profile]
    apply_profile(
        args.profile,
        profile,
        base_dir,
        runtime_dir=args.runtime_dir,
        dry_run=args.dry_run,
        backup=args.backup,
        restart=args.restart,
    )


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(f"command failed: {exc}", file=sys.stderr)
        raise SystemExit(exc.returncode)
