#!/usr/bin/env python3
"""Build, verify, activate, and roll back a pinned HIDloom early-boot artifact."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any


SCHEMA = "hidloom.rpi-os-early-boot-package.v1"
STATE_SCHEMA = "hidloom.rpi-os-early-boot-control-state.v1"
RECEIPT_SCHEMA = "hidloom.rpi-os-early-tryboot-install.v1"
DEFAULT_ARTIFACT_ROOT = Path("/usr/lib/hidloom-early-boot/artifact")
DEFAULT_BOOT_ROOT = Path("/boot/firmware")
DEFAULT_ACCEPTED_ROOT = Path("/var/lib/hidloom/early-boot")
DEFAULT_STATE_ROOT = Path("/var/lib/hidloom/early-boot-control")
DEFAULT_BACKUP_ROOT = Path("/var/backups/hidloom/early-boot-control")
DEFAULT_MODEL_PATH = Path("/sys/firmware/devicetree/base/model")
DEFAULT_KERNEL_RELEASE_PATH = Path("/proc/sys/kernel/osrelease")
MANIFEST_NAME = "manifest.json"
STATE_NAME = "state.json"
ACCEPTED_NAME = "early-image.accepted.json"
TRYBOOT_NAME = "tryboot.txt"
CONFIG_NAME = "config.txt"
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
MINIMUM_FREE_BYTES = 32 * 1024 * 1024


class ControlError(RuntimeError):
    """The requested operation violates the pinned boot contract."""


@dataclass(frozen=True)
class Paths:
    artifact_root: Path = DEFAULT_ARTIFACT_ROOT
    boot_root: Path = DEFAULT_BOOT_ROOT
    accepted_root: Path = DEFAULT_ACCEPTED_ROOT
    state_root: Path = DEFAULT_STATE_ROOT
    backup_root: Path = DEFAULT_BACKUP_ROOT
    model_path: Path = DEFAULT_MODEL_PATH
    kernel_release_path: Path = DEFAULT_KERNEL_RELEASE_PATH


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SAFE_NAME_RE.fullmatch(value):
        raise ControlError(f"invalid {label}: {value!r}")
    if Path(value).name != value:
        raise ControlError(f"{label} must be a basename")
    return value


def read_json(path: Path, label: str, max_bytes: int = 2 * 1024 * 1024) -> dict[str, Any]:
    try:
        details = path.lstat()
    except OSError as exc:
        raise ControlError(f"cannot inspect {label}: {path}: {exc}") from exc
    if not stat.S_ISREG(details.st_mode) or details.st_size > max_bytes:
        raise ControlError(f"{label} is not a bounded regular file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ControlError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ControlError(f"{label} root must be an object")
    return value


def file_record(path: Path, name: str, role: str) -> dict[str, Any]:
    details = path.stat()
    if not stat.S_ISREG(details.st_mode):
        raise ControlError(f"artifact input is not regular: {path}")
    return {
        "path": safe_name(name, "artifact filename"),
        "role": role,
        "size": details.st_size,
        "sha256": sha256_file(path),
    }


def require_record(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"path", "role", "size", "sha256"}:
        raise ControlError(f"invalid {label} record")
    safe_name(value.get("path"), f"{label} path")
    if not isinstance(value.get("role"), str) or not value["role"]:
        raise ControlError(f"invalid {label} role")
    if not isinstance(value.get("size"), int) or value["size"] < 0:
        raise ControlError(f"invalid {label} size")
    if not isinstance(value.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"]):
        raise ControlError(f"invalid {label} SHA-256")
    return value


def verify_record(path: Path, record: dict[str, Any], label: str) -> None:
    try:
        details = path.lstat()
    except OSError as exc:
        raise ControlError(f"cannot inspect {label}: {path}: {exc}") from exc
    if not stat.S_ISREG(details.st_mode):
        raise ControlError(f"{label} is not a regular file: {path}")
    if details.st_size != record["size"] or sha256_file(path) != record["sha256"]:
        raise ControlError(f"{label} differs from the pinned artifact: {path}")


def build_manifest(payload_root: Path, output: Path) -> dict[str, Any]:
    receipt = read_json(payload_root / "receipt.json", "placement receipt")
    if receipt.get("schema") != RECEIPT_SCHEMA or receipt.get("status") != "installed-disabled":
        raise ControlError("placement receipt is not installed-disabled v1")
    activation = receipt.get("activation")
    if activation != {
        "default_boot_modified": False,
        "one_shot_requested": False,
        "reboot_requested": False,
        "tryboot_published_last": True,
    }:
        raise ControlError("placement receipt activation boundary is not disabled")
    boot_values = receipt.get("installed", {}).get("boot_files")
    normal_values = receipt.get("normal_boot_inputs")
    if not isinstance(boot_values, list) or not isinstance(normal_values, dict):
        raise ControlError("placement receipt lacks boot or normal input records")
    boot_records = []
    for index, value in enumerate(boot_values):
        pinned = require_record(value, f"receipt boot file {index}")
        source = payload_root / "boot" / pinned["path"]
        actual = file_record(source, pinned["path"], pinned["role"])
        if actual != pinned:
            raise ControlError(f"payload differs from receipt: {pinned['path']}")
        boot_records.append(actual)
    accepted_receipt = require_record(
        receipt.get("installed", {}).get("accepted_manifest"), "accepted manifest"
    )
    accepted_source = payload_root / "accepted" / ACCEPTED_NAME
    accepted_record = file_record(accepted_source, ACCEPTED_NAME, accepted_receipt["role"])
    if accepted_record != accepted_receipt:
        raise ControlError("accepted manifest differs from receipt")
    normal_records = {}
    for key in ("config", "cmdline", "kernel", "initramfs"):
        normal_records[key] = require_record(normal_values.get(key), f"normal {key}")
    manifest = {
        "schema": SCHEMA,
        "source": receipt.get("source"),
        "profile": "keyboard-ver1",
        "model": receipt.get("model"),
        "kernel_release": receipt.get("kernel_release"),
        "placement_sha256": receipt.get("placement_sha256"),
        "boot_files": sorted(boot_records, key=lambda item: item["path"]),
        "accepted_manifest": accepted_record,
        "normal_boot_inputs": normal_records,
        "receipt": file_record(payload_root / "receipt.json", "receipt.json", "placement_receipt"),
        "policy": {
            "install_disabled": True,
            "postinst_modifies_boot": False,
            "kernel_mismatch": "disable-or-refuse",
            "persistent_enable_requires_explicit_command": True,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_bytes(manifest))
    return manifest


def load_manifest(paths: Paths) -> dict[str, Any]:
    manifest = read_json(paths.artifact_root / MANIFEST_NAME, "artifact manifest")
    required = {
        "schema", "source", "profile", "model", "kernel_release",
        "placement_sha256", "boot_files", "accepted_manifest",
        "normal_boot_inputs", "receipt", "policy",
    }
    if set(manifest) != required or manifest.get("schema") != SCHEMA:
        raise ControlError("artifact manifest schema or fields are invalid")
    if manifest.get("profile") != "keyboard-ver1":
        raise ControlError("artifact profile is not keyboard-ver1")
    if not isinstance(manifest.get("source"), str) or not re.fullmatch(r"[0-9a-f]{40}", manifest["source"]):
        raise ControlError("artifact source is not a full Git SHA")
    if not isinstance(manifest.get("kernel_release"), str) or not manifest["kernel_release"]:
        raise ControlError("artifact kernel release is invalid")
    if not isinstance(manifest.get("model"), str) or not manifest["model"]:
        raise ControlError("artifact model is invalid")
    if not isinstance(manifest.get("placement_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", manifest["placement_sha256"]):
        raise ControlError("artifact placement SHA-256 is invalid")
    policy = manifest.get("policy")
    if policy != {
        "install_disabled": True,
        "postinst_modifies_boot": False,
        "kernel_mismatch": "disable-or-refuse",
        "persistent_enable_requires_explicit_command": True,
    }:
        raise ControlError("artifact policy is invalid")
    boot_values = manifest.get("boot_files")
    if not isinstance(boot_values, list) or not boot_values:
        raise ControlError("artifact boot inventory is empty")
    names = []
    for index, value in enumerate(boot_values):
        record = require_record(value, f"boot file {index}")
        names.append(record["path"])
        verify_record(paths.artifact_root / "boot" / record["path"], record, f"artifact {record['path']}")
    if names != sorted(names) or len(names) != len(set(names)) or TRYBOOT_NAME not in names:
        raise ControlError("artifact boot inventory is unsorted, duplicated, or lacks tryboot.txt")
    accepted = require_record(manifest.get("accepted_manifest"), "accepted manifest")
    verify_record(paths.artifact_root / "accepted" / accepted["path"], accepted, "artifact accepted manifest")
    receipt = require_record(manifest.get("receipt"), "receipt")
    verify_record(paths.artifact_root / receipt["path"], receipt, "artifact placement receipt")
    normal = manifest.get("normal_boot_inputs")
    if not isinstance(normal, dict) or set(normal) != {"config", "cmdline", "kernel", "initramfs"}:
        raise ControlError("normal boot input inventory is invalid")
    for key, value in normal.items():
        require_record(value, f"normal {key}")
    return manifest


def read_identity(path: Path, label: str) -> str:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ControlError(f"cannot read {label}: {path}: {exc}") from exc
    return raw.rstrip(b"\x00\r\n").decode("utf-8")


def verify_identity(paths: Paths, manifest: dict[str, Any]) -> None:
    model = read_identity(paths.model_path, "device model")
    release = read_identity(paths.kernel_release_path, "kernel release")
    if model != manifest["model"]:
        raise ControlError(f"device model mismatch: {model!r}")
    if release != manifest["kernel_release"]:
        raise ControlError(
            f"kernel release mismatch: running={release!r} pinned={manifest['kernel_release']!r}"
        )


def verify_normal_inputs(paths: Paths, manifest: dict[str, Any], *, include_config: bool) -> None:
    for key, record in manifest["normal_boot_inputs"].items():
        if key == "config" and not include_config:
            continue
        verify_record(paths.boot_root / record["path"], record, f"live normal {key}")


def state_path(paths: Paths) -> Path:
    return paths.state_root / STATE_NAME


def load_state(paths: Paths) -> dict[str, Any] | None:
    path = state_path(paths)
    if not path.exists():
        return None
    state = read_json(path, "control state")
    if state.get("schema") != STATE_SCHEMA:
        raise ControlError("control state schema is invalid")
    return state


def fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        try:
            os.fsync(descriptor)
        except OSError:
            pass
    finally:
        os.close(descriptor)


def atomic_write(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.hidloom-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        fchmod = getattr(os, "fchmod", None)
        if fchmod is not None:
            fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if fchmod is None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def save_state(paths: Paths, state: dict[str, Any]) -> None:
    paths.state_root.mkdir(parents=True, exist_ok=True)
    atomic_write(state_path(paths), canonical_bytes(state), 0o600)


def require_root() -> None:
    geteuid = getattr(os, "geteuid", lambda: 1)
    if geteuid() != 0 and os.environ.get("HIDLOOM_EARLY_BOOT_TEST_ROOT") != "1":
        raise ControlError("this operation requires root")


def prepare_payload(paths: Paths, manifest: dict[str, Any]) -> dict[str, bool]:
    require_root()
    created: dict[str, bool] = {}
    paths.boot_root.mkdir(parents=True, exist_ok=True)
    paths.accepted_root.mkdir(parents=True, exist_ok=True)
    copies: list[tuple[Path, Path, dict[str, Any], str, int]] = []
    for record in manifest["boot_files"]:
        source = paths.artifact_root / "boot" / record["path"]
        target = paths.boot_root / record["path"]
        if target.exists():
            verify_record(target, record, f"existing boot payload {record['path']}")
            created[f"boot/{record['path']}"] = False
        else:
            created[f"boot/{record['path']}"] = True
            copies.append((source, target, record, f"boot payload {record['path']}", 0o644))
    accepted = manifest["accepted_manifest"]
    accepted_source = paths.artifact_root / "accepted" / accepted["path"]
    accepted_target = paths.accepted_root / accepted["path"]
    if accepted_target.exists():
        verify_record(accepted_target, accepted, "existing accepted manifest")
        created[f"accepted/{accepted['path']}"] = False
    else:
        created[f"accepted/{accepted['path']}"] = True
        copies.append((accepted_source, accepted_target, accepted, "accepted manifest", 0o600))

    boot_device = paths.boot_root.stat().st_dev
    requirements: dict[int, dict[str, Any]] = {
        boot_device: {"root": paths.boot_root, "payload_bytes": 0}
    }
    for _, target, record, _, _ in copies:
        device = target.parent.stat().st_dev
        requirement = requirements.setdefault(
            device, {"root": target.parent, "payload_bytes": 0}
        )
        requirement["payload_bytes"] += record["size"]
    for requirement in requirements.values():
        required = requirement["payload_bytes"] + MINIMUM_FREE_BYTES
        free = shutil.disk_usage(requirement["root"]).free
        if free < required:
            raise ControlError(
                f"insufficient free space at {requirement['root']}: "
                f"need {required} bytes including {MINIMUM_FREE_BYTES} reserve, have {free}"
            )

    for source, target, record, label, mode in copies:
        atomic_write(target, source.read_bytes(), mode)
        verify_record(target, record, f"installed {label}")
    return created


def enabled_config(paths: Paths, manifest: dict[str, Any]) -> bytes:
    record = next(item for item in manifest["boot_files"] if item["path"] == TRYBOOT_NAME)
    source = paths.artifact_root / "boot" / TRYBOOT_NAME
    verify_record(source, record, "enabled config source")
    return source.read_bytes()


def new_state(paths: Paths, manifest: dict[str, Any], created: dict[str, bool]) -> dict[str, Any]:
    paths.backup_root.mkdir(parents=True, exist_ok=True)
    backup_dir = Path(tempfile.mkdtemp(prefix="enable-", dir=paths.backup_root))
    os.chmod(backup_dir, 0o700)
    normal_config = manifest["normal_boot_inputs"]["config"]
    live_config = paths.boot_root / normal_config["path"]
    verify_record(live_config, normal_config, "normal config before enable")
    backup_path = backup_dir / CONFIG_NAME
    atomic_write(backup_path, live_config.read_bytes(), 0o600)
    state = {
        "schema": STATE_SCHEMA,
        "status": "prepared-disabled",
        "source": manifest["source"],
        "kernel_release": manifest["kernel_release"],
        "placement_sha256": manifest["placement_sha256"],
        "backup": {
            "directory": str(backup_dir),
            "config": file_record(backup_path, CONFIG_NAME, "normal_config_backup"),
        },
        "created": created,
        "one_shot_requested": False,
        "reboot_requested": False,
        "last_action": "prepare",
    }
    save_state(paths, state)
    return state


def ensure_state(paths: Paths, manifest: dict[str, Any]) -> dict[str, Any]:
    state = load_state(paths)
    if state is not None:
        for key in ("source", "kernel_release", "placement_sha256"):
            if state.get(key) != manifest[key]:
                raise ControlError(f"control state {key} differs from artifact")
        return state
    created = prepare_payload(paths, manifest)
    return new_state(paths, manifest, created)


def restore_normal(paths: Paths, manifest: dict[str, Any], state: dict[str, Any]) -> bool:
    backup = state.get("backup", {})
    record = require_record(backup.get("config"), "backup config")
    backup_path = Path(str(backup.get("directory", ""))) / record["path"]
    verify_record(backup_path, record, "normal config backup")
    config_path = paths.boot_root / manifest["normal_boot_inputs"]["config"]["path"]
    current = config_path.read_bytes()
    normal = backup_path.read_bytes()
    enabled = enabled_config(paths, manifest)
    if current == normal:
        return False
    if current != enabled:
        raise ControlError("live config is neither pinned enabled config nor saved normal config")
    atomic_write(config_path, normal, 0o644)
    verify_record(config_path, manifest["normal_boot_inputs"]["config"], "restored normal config")
    return True


def command_verify(paths: Paths, live: bool) -> dict[str, Any]:
    manifest = load_manifest(paths)
    result = {
        "schema": SCHEMA,
        "status": "pass",
        "source": manifest["source"],
        "profile": manifest["profile"],
        "kernel_release": manifest["kernel_release"],
        "artifact_files": len(manifest["boot_files"]) + 2,
        "live_verified": False,
    }
    if live:
        verify_identity(paths, manifest)
        state = load_state(paths)
        include_config = state is None or state.get("status") != "enabled"
        verify_normal_inputs(paths, manifest, include_config=include_config)
        result["live_verified"] = True
    return result


def command_status(paths: Paths) -> dict[str, Any]:
    manifest = load_manifest(paths)
    state = load_state(paths)
    running_release = read_identity(paths.kernel_release_path, "kernel release")
    config_path = paths.boot_root / manifest["normal_boot_inputs"]["config"]["path"]
    config_raw = config_path.read_bytes()
    normal_record = manifest["normal_boot_inputs"]["config"]
    normal = config_path.stat().st_size == normal_record["size"] and sha256_file(config_path) == normal_record["sha256"]
    enabled = config_raw == enabled_config(paths, manifest)
    if enabled:
        mode = "enabled"
    elif normal:
        mode = "disabled"
    else:
        mode = "drift"
    return {
        "schema": STATE_SCHEMA,
        "status": "pass" if mode != "drift" else "unsafe",
        "mode": mode,
        "source": manifest["source"],
        "profile": manifest["profile"],
        "pinned_kernel_release": manifest["kernel_release"],
        "running_kernel_release": running_release,
        "kernel_match": running_release == manifest["kernel_release"],
        "state_present": state is not None,
        "state_status": state.get("status") if state else "package-installed-disabled",
        "one_shot_requested": bool(state and state.get("one_shot_requested")),
        "reboot_requested": bool(state and state.get("reboot_requested")),
    }


def command_enable(paths: Paths, confirm_source: str) -> dict[str, Any]:
    require_root()
    manifest = load_manifest(paths)
    if confirm_source != manifest["source"]:
        raise ControlError("--confirm-source must equal the full pinned source SHA")
    verify_identity(paths, manifest)
    if load_state(paths) is None:
        verify_normal_inputs(paths, manifest, include_config=True)
    state = ensure_state(paths, manifest)
    config_path = paths.boot_root / manifest["normal_boot_inputs"]["config"]["path"]
    enabled = enabled_config(paths, manifest)
    if config_path.read_bytes() != enabled:
        verify_normal_inputs(paths, manifest, include_config=True)
        state["status"] = "enabling"
        state["last_action"] = "enable-prepare"
        save_state(paths, state)
        atomic_write(config_path, enabled, 0o644)
    if config_path.read_bytes() != enabled:
        raise ControlError("enabled config publication failed")
    state["status"] = "enabled"
    state["last_action"] = "enable"
    state["one_shot_requested"] = False
    state["reboot_requested"] = False
    save_state(paths, state)
    return command_status(paths)


def command_disable(paths: Paths, reason: str) -> dict[str, Any]:
    require_root()
    manifest = load_manifest(paths)
    state = load_state(paths)
    if state is None:
        verify_normal_inputs(paths, manifest, include_config=True)
        return command_status(paths)
    restored = restore_normal(paths, manifest, state)
    state["status"] = "disabled"
    state["last_action"] = f"disable:{reason}"
    state["one_shot_requested"] = False
    state["reboot_requested"] = False
    save_state(paths, state)
    result = command_status(paths)
    result["restored"] = restored
    return result


def command_try_once(paths: Paths, confirm_source: str, reboot: bool) -> dict[str, Any]:
    require_root()
    manifest = load_manifest(paths)
    if confirm_source != manifest["source"]:
        raise ControlError("--confirm-source must equal the full pinned source SHA")
    verify_identity(paths, manifest)
    verify_normal_inputs(paths, manifest, include_config=True)
    state = ensure_state(paths, manifest)
    if command_status(paths)["mode"] != "disabled":
        raise ControlError("try-once requires disabled normal config")
    state["one_shot_requested"] = True
    state["reboot_requested"] = reboot
    state["last_action"] = "try-once"
    save_state(paths, state)
    result = command_status(paths)
    if reboot:
        os.sync()
        subprocess.run(["/usr/sbin/reboot", "0", "tryboot"], check=True)
    return result


def command_rollback(paths: Paths) -> dict[str, Any]:
    require_root()
    manifest = load_manifest(paths)
    state = load_state(paths)
    if state is None:
        verify_normal_inputs(paths, manifest, include_config=True)
        return {"schema": STATE_SCHEMA, "status": "pass", "mode": "disabled", "removed": []}
    restore_normal(paths, manifest, state)
    removed = []
    created = state.get("created")
    if not isinstance(created, dict):
        raise ControlError("control state created-file inventory is invalid")
    records = {f"boot/{item['path']}": item for item in manifest["boot_files"]}
    accepted = manifest["accepted_manifest"]
    records[f"accepted/{accepted['path']}"] = accepted
    for key in sorted(created, reverse=True):
        if created[key] is not True:
            continue
        record = records.get(key)
        if record is None:
            raise ControlError(f"unknown created-file record: {key}")
        group, name = key.split("/", 1)
        target = (paths.boot_root if group == "boot" else paths.accepted_root) / name
        verify_record(target, record, f"rollback target {key}")
        target.unlink()
        removed.append(key)
    state["status"] = "rolled-back"
    state["last_action"] = "rollback"
    state["one_shot_requested"] = False
    state["reboot_requested"] = False
    save_state(paths, state)
    return {
        "schema": STATE_SCHEMA,
        "status": "pass",
        "mode": "disabled",
        "removed": sorted(removed),
        "retained_preexisting": sorted(key for key, value in created.items() if value is False),
    }


def command_kernel_guard(paths: Paths, new_release: str) -> dict[str, Any]:
    require_root()
    manifest = load_manifest(paths)
    if new_release == manifest["kernel_release"]:
        return {"schema": STATE_SCHEMA, "status": "pass", "action": "none", "kernel_match": True}
    status = command_status(paths)
    action = "already-disabled"
    if status["mode"] == "enabled":
        command_disable(paths, f"kernel-mismatch:{new_release}")
        action = "disabled"
    elif status["mode"] == "drift":
        raise ControlError("kernel mismatch found with unknown config drift")
    return {
        "schema": STATE_SCHEMA,
        "status": "pass",
        "action": action,
        "kernel_match": False,
        "new_release": new_release,
        "pinned_release": manifest["kernel_release"],
    }


def add_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--boot-root", type=Path, default=DEFAULT_BOOT_ROOT)
    parser.add_argument("--accepted-root", type=Path, default=DEFAULT_ACCEPTED_ROOT)
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    parser.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUP_ROOT)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--kernel-release-path", type=Path, default=DEFAULT_KERNEL_RELEASE_PATH)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="build a canonical artifact manifest")
    build.add_argument("--payload-root", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify", help="verify the package artifact and optionally live state")
    add_paths(verify)
    verify.add_argument("--live", action="store_true")
    status = commands.add_parser("status", help="report activation and kernel-match state")
    add_paths(status)
    for name in ("enable", "try-once"):
        command = commands.add_parser(name)
        add_paths(command)
        command.add_argument("--confirm-source", required=True)
        if name == "try-once":
            command.add_argument("--reboot", action="store_true")
    disable = commands.add_parser("disable")
    add_paths(disable)
    disable.add_argument("--reason", default="operator")
    rollback = commands.add_parser("rollback")
    add_paths(rollback)
    guard = commands.add_parser("kernel-guard")
    add_paths(guard)
    guard.add_argument("--new-release", required=True)
    return result


def paths_from(args: argparse.Namespace) -> Paths:
    return Paths(
        artifact_root=args.artifact_root,
        boot_root=args.boot_root,
        accepted_root=args.accepted_root,
        state_root=args.state_root,
        backup_root=args.backup_root,
        model_path=args.model_path,
        kernel_release_path=args.kernel_release_path,
    )


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "build":
            result = build_manifest(args.payload_root, args.output)
        else:
            paths = paths_from(args)
            if args.command == "verify":
                result = command_verify(paths, args.live)
            elif args.command == "status":
                result = command_status(paths)
            elif args.command == "enable":
                result = command_enable(paths, args.confirm_source)
            elif args.command == "try-once":
                result = command_try_once(paths, args.confirm_source, args.reboot)
            elif args.command == "disable":
                result = command_disable(paths, args.reason)
            elif args.command == "rollback":
                result = command_rollback(paths)
            else:
                result = command_kernel_guard(paths, args.new_release)
    except (ControlError, OSError, subprocess.CalledProcessError, KeyError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
