#!/usr/bin/env python3
"""Apply HIDloom device profile runtime files and service policy."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
import time
import uuid
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
DROPIN_NAME = "10-hidloom-device-profile.conf"
DROPIN_HEADER = "# Managed by hidloom-profile; sha256="
# Exact output of the original touch profile, retained after its package removal.
LEGACY_DROPINS = {
    "logicd.service": '[Unit]\nWants=\nWants=dev-hidg0.device\n\n[Service]\nEnvironment="LOGICD_MATRIX_ROWS=16"\nEnvironment="LOGICD_MATRIX_COLS=16"\nEnvironment="LOGICD_OUTPUTS=auto"\n',
    "httpd.service": "[Unit]\nAfter=\nAfter=logicd.service\nWants=\nWants=logicd.service\n",
    "viald.service": "[Unit]\nAfter=\nAfter=hidloom-usb-gadget.service logicd.service\n",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_content(path, (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


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
    candidate = path.with_name(f"{path.name}.bak.{timestamp}")
    suffix = 1
    while candidate.exists() or candidate.is_symlink():
        candidate = path.with_name(f"{path.name}.bak.{timestamp}.{suffix}")
        suffix += 1
    return candidate


def atomic_content(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


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
    atomic_content(dst, src.read_bytes())
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


def planned_dropins(profile: dict[str, Any]) -> dict[Path, str]:
    dropins = profile.get("dropins", {})
    if not isinstance(dropins, dict):
        raise SystemExit("profile dropins must be an object")
    desired = {}
    for unit, spec in dropins.items():
        if not re.fullmatch(r"[A-Za-z0-9_@.+-]+\.(service|timer|socket|target)", unit):
            raise SystemExit(f"invalid drop-in unit: {unit}")
        if not isinstance(spec, dict):
            raise SystemExit(f"drop-in spec must be an object: {unit}")
        content = render_dropin(unit, spec)
        path = SYSTEMD_ETC_DIR / f"{unit}.d" / DROPIN_NAME
        desired[path] = DROPIN_HEADER + hashlib.sha256(content.encode()).hexdigest() + "\n" + content
    return desired


def owned_dropins(desired: dict[Path, str]) -> list[Path]:
    existing = set(SYSTEMD_ETC_DIR.glob(f"*.d/{DROPIN_NAME}")) | set(desired)
    owned = []
    for path in sorted(existing):
        if path.parent.is_symlink() or path.is_symlink():
            raise SystemExit(f"profile drop-in symlink conflict: {path}")
        if not path.exists():
            continue
        if not path.is_file():
            raise SystemExit(f"profile drop-in is not a regular file: {path}")
        content = path.read_text(encoding="utf-8")
        header, separator, body = content.partition("\n")
        managed = separator and header == DROPIN_HEADER + hashlib.sha256(body.encode()).hexdigest()
        legacy = content == LEGACY_DROPINS.get(path.parent.name.removesuffix(".d"))
        if not managed and not legacy:
            raise SystemExit(f"unrecognized profile drop-in; preserve and inspect: {path}")
        owned.append(path)
    return owned


def write_dropins(profile: dict[str, Any], *, dry_run: bool, backup: bool = False,
                  timestamp: str = "", plan: tuple[dict[Path, str], list[Path]] | None = None) -> None:
    desired, owned = plan if plan is not None else (planned_dropins(profile), [])
    if plan is None:
        owned = owned_dropins(desired)
    unchanged = {path for path in owned if path in desired
                 and path.read_bytes() == desired[path].encode("utf-8")
                 and stat.S_IMODE(path.stat().st_mode) == 0o644}
    for path in owned:
        if path in unchanged:
            continue
        if backup:
            saved = backup_path(path, timestamp)
            print(f"backup {path} -> {saved}")
            if not dry_run:
                shutil.copy2(path, saved)
        if path not in desired:
            print(f"remove-dropin {path}")
            if not dry_run:
                path.unlink()
    for path, content in desired.items():
        if path in unchanged:
            continue
        if dry_run:
            print(f"write-dropin {path}")
            for line in content.splitlines():
                print(f"  {line}")
            continue
        atomic_content(path, content.encode("utf-8"))
        print(f"wrote drop-in {path}")


def validate_profile(profile_id: str, profile: dict[str, Any], base_dir: Path,
                     runtime_dir: Path) -> tuple[dict[Path, str], list[Path]]:
    if not re.fullmatch(r"[A-Za-z0-9.+-]+", profile_id):
        raise SystemExit(f"invalid profile id: {profile_id}")
    destinations = set()
    for section in ("runtime_files", "config_files"):
        files = profile.get(section, {})
        if not isinstance(files, dict):
            raise SystemExit(f"{section} must be an object")
        for destination, source in files.items():
            if not isinstance(destination, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", destination) or destination in (".", "..", "device_profile.json"):
                raise SystemExit(f"invalid runtime destination: {destination!r}")
            if destination in destinations:
                raise SystemExit(f"duplicate runtime destination: {destination}")
            destinations.add(destination)
            src = source_path(base_dir, str(source))
            if not src.is_file() or src.is_symlink():
                raise SystemExit(f"missing or invalid profile source file: {src}")
            dst = runtime_dir / destination
            if dst.is_symlink() or (dst.exists() and not dst.is_file()):
                raise SystemExit(f"runtime destination conflict: {dst}")
    if runtime_dir.is_symlink() or (runtime_dir.exists() and not runtime_dir.is_dir()):
        raise SystemExit(f"runtime directory conflict: {runtime_dir}")
    for dst in (runtime_dir / "flick.json", runtime_dir / "device_profile.json"):
        if dst.is_symlink() or (dst.exists() and not dst.is_file()):
            raise SystemExit(f"runtime destination conflict: {dst}")
    services = profile.get("services", {})
    if not isinstance(services, dict):
        raise SystemExit("profile services must be an object")
    groups = {}
    for group in ("enable", "disable", "mask"):
        values = services.get(group, [])
        if not isinstance(values, list) or any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_@.+-]+\.(service|timer|socket|target)", v) for v in values):
            raise SystemExit(f"invalid service list: {group}")
        groups[group] = set(values)
    if groups["enable"] & (groups["disable"] | groups["mask"]):
        raise SystemExit("profile cannot enable disabled or masked services")
    sockets = services.get("ready_sockets", [])
    if not isinstance(sockets, list) or any(not isinstance(v, str) or not Path(v).is_absolute() for v in sockets):
        raise SystemExit("service ready socket must be absolute")
    desired = planned_dropins(profile)
    return desired, owned_dropins(desired)


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


def file_fingerprint(path: Path) -> tuple[Any, ...] | None:
    if path.is_symlink():
        return ("symlink", os.readlink(path))
    if not path.exists():
        return None
    if not path.is_file():
        return ("nonregular",)
    return ("file", stat.S_IMODE(path.stat().st_mode), hashlib.sha256(path.read_bytes()).hexdigest())


def report_partial_apply(before: dict[Path, tuple[Any, ...] | None],
                         backups_before: set[Path], progress: dict[str, Any], error: BaseException) -> None:
    """Report bounded file recovery, without claiming a device-wide rollback."""
    print(f"profile apply incomplete; failed phase: {progress['phase']}: {error}", file=sys.stderr)
    commands = []
    for path, original in sorted(before.items()):
        current = file_fingerprint(path)
        if current != original:
            print(f"changed-path: {path}", file=sys.stderr)
        backups = sorted(set(path.parent.glob(path.name + ".bak.*")) - backups_before)
        for saved in backups:
            valid = file_fingerprint(saved) == original
            print(f"backup {'verified' if valid else 'unverified'}: {saved}", file=sys.stderr)
        valid_backups = [saved for saved in backups if original is not None and file_fingerprint(saved) == original]
        if current != original:
            if valid_backups:
                commands.append(["sudo", "cp", "-p", "--", str(valid_backups[0]), str(path)])
            elif original is None:
                commands.append(["sudo", "rm", "--", str(path)])
            else:
                print(f"manual recovery required; no verified backup for: {path}", file=sys.stderr)
    for operation in progress["services"]:
        print(f"service-operation: {operation}", file=sys.stderr)
    print("Recovery: inspect the partial state, then restore the prior file bytes/modes with:", file=sys.stderr)
    for command in commands:
        print("  " + shlex.join(command), file=sys.stderr)
    print("  sudo systemctl daemon-reload", file=sys.stderr)
    print("Then inspect the prior profile marker and restore its service policy using the profile runbook; "
          "this does not restore service state or downgrade packages automatically.", file=sys.stderr)
    print("Check installed versions: dpkg-query -W 'hidloom-core' 'hidloom-profile-*'", file=sys.stderr)


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
    dropin_plan = validate_profile(profile_id, profile, base_dir, runtime_dir)
    paths = {runtime_dir / str(name) for section in ("runtime_files", "config_files")
             for name in profile.get(section, {})}
    paths.update((runtime_dir / "flick.json", runtime_dir / "device_profile.json"))
    paths.update(dropin_plan[0])
    paths.update(dropin_plan[1])
    before = {path: file_fingerprint(path) for path in paths}
    backups_before = {saved for path in paths for saved in path.parent.glob(path.name + ".bak.*")}
    progress: dict[str, Any] = {"phase": "prepare-runtime-directory", "services": []}
    try:
        _apply_profile(profile_id, profile, base_dir, runtime_dir=runtime_dir, dry_run=dry_run,
                       backup=backup, restart=restart, dropin_plan=dropin_plan, progress=progress)
    except (OSError, subprocess.CalledProcessError, SystemExit) as error:
        if not dry_run:
            try:
                report_partial_apply(before, backups_before, progress, error)
            except OSError as report_error:
                print(f"partial-state inspection also failed: {report_error}; retain all backups and inspect "
                      f"the failed phase {progress['phase']} manually", file=sys.stderr)
        raise


def _apply_profile(profile_id: str, profile: dict[str, Any], base_dir: Path, *,
                   runtime_dir: Path, dry_run: bool, backup: bool, restart: bool,
                   dropin_plan: tuple[dict[Path, str], list[Path]], progress: dict[str, Any]) -> None:
    def service(arguments: list[str]) -> None:
        progress["phase"] = "systemctl " + " ".join(arguments)
        progress["services"].append(progress["phase"] + " (attempted)")
        systemctl(arguments, dry_run=dry_run)
        progress["services"][-1] = progress["phase"] + " (completed)"

    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    runtime_files = profile.get("runtime_files", {})
    config_files = profile.get("config_files", {})
    if not isinstance(runtime_files, dict) or not isinstance(config_files, dict):
        raise SystemExit("runtime_files and config_files must be objects")

    runtime_dir.mkdir(parents=True, exist_ok=True) if not dry_run else None
    for dest_name, src_name in runtime_files.items():
        progress["phase"] = f"copy:{runtime_dir / str(dest_name)}"
        copy_file(
            source_path(base_dir, str(src_name)),
            runtime_dir / str(dest_name),
            dry_run=dry_run,
            backup=backup,
            timestamp=timestamp,
        )
    if "flick.json" not in runtime_files:
        progress["phase"] = f"remove:{runtime_dir / 'flick.json'}"
        remove_runtime_file(runtime_dir / "flick.json", dry_run=dry_run, backup=backup, timestamp=timestamp)
    for dest_name, src_name in config_files.items():
        progress["phase"] = f"copy:{runtime_dir / str(dest_name)}"
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
    progress["phase"] = "reconcile-dropins"
    write_dropins(profile, dry_run=dry_run, backup=backup, timestamp=timestamp, plan=dropin_plan)

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
    service(["daemon-reload"])
    if enable:
        service(["unmask", *enable])
    if disable:
        service(["disable", *disable])
        if restart:
            service(["stop", *disable])
    if mask:
        service(["mask", *mask])
        if restart:
            service(["stop", *mask])
    if enable:
        service(["enable", *enable])
    if restart and enable:
        service(["restart", *enable])
    final_stop = [*disable, *mask]
    if restart and final_stop:
        service(["stop", *final_stop])
    if restart and ready_sockets:
        if dry_run:
            for path in ready_sockets:
                print(f"wait-socket {path}")
        else:
            progress["phase"] = "readiness"
            wait_for_sockets(ready_sockets)
    if dry_run:
        print(f"write-marker {runtime_dir / 'device_profile.json'}")
    else:
        progress["phase"] = "write-marker"
        write_json(runtime_dir / "device_profile.json", marker)
        print(f"wrote {runtime_dir / 'device_profile.json'}")


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
