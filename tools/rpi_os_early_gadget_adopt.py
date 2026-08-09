#!/usr/bin/env python3
"""Verify that a bound early-initramfs USB gadget is safe to adopt.

Gadget verification and capture are deliberately read-only with respect to the
machine state.  They do not bind, unbind, remove, create, chmod, or chown any
configfs or runtime object.  ``capture`` may create only its explicitly named,
previously absent output file.  The explicit service-stop command may unlink
only a validated ephemeral early marker after proving the gadget is stably
unbound.  The handoff wrapper uses these verify states:

* 0: the live gadget exactly matches the accepted early-image contract;
* 10: the marker is absent and the gadget is absent or stably unbound;
* 78: anything else is an unsafe or unverifiable state.

All mutable filesystem roots are explicit CLI inputs so the complete decision
can be exercised against ordinary host-side fixtures.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import sys
from typing import Any


EXIT_ADOPTED = 0
EXIT_CREATE_SENTINEL = 10
EXIT_UNSAFE = 78

IMAGE_SCHEMA = "hidloom.rpi-os-early-initramfs.e1.v1"
RUNTIME_CONTRACT_SCHEMA = "hidloom.rpi-os-early-runtime-contract.e1.v1"
ADOPT_CONTRACT_SCHEMA = "hidloom.rpi-os-early-gadget-adopt.v1"
GADGET_CONTRACT_SCHEMA = "hidloom.configfs-usb-gadget.snapshot.v2"
MARKER_SCHEMA = "hidloom.early-gadget-bound.v1"
PROFILE_SCHEMA = "cqa02303v5.device-profile.v1"
PACKAGE_MANIFEST_SCHEMA = "hidloom.release-bundle.v1"

SHA256_RE = re.compile(r"[0-9a-f]{64}")
SAFE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+~-]{0,127}")
SAFE_PACKAGE_RE = re.compile(r"[a-z0-9][a-z0-9+.-]{0,127}")
FUNCTION_RE = re.compile(r"hid\.usb[0-9]+")
IDENTITY_VALUE_RE = re.compile(r"[A-Za-z0-9 ._:,+/@-]{0,127}")
E1_REPORT_FUNCTIONS = {
    "main": "hid.usb0",
    "raw": "hid.usb1",
    "us_sub": "hid.usb2",
    "windows_ime_custom": "hid.usb4",
}

EP0_MAX_PACKET_SIZE_ENTRY = "bMaxPacketSize0"
# Zero is configfs' kernel-owned, pre-bind default.  USB 2.x uses byte counts,
# while USB 3.x encodes 512 bytes as exponent 9 in the device descriptor.
VALID_EP0_MAX_PACKET_SIZE_VALUES = {0, 8, 9, 16, 32, 64}

IDENTITY_DEFAULTS = {
    "HIDLOOM_USB_VENDOR_ID": "0x1d6b",
    "HIDLOOM_USB_PRODUCT_ID": "0x0105",
    "HIDLOOM_USB_SERIAL": "vial:f64c2b3c",
    "HIDLOOM_USB_SERIAL_SUFFIX": "",
    "HIDLOOM_USB_US_SUB_KEYBOARD": "1",
    "HIDLOOM_WINDOWS_IME_CUSTOM_HID": "0",
}
IDENTITY_KEYS = {
    "HIDLOOM_USB_VENDOR_ID",
    "HIDLOOM_USB_PRODUCT_ID",
    "HIDLOOM_USB_MANUFACTURER",
    "HIDLOOM_USB_PRODUCT_NAME",
    "HIDLOOM_USB_SERIAL",
    "HIDLOOM_USB_SERIAL_SUFFIX",
    "HIDLOOM_USB_US_SUB_KEYBOARD",
    "HIDLOOM_WINDOWS_IME_CUSTOM_HID",
}


class AdoptError(ValueError):
    """The live state cannot be adopted without risking a USB disconnect."""


class AdoptArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise AdoptError(f"command line: {message}")


def strict_json_loads(data: bytes | str, label: str) -> object:
    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise AdoptError(f"{label} contains duplicate key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise AdoptError(f"{label} contains non-finite number: {value}")

    return json.loads(
        data,
        object_pairs_hook=object_pairs,
        parse_constant=reject_constant,
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_sha256(value: object) -> str:
    return sha256_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    )


def require_sha256(value: object, label: str) -> str:
    text = str(value)
    if not SHA256_RE.fullmatch(text):
        raise AdoptError(f"{label} is not a lowercase SHA-256")
    return text


def require_string(value: object, label: str, pattern: re.Pattern[str] = SAFE_NAME_RE) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise AdoptError(f"{label} is invalid")
    return value


def require_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AdoptError(f"{label} must be an object")
    return value


def require_regular_secure(path: Path, label: str, owner_uid: int) -> os.stat_result:
    try:
        details = path.lstat()
    except OSError as exc:
        raise AdoptError(f"cannot stat {label}: {path}: {exc}") from exc
    if not stat.S_ISREG(details.st_mode):
        raise AdoptError(f"{label} is not a regular file: {path}")
    if details.st_uid != owner_uid:
        raise AdoptError(
            f"{label} owner mismatch: {path}: {details.st_uid} != {owner_uid}"
        )
    if details.st_mode & 0o022:
        raise AdoptError(f"{label} is group/world writable: {path}")
    return details


def read_secure_json(
    path: Path, label: str, owner_uid: int, *, max_bytes: int = 8 * 1024 * 1024
) -> tuple[dict[str, Any], bytes]:
    details = require_regular_secure(path, label, owner_uid)
    if details.st_size > max_bytes:
        raise AdoptError(f"{label} is unexpectedly large: {details.st_size} bytes")
    try:
        data = path.read_bytes()
        payload = strict_json_loads(data, label)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AdoptError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AdoptError(f"{label} JSON root must be an object")
    return payload, data


def path_exists_no_follow(path: Path) -> bool:
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise AdoptError(f"cannot inspect path: {path}: {exc}") from exc


def resolved_existing(path: Path, label: str) -> Path:
    try:
        return path.resolve(strict=True)
    except OSError as exc:
        raise AdoptError(f"cannot resolve {label}: {path}: {exc}") from exc


def path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def capture_output_path(args: argparse.Namespace) -> Path:
    """Resolve a new capture path and keep it outside every read-only input."""
    output = args.output
    if output.name in {"", ".", ".."}:
        raise AdoptError("capture output must name a file")
    parent = resolved_existing(output.parent, "capture output parent")
    try:
        if not parent.is_dir():
            raise AdoptError(f"capture output parent is not a directory: {parent}")
    except OSError as exc:
        raise AdoptError(f"cannot inspect capture output parent: {parent}: {exc}") from exc
    destination = parent / output.name
    if path_exists_no_follow(destination):
        raise AdoptError(f"capture output already exists: {destination}")

    protected_roots = {
        "configfs root": args.configfs_root,
        "proc root": args.proc_root,
        "sys root": args.sys_root,
        "dev root": args.dev_root,
        "profile root": args.profile_root,
    }
    for label, root in protected_roots.items():
        canonical_root = resolved_existing(root, label)
        if path_is_within(destination, canonical_root):
            raise AdoptError(f"capture output is inside read-only {label}: {destination}")

    protected_files = {
        "E1 manifest": args.manifest,
        "runtime profile marker": args.runtime_profile_marker,
        "installed helper": args.helper,
    }
    for label, source in protected_files.items():
        canonical_source = resolved_existing(source, label)
        if destination == canonical_source:
            raise AdoptError(f"capture output aliases read-only {label}: {destination}")
    return destination


def write_exclusive_0600(path: Path, data: bytes) -> None:
    """Create one file atomically with O_EXCL; remove only our inode on failure."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd: int | None = None
    created: tuple[int, int] | None = None
    try:
        fd = os.open(path, flags, 0o600)
        details = os.fstat(fd)
        created = (details.st_dev, details.st_ino)
        if not stat.S_ISREG(details.st_mode):
            raise AdoptError(f"capture output is not a regular file: {path}")
        os.fchmod(fd, 0o600)
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise AdoptError(f"short write while creating capture output: {path}")
            view = view[written:]
        os.fsync(fd)
    except FileExistsError as exc:
        raise AdoptError(f"capture output already exists: {path}") from exc
    except OSError as exc:
        raise AdoptError(f"cannot create capture output: {path}: {exc}") from exc
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if sys.exc_info()[0] is not None and created is not None:
            try:
                current = path.lstat()
                if (current.st_dev, current.st_ino) == created:
                    path.unlink()
            except OSError:
                pass


def safe_relative_path(raw: object, label: str) -> str:
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise AdoptError(f"{label} is invalid")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise AdoptError(f"{label} is not a safe relative path: {raw!r}")
    normalized = path.as_posix()
    if normalized != raw:
        raise AdoptError(f"{label} is not normalized: {raw!r}")
    return normalized


def normalized_architecture(value: str) -> str:
    aliases = {
        "arm64": "aarch64",
        "aarch64": "aarch64",
        "x86_64": "x86_64",
        "amd64": "x86_64",
    }
    return aliases.get(value.lower(), value.lower())


def architectures_match(left: str, right: str) -> bool:
    return normalized_architecture(left) == normalized_architecture(right)


def commits_match(left: object, right: object) -> bool:
    a = str(left).lower()
    b = str(right).lower()
    if not re.fullmatch(r"[0-9a-f]{7,64}", a) or not re.fullmatch(r"[0-9a-f]{7,64}", b):
        return False
    return a.startswith(b) or b.startswith(a)


def normalize_bool(value: object, label: str) -> str:
    text = str(value).lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return "1"
    if text in {"0", "false", "no", "off", "disabled", ""}:
        return "0"
    raise AdoptError(f"{label} is not a boolean")


def normalize_usb_id(value: object, label: str) -> str:
    text = str(value).lower()
    if not re.fullmatch(r"0x[0-9a-f]{4}", text):
        raise AdoptError(f"{label} must be 0x followed by four hex digits")
    return text


def normalize_identity(identity: object) -> dict[str, str]:
    values = require_object(identity, "identity")
    unexpected = sorted(set(values) - IDENTITY_KEYS)
    if unexpected:
        raise AdoptError("identity contains unsupported keys: " + ", ".join(unexpected))
    result: dict[str, str] = {}
    for key in sorted(IDENTITY_KEYS):
        if key == "HIDLOOM_USB_SERIAL_SUFFIX":
            raw = values.get(key, "")
        elif key not in values:
            raise AdoptError(f"identity is missing {key}")
        else:
            raw = values[key]
        if (
            not isinstance(raw, str)
            or not IDENTITY_VALUE_RE.fullmatch(raw)
            or "__HOSTNAME__" in raw
        ):
            raise AdoptError(f"identity value is invalid: {key}")
        result[key] = raw
    for key in (
        "HIDLOOM_USB_MANUFACTURER",
        "HIDLOOM_USB_PRODUCT_NAME",
        "HIDLOOM_USB_SERIAL",
    ):
        if not result[key]:
            raise AdoptError(f"identity value must not be empty: {key}")
    for key in ("HIDLOOM_USB_VENDOR_ID", "HIDLOOM_USB_PRODUCT_ID"):
        result[key] = normalize_usb_id(result[key], key)
    for key in ("HIDLOOM_USB_US_SUB_KEYBOARD", "HIDLOOM_WINDOWS_IME_CUSTOM_HID"):
        result[key] = normalize_bool(result[key], key)
    return result


def effective_identity(proc_root: Path) -> dict[str, str]:
    try:
        hostname = (proc_root / "sys/kernel/hostname").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise AdoptError(f"cannot read kernel hostname: {exc}") from exc
    if not hostname or "\x00" in hostname:
        raise AdoptError("kernel hostname is invalid")
    raw = dict(IDENTITY_DEFAULTS)
    raw["HIDLOOM_USB_MANUFACTURER"] = hostname
    raw["HIDLOOM_USB_PRODUCT_NAME"] = hostname
    for key in IDENTITY_KEYS:
        value = os.environ.get(key)
        if value is not None and value != "":
            raw[key] = value
    for key in (
        "HIDLOOM_USB_MANUFACTURER",
        "HIDLOOM_USB_PRODUCT_NAME",
        "HIDLOOM_USB_SERIAL",
    ):
        if raw[key] == "__HOSTNAME__":
            raw[key] = hostname
    return normalize_identity(raw)


def identity_serial(identity: dict[str, str]) -> str:
    serial = identity["HIDLOOM_USB_SERIAL"]
    suffix = identity["HIDLOOM_USB_SERIAL_SUFFIX"]
    return f"{serial}:{suffix}" if suffix else serial


def identity_env_bytes(identity: dict[str, str]) -> bytes:
    lines = ["# Generated by rpi_os_early_initramfs.py; do not edit."]
    for key in sorted(identity):
        lines.append(f"{key}='{identity[key]}'")
        lines.append(f"export {key}")
    return ("\n".join(lines) + "\n").encode()


def overlay_file(manifest: dict[str, Any], relative: str) -> dict[str, Any]:
    overlay = require_object(manifest.get("overlay"), "accepted manifest overlay")
    files = overlay.get("files")
    if not isinstance(files, list):
        raise AdoptError("accepted manifest overlay files must be a list")
    matches = [item for item in files if isinstance(item, dict) and item.get("path") == relative]
    if len(matches) != 1:
        raise AdoptError(f"accepted manifest must contain exactly one {relative}")
    return matches[0]


def validate_e1_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate the self-contained E1 fields needed by capture and verify."""
    if manifest.get("schema") != IMAGE_SCHEMA:
        raise AdoptError("E1 manifest schema mismatch")
    if "adopt" in manifest:
        raise AdoptError("input E1 manifest already contains an adopt extension")
    kernel = require_string(manifest.get("kernel_release"), "kernel release")
    source = require_string(manifest.get("source"), "source identifier")
    identity = normalize_identity(manifest.get("identity"))
    if manifest.get("identity") != identity:
        raise AdoptError("E1 identity is not in canonical normalized form")
    profile = require_object(manifest.get("profile"), "profile contract")
    require_string(profile.get("id"), "profile id")
    require_sha256(profile.get("sha256"), "profile sha256")
    if set(profile) != {"id", "sha256"}:
        raise AdoptError("profile contract contains unsupported fields")

    helper = require_object(manifest.get("helper"), "helper contract")
    architecture = require_string(helper.get("architecture"), "helper architecture")
    if helper.get("static") is not True:
        raise AdoptError("E1 helper is not declared static")
    helper_sha = require_sha256(helper.get("sha256"), "helper sha256")
    if set(helper) != {"architecture", "static", "sha256"}:
        raise AdoptError("helper contract contains unsupported fields")

    descriptors = require_object(manifest.get("descriptors"), "descriptor contract")
    reports = require_object(descriptors.get("reports"), "descriptor reports")
    if set(reports) != set(E1_REPORT_FUNCTIONS):
        raise AdoptError("E1 descriptor report set is unsupported")
    for report_name, raw_record in reports.items():
        record = require_object(raw_record, f"descriptor {report_name}")
        size = record.get("size")
        digest = require_sha256(record.get("sha256"), f"descriptor {report_name} sha256")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise AdoptError(f"descriptor {report_name} size is invalid")
        if record != {"size": size, "sha256": digest}:
            raise AdoptError(f"descriptor {report_name} contains unsupported fields")
    descriptor_sha = require_sha256(
        descriptors.get("contract_sha256"), "descriptor contract sha256"
    )
    if canonical_sha256(reports) != descriptor_sha:
        raise AdoptError("descriptor records do not match their contract hash")
    if set(descriptors) != {"contract_sha256", "reports"}:
        raise AdoptError("descriptor contract contains unsupported fields")

    declared = require_object(manifest.get("runtime_contract"), "runtime contract")
    declared_sha = require_sha256(declared.get("sha256"), "runtime contract sha256")
    content = {key: value for key, value in declared.items() if key != "sha256"}
    contract_bytes = (json.dumps(content, indent=2, sort_keys=True) + "\n").encode()
    if sha256_bytes(contract_bytes) != declared_sha:
        raise AdoptError("runtime contract content does not match its SHA-256")
    if content.get("schema") != RUNTIME_CONTRACT_SCHEMA:
        raise AdoptError("runtime contract schema mismatch")
    if (
        content.get("source") != source
        or content.get("kernel_release") != kernel
        or content.get("profile") != profile
        or content.get("helper_sha256") != helper_sha
        or content.get("descriptor_contract_sha256") != descriptor_sha
    ):
        raise AdoptError("runtime contract differs from E1 manifest fields")
    identity_sha = require_sha256(content.get("identity_sha256"), "identity sha256")
    contract_item = overlay_file(manifest, "conf/hidloom-early-contract.json")
    if contract_item.get("sha256") != declared_sha or contract_item.get("size") != len(
        contract_bytes
    ):
        raise AdoptError("runtime contract differs from overlay inventory")
    identity_item = overlay_file(manifest, "conf/hidloom-early-usb.env")
    expected_identity_bytes = identity_env_bytes(identity)
    if (
        require_sha256(identity_item.get("sha256"), "identity overlay sha256")
        != identity_sha
        or identity_sha != sha256_bytes(expected_identity_bytes)
        or identity_item.get("size") != len(expected_identity_bytes)
    ):
        raise AdoptError("runtime identity hash differs from overlay inventory")
    helper_item = overlay_file(
        manifest, "usr/lib/hidloom/early/hidloom-usb-gadget-fast"
    )
    if require_sha256(helper_item.get("sha256"), "helper overlay sha256") != helper_sha:
        raise AdoptError("helper hash differs from overlay inventory")
    return {
        "kernel_release": kernel,
        "source": source,
        "identity": identity,
        "profile": profile,
        "helper": helper,
        "descriptors": descriptors,
        "runtime_contract": declared,
        "architecture": architecture,
    }


def validate_runtime_contract(
    runtime: dict[str, Any],
    accepted: dict[str, Any],
    runtime_bytes: bytes,
) -> None:
    if runtime.get("schema") != RUNTIME_CONTRACT_SCHEMA:
        raise AdoptError("runtime contract schema mismatch")
    accepted_contract = require_object(
        accepted.get("runtime_contract"), "accepted runtime contract"
    )
    declared_sha = require_sha256(accepted_contract.get("sha256"), "runtime contract sha256")
    actual_sha = sha256_bytes(runtime_bytes)
    if actual_sha != declared_sha:
        raise AdoptError("runtime contract hash does not match accepted manifest")
    expected_content = {key: value for key, value in accepted_contract.items() if key != "sha256"}
    if runtime != expected_content:
        raise AdoptError("runtime contract content differs from accepted manifest")
    item = overlay_file(accepted, "conf/hidloom-early-contract.json")
    if item.get("sha256") != actual_sha or item.get("size") != len(runtime_bytes):
        raise AdoptError("runtime contract does not match accepted overlay inventory")


def validate_marker_shape(marker: dict[str, Any]) -> None:
    if marker.get("schema") != MARKER_SCHEMA or marker.get("state") != "bound":
        raise AdoptError("runtime marker is not a bound E1 gadget marker")
    require_sha256(
        marker.get("runtime_contract_sha256"),
        "runtime marker contract sha256",
    )
    require_string(marker.get("kernel_release"), "runtime marker kernel release")
    uptime = marker.get("ready_uptime_seconds")
    if (
        not isinstance(uptime, (int, float))
        or isinstance(uptime, bool)
        or not math.isfinite(uptime)
        or uptime < 0
    ):
        raise AdoptError("runtime marker ready uptime is invalid")
    if set(marker) != {
        "schema",
        "state",
        "kernel_release",
        "runtime_contract_sha256",
        "ready_uptime_seconds",
    }:
        raise AdoptError("runtime marker contains unsupported fields")


def validate_marker(
    marker: dict[str, Any],
    accepted: dict[str, Any],
    runtime_sha: str,
) -> None:
    validate_marker_shape(marker)
    if marker.get("runtime_contract_sha256") != runtime_sha:
        raise AdoptError("runtime marker contract hash mismatch")
    if marker.get("kernel_release") != accepted.get("kernel_release"):
        raise AdoptError("runtime marker kernel release mismatch")


def parse_dpkg_status(path: Path, owner_uid: int) -> dict[str, dict[str, str]]:
    require_regular_secure(path, "dpkg status", owner_uid)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise AdoptError(f"cannot read dpkg status: {path}: {exc}") from exc
    result: dict[str, dict[str, str]] = {}
    for paragraph in re.split(r"\n\s*\n", text.strip()):
        fields: dict[str, str] = {}
        current = ""
        for line in paragraph.splitlines():
            if line.startswith((" ", "\t")) and current:
                fields[current] += "\n" + line[1:]
                continue
            if ":" not in line:
                raise AdoptError("dpkg status contains an invalid field")
            current, value = line.split(":", 1)
            fields[current] = value.strip()
        package = fields.get("Package")
        if package:
            if package in result:
                raise AdoptError(f"dpkg status contains duplicate package: {package}")
            result[package] = fields
    return result


def validate_package_source(
    package_root: Path, accepted_source: object, owner_uid: int
) -> None:
    manifest, _ = read_secure_json(
        package_root / "var/lib/hidloom/package-manifest.json",
        "installed package manifest",
        owner_uid=owner_uid,
    )
    if manifest.get("schema") != PACKAGE_MANIFEST_SCHEMA:
        raise AdoptError("installed package manifest schema mismatch")
    if not commits_match(manifest.get("git_sha"), accepted_source):
        raise AdoptError("installed package source does not match early image")


def installed_package_contract(
    status: dict[str, dict[str, str]],
    name: str,
    role: str,
    accepted_architecture: str,
    *,
    expected_version: str | None = None,
) -> dict[str, str]:
    require_string(name, f"{role} package name", SAFE_PACKAGE_RE)
    record = status.get(name)
    if record is None or record.get("Status") != "install ok installed":
        raise AdoptError(f"required package is not installed: {name}")
    version = require_string(record.get("Version"), f"{role} package version")
    if expected_version is not None and version != expected_version:
        raise AdoptError(f"package version mismatch: {name}")
    if not architectures_match(record.get("Architecture", ""), accepted_architecture):
        raise AdoptError(f"package architecture mismatch: {name}")
    return {"name": name, "version": version}


def capture_package_contract(
    package_root: Path,
    core_name: str,
    profile_name: str,
    accepted_source: object,
    accepted_architecture: str,
    owner_uid: int,
) -> dict[str, dict[str, str]]:
    status = parse_dpkg_status(package_root / "var/lib/dpkg/status", owner_uid)
    core = installed_package_contract(
        status, core_name, "core", accepted_architecture
    )
    profile = installed_package_contract(
        status, profile_name, "profile", accepted_architecture
    )
    if core["version"] != profile["version"]:
        raise AdoptError("core and profile package versions differ")
    validate_package_source(package_root, accepted_source, owner_uid)
    return {"core": core, "profile": profile}


def validate_packages(
    package_root: Path,
    packages_contract: object,
    accepted_source: object,
    accepted_architecture: str,
    owner_uid: int,
) -> None:
    packages = require_object(packages_contract, "package contract")
    if set(packages) != {"core", "profile"}:
        raise AdoptError("package contract must contain exactly core and profile")
    status = parse_dpkg_status(package_root / "var/lib/dpkg/status", owner_uid)
    versions: set[str] = set()
    for role in ("core", "profile"):
        expected = require_object(packages[role], f"{role} package contract")
        name = require_string(expected.get("name"), f"{role} package name", SAFE_PACKAGE_RE)
        version = require_string(expected.get("version"), f"{role} package version")
        actual = installed_package_contract(
            status,
            name,
            role,
            accepted_architecture,
            expected_version=version,
        )
        versions.add(actual["version"])
    if len(versions) != 1:
        raise AdoptError("core and profile package versions differ")

    validate_package_source(package_root, accepted_source, owner_uid)


def validate_profile(
    profile_root: Path,
    runtime_profile_marker: Path,
    profile_contract: object,
    owner_uid: int,
) -> None:
    profile = require_object(profile_contract, "profile contract")
    profile_id = require_string(profile.get("id"), "profile id")
    expected_sha = require_sha256(profile.get("sha256"), "profile sha256")
    installed_path = profile_root / profile_id / "profile.json"
    require_regular_secure(installed_path, "installed profile", owner_uid)
    try:
        installed_bytes = installed_path.read_bytes()
    except OSError as exc:
        raise AdoptError(f"cannot read installed profile: {exc}") from exc
    if sha256_bytes(installed_bytes) != expected_sha:
        raise AdoptError("installed profile hash mismatch")
    try:
        installed = strict_json_loads(installed_bytes, "installed profile")
    except json.JSONDecodeError as exc:
        raise AdoptError(f"installed profile is invalid JSON: {exc}") from exc
    if not isinstance(installed, dict) or installed.get("schema") != PROFILE_SCHEMA:
        raise AdoptError("installed profile schema mismatch")
    if installed.get("id") != profile_id:
        raise AdoptError("installed profile id mismatch")
    profile_kind = require_string(installed.get("kind"), "installed profile kind")
    marker, _ = read_secure_json(
        runtime_profile_marker, "runtime device profile marker", owner_uid
    )
    if (
        marker.get("schema") != PROFILE_SCHEMA
        or marker.get("id") != profile_id
        or marker.get("kind") != profile_kind
    ):
        raise AdoptError("runtime device profile marker mismatch")


def validate_helper(helper: Path, expected_sha: object, owner_uid: int) -> None:
    require_regular_secure(helper, "installed gadget helper", owner_uid)
    try:
        data = helper.read_bytes()
    except OSError as exc:
        raise AdoptError(f"cannot read installed gadget helper: {exc}") from exc
    if sha256_bytes(data) != require_sha256(expected_sha, "helper sha256"):
        raise AdoptError("installed gadget helper hash mismatch")


def normalized_symlink_target(gadget: Path, link: Path) -> str:
    try:
        raw = os.readlink(link)
    except OSError as exc:
        raise AdoptError(f"cannot read configfs symlink: {link}: {exc}") from exc
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = link.parent / candidate
    try:
        resolved = candidate.resolve(strict=True)
        relative = resolved.relative_to(gadget.resolve(strict=True)).as_posix()
    except (OSError, ValueError) as exc:
        raise AdoptError(f"configfs symlink escapes or is broken: {link}: {exc}") from exc
    return safe_relative_path(relative, f"symlink target for {link}")


def snapshot_configfs_entries(gadget: Path) -> dict[str, dict[str, Any]]:
    """Return a byte-exact, non-following snapshot of one configfs gadget."""
    try:
        root_stat = gadget.lstat()
    except OSError as exc:
        raise AdoptError(f"cannot stat configfs gadget: {gadget}: {exc}") from exc
    if not stat.S_ISDIR(root_stat.st_mode):
        raise AdoptError(f"configfs gadget is not a directory: {gadget}")
    entries: dict[str, dict[str, Any]] = {}

    def walk(directory: Path) -> None:
        try:
            children = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as exc:
            raise AdoptError(f"cannot scan configfs directory: {directory}: {exc}") from exc
        for child in children:
            path = Path(child.path)
            relative = path.relative_to(gadget).as_posix()
            safe_relative_path(relative, "configfs entry")
            try:
                details = child.stat(follow_symlinks=False)
            except OSError as exc:
                raise AdoptError(f"cannot stat configfs entry: {path}: {exc}") from exc
            if stat.S_ISLNK(details.st_mode):
                entries[relative] = {
                    "kind": "symlink",
                    "target": normalized_symlink_target(gadget, path),
                }
            elif stat.S_ISDIR(details.st_mode):
                entries[relative] = {"kind": "directory"}
                walk(path)
            elif stat.S_ISREG(details.st_mode):
                try:
                    data = path.read_bytes()
                except OSError as exc:
                    raise AdoptError(f"cannot read configfs attribute: {path}: {exc}") from exc
                entries[relative] = {
                    "kind": "file",
                    "size": len(data),
                    "sha256": sha256_bytes(data),
                }
            else:
                raise AdoptError(f"unsupported configfs entry type: {path}")
    walk(gadget)
    return entries


def validate_contract_entries(entries: object) -> dict[str, dict[str, Any]]:
    payload = require_object(entries, "configfs entry contract")
    normalized: dict[str, dict[str, Any]] = {}
    for raw_path, raw_entry in payload.items():
        path = safe_relative_path(raw_path, "configfs contract path")
        entry = require_object(raw_entry, f"configfs contract entry {path}")
        kind = entry.get("kind")
        if kind == "directory":
            if entry != {"kind": "directory"}:
                raise AdoptError(f"directory contract has extra fields: {path}")
        elif kind == "symlink":
            target = safe_relative_path(entry.get("target"), f"symlink target {path}")
            if entry != {"kind": "symlink", "target": target}:
                raise AdoptError(f"symlink contract has invalid fields: {path}")
        elif kind == "file":
            size = entry.get("size")
            digest = require_sha256(entry.get("sha256"), f"configfs sha256 {path}")
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise AdoptError(f"configfs file size is invalid: {path}")
            if entry != {"kind": "file", "size": size, "sha256": digest}:
                raise AdoptError(f"file contract has invalid fields: {path}")
        else:
            raise AdoptError(f"configfs entry kind is invalid: {path}")
        normalized[path] = entry
    return normalized


def read_config_text(path: Path, label: str) -> str:
    try:
        data = path.read_bytes()
        return data.decode("utf-8").rstrip("\r\n\x00")
    except (OSError, UnicodeError) as exc:
        raise AdoptError(f"cannot read {label}: {path}: {exc}") from exc


def validate_ep0_max_packet_size(gadget: Path) -> int:
    """Require a real configfs EP0 attribute with a valid kernel value."""
    path = gadget / EP0_MAX_PACKET_SIZE_ENTRY
    try:
        details = path.lstat()
    except OSError as exc:
        raise AdoptError(f"cannot inspect configfs bMaxPacketSize0: {path}: {exc}") from exc
    if not stat.S_ISREG(details.st_mode):
        raise AdoptError(f"configfs bMaxPacketSize0 is not a regular file: {path}")

    text = read_config_text(path, "configfs bMaxPacketSize0")
    if re.fullmatch(r"0[xX][0-9a-fA-F]{1,2}", text):
        value = int(text, 16)
    elif re.fullmatch(r"[0-9]{1,3}", text):
        value = int(text, 10)
    else:
        raise AdoptError("configfs bMaxPacketSize0 is malformed")
    if value not in VALID_EP0_MAX_PACKET_SIZE_VALUES:
        raise AdoptError(f"configfs bMaxPacketSize0 is invalid: {text!r}")
    return value


def volatile_configfs_entries(ordered_functions: list[str]) -> list[str]:
    return [
        "UDC",
        EP0_MAX_PACKET_SIZE_ENTRY,
        *[f"functions/{function}/dev" for function in ordered_functions],
    ]


def snapshots_match_allowing_ep0_normalization(
    first: dict[str, dict[str, Any]],
    second: dict[str, dict[str, Any]],
) -> bool:
    """Compare every configfs entry except the kernel-normalized EP0 value."""
    return (
        {
            path: entry
            for path, entry in first.items()
            if path != EP0_MAX_PACKET_SIZE_ENTRY
        }
        == {
            path: entry
            for path, entry in second.items()
            if path != EP0_MAX_PACKET_SIZE_ENTRY
        }
    )


def validate_stably_unbound_gadget(gadget: Path) -> None:
    """Accept a normal stop residue only when it is real, empty, and stable."""
    try:
        gadget_details = gadget.lstat()
    except OSError as exc:
        raise AdoptError(f"cannot inspect unmarked configfs gadget: {gadget}: {exc}") from exc
    if not stat.S_ISDIR(gadget_details.st_mode):
        raise AdoptError(f"unmarked configfs gadget is not a real directory: {gadget}")
    try:
        udc_details = (gadget / "UDC").lstat()
    except OSError as exc:
        raise AdoptError(f"cannot inspect unmarked configfs UDC: {gadget / 'UDC'}: {exc}") from exc
    if not stat.S_ISREG(udc_details.st_mode):
        raise AdoptError(f"unmarked configfs UDC is not a regular attribute: {gadget / 'UDC'}")

    first_udc = read_config_text(gadget / "UDC", "unmarked gadget UDC").strip()
    first_snapshot = snapshot_configfs_entries(gadget)
    second_udc = read_config_text(gadget / "UDC", "unmarked gadget UDC").strip()
    second_snapshot = snapshot_configfs_entries(gadget)
    if any(
        snapshot.get("UDC", {}).get("kind") != "file"
        for snapshot in (first_snapshot, second_snapshot)
    ):
        raise AdoptError("unmarked configfs UDC stopped being a regular attribute")
    if first_udc or second_udc:
        raise AdoptError("unmarked configfs gadget is still bound")
    if first_snapshot != second_snapshot:
        raise AdoptError("unmarked configfs gadget changed while checking its unbound state")


def expected_functions(identity: dict[str, str]) -> list[str]:
    result = ["hid.usb0", "hid.usb1"]
    if identity["HIDLOOM_USB_US_SUB_KEYBOARD"] == "1":
        result.append("hid.usb2")
    if identity["HIDLOOM_WINDOWS_IME_CUSTOM_HID"] == "1":
        result.append("hid.usb4")
    return result


def validate_identity_against_configfs(gadget: Path, identity: dict[str, str]) -> None:
    values = {
        "idVendor": normalize_usb_id(
            read_config_text(gadget / "idVendor", "configfs idVendor"), "live idVendor"
        ),
        "idProduct": normalize_usb_id(
            read_config_text(gadget / "idProduct", "configfs idProduct"), "live idProduct"
        ),
    }
    if values["idVendor"] != identity["HIDLOOM_USB_VENDOR_ID"]:
        raise AdoptError("live USB vendor ID differs from effective identity")
    if values["idProduct"] != identity["HIDLOOM_USB_PRODUCT_ID"]:
        raise AdoptError("live USB product ID differs from effective identity")
    expected_strings = {
        "manufacturer": identity["HIDLOOM_USB_MANUFACTURER"],
        "product": identity["HIDLOOM_USB_PRODUCT_NAME"],
        "serialnumber": identity_serial(identity),
    }
    for language in ("0x409", "0x411"):
        for name, expected in expected_strings.items():
            actual = read_config_text(
                gadget / "strings" / language / name,
                f"configfs {language} {name}",
            )
            if actual != expected:
                raise AdoptError(f"live USB {language} {name} differs from identity")


def parse_major_minor(value: str, label: str) -> tuple[int, int]:
    match = re.fullmatch(r"([0-9]+):([0-9]+)", value.strip())
    if not match:
        raise AdoptError(f"{label} is not major:minor")
    return int(match.group(1)), int(match.group(2))


def device_major_minor(
    path: Path, *, allow_regular_fixture: bool
) -> tuple[int, int]:
    try:
        details = path.lstat()
    except OSError as exc:
        raise AdoptError(f"cannot stat HID device node: {path}: {exc}") from exc
    if stat.S_ISCHR(details.st_mode):
        return os.major(details.st_rdev), os.minor(details.st_rdev)
    if allow_regular_fixture and stat.S_ISREG(details.st_mode):
        return parse_major_minor(read_config_text(path, "fixture HID device"), str(path))
    raise AdoptError(f"HID device path is not a character device: {path}")


def capture_gadget_contract(
    configfs_root: Path,
    sys_root: Path,
    dev_root: Path,
    gadget_name: str,
    config_name: str,
    identity: dict[str, str],
    descriptors: dict[str, Any],
    runtime_descriptor_sha256: object,
    *,
    allow_regular_dev_fixtures: bool,
) -> dict[str, Any]:
    name = require_string(gadget_name, "gadget name")
    config = require_string(config_name, "gadget config name")
    gadget = configfs_root / name
    entries = snapshot_configfs_entries(gadget)
    ordered = expected_functions(identity)

    functions_dir = gadget / "functions"
    try:
        function_dirs = sorted(
            path.name
            for path in functions_dir.iterdir()
            if path.is_dir() and not path.is_symlink()
        )
        config_dirs = sorted(
            path.name
            for path in (gadget / "configs").iterdir()
            if path.is_dir() and not path.is_symlink()
        )
        config_links = sorted(
            path.name for path in (gadget / "configs" / config).iterdir() if path.is_symlink()
        )
    except OSError as exc:
        raise AdoptError(f"cannot inspect live gadget layout: {exc}") from exc
    if function_dirs != sorted(ordered):
        raise AdoptError("live normal gadget function set differs from E1 identity")
    if config_dirs != [config]:
        raise AdoptError("live normal gadget config set is not exactly the requested config")
    if config_links != sorted(ordered):
        raise AdoptError("live normal gadget function links differ from E1 identity")
    for function in ordered:
        target = normalized_symlink_target(gadget, gadget / "configs" / config / function)
        if target != f"functions/{function}":
            raise AdoptError(f"live normal gadget symlink target mismatch: {function}")

    udc = read_config_text(gadget / "UDC", "bound UDC")
    require_string(udc, "UDC name")
    try:
        if not (sys_root / "class/udc" / udc).is_dir():
            raise AdoptError("live normal gadget UDC does not exist")
    except OSError as exc:
        raise AdoptError(f"cannot inspect live normal UDC: {exc}") from exc

    try:
        hidg_paths = sorted(
            path for path in dev_root.iterdir() if re.fullmatch(r"hidg[0-9]+", path.name)
        )
    except OSError as exc:
        raise AdoptError(f"cannot scan HID device nodes: {dev_root}: {exc}") from exc
    node_numbers = {
        path.name: device_major_minor(
            path, allow_regular_fixture=allow_regular_dev_fixtures
        )
        for path in hidg_paths
    }
    dev_nodes: dict[str, str] = {}
    for function in ordered:
        function_number = parse_major_minor(
            read_config_text(
                gadget / "functions" / function / "dev", f"{function} device number"
            ),
            f"{function} device number",
        )
        matches = sorted(name for name, number in node_numbers.items() if number == function_number)
        if len(matches) != 1:
            raise AdoptError(f"cannot uniquely map {function} to a HID device node")
        expected_node = "hidg" + function.removeprefix("hid.usb")
        if matches[0] != expected_node:
            raise AdoptError(f"unexpected production device-node mapping: {function}")
        dev_nodes[function] = matches[0]
    if set(node_numbers) != set(dev_nodes.values()):
        raise AdoptError("unexpected extra HID device node is present")

    validate_ep0_max_packet_size(gadget)
    volatile = volatile_configfs_entries(ordered)
    for relative in volatile:
        if entries.get(relative, {}).get("kind") != "file":
            raise AdoptError(f"dynamic configfs attribute is missing: {relative}")
    contract = {
        "schema": GADGET_CONTRACT_SCHEMA,
        "name": name,
        "udc": udc,
        "config_name": config,
        "ordered_functions": ordered,
        "volatile_entries": volatile,
        "dev_nodes": dev_nodes,
        "entries": {
            path: value for path, value in entries.items() if path not in set(volatile)
        },
    }
    validate_identity_against_configfs(gadget, identity)
    validate_report_descriptors(
        gadget,
        descriptors,
        runtime_descriptor_sha256,
        ordered,
    )
    validate_gadget_contract(
        configfs_root,
        sys_root,
        dev_root,
        contract,
        identity,
        allow_regular_dev_fixtures=allow_regular_dev_fixtures,
    )
    return contract


def validate_gadget_contract(
    configfs_root: Path,
    sys_root: Path,
    dev_root: Path,
    gadget_contract: object,
    identity: dict[str, str],
    *,
    allow_regular_dev_fixtures: bool,
) -> tuple[str, str, list[str]]:
    contract = require_object(gadget_contract, "gadget contract")
    if contract.get("schema") != GADGET_CONTRACT_SCHEMA:
        raise AdoptError("gadget snapshot schema mismatch")
    if set(contract) != {
        "schema",
        "name",
        "udc",
        "config_name",
        "ordered_functions",
        "volatile_entries",
        "dev_nodes",
        "entries",
    }:
        raise AdoptError("gadget snapshot contains unsupported fields")
    name = require_string(contract.get("name"), "gadget name")
    udc = require_string(contract.get("udc"), "UDC name")
    config_name = require_string(contract.get("config_name"), "gadget config name")
    ordered = contract.get("ordered_functions")
    if not isinstance(ordered, list) or not ordered or not all(
        isinstance(item, str) and FUNCTION_RE.fullmatch(item) for item in ordered
    ) or len(set(ordered)) != len(ordered):
        raise AdoptError("ordered function contract is invalid")
    if ordered != expected_functions(identity):
        raise AdoptError("ordered function contract differs from effective identity")
    dev_nodes = require_object(contract.get("dev_nodes"), "HID device-node contract")
    if set(dev_nodes) != set(ordered):
        raise AdoptError("HID device-node contract does not match functions")
    for function, node in dev_nodes.items():
        if not isinstance(node, str) or not re.fullmatch(r"hidg[0-9]+", node):
            raise AdoptError(f"invalid device node for {function}")

    gadget = configfs_root / name
    actual_entries = snapshot_configfs_entries(gadget)
    validate_ep0_max_packet_size(gadget)
    volatile = volatile_configfs_entries(ordered)
    if contract.get("volatile_entries") != volatile:
        raise AdoptError("volatile configfs entry contract mismatch")
    for relative in volatile:
        entry = actual_entries.get(relative)
        if not isinstance(entry, dict) or entry.get("kind") != "file":
            raise AdoptError(f"volatile configfs attribute is missing: {relative}")
    static_actual = {
        path: value for path, value in actual_entries.items() if path not in set(volatile)
    }
    static_expected = validate_contract_entries(contract.get("entries"))
    if static_actual != static_expected:
        missing = sorted(set(static_expected) - set(static_actual))
        extra = sorted(set(static_actual) - set(static_expected))
        changed = sorted(
            path
            for path in set(static_actual) & set(static_expected)
            if static_actual[path] != static_expected[path]
        )
        detail = []
        if missing:
            detail.append("missing=" + ",".join(missing))
        if extra:
            detail.append("extra=" + ",".join(extra))
        if changed:
            detail.append("changed=" + ",".join(changed))
        raise AdoptError("configfs snapshot mismatch: " + "; ".join(detail))

    live_udc = read_config_text(gadget / "UDC", "bound UDC")
    if not live_udc or live_udc != udc:
        raise AdoptError("live gadget is not bound to the contracted UDC")
    udc_path = sys_root / "class/udc" / udc
    try:
        if not udc_path.is_dir():
            raise AdoptError(f"contracted UDC is absent: {udc_path}")
    except OSError as exc:
        raise AdoptError(f"cannot inspect contracted UDC: {udc_path}: {exc}") from exc

    functions_dir = gadget / "functions"
    configs_dir = gadget / "configs" / config_name
    actual_function_dirs = sorted(
        path.name for path in functions_dir.iterdir() if path.is_dir() and not path.is_symlink()
    )
    if actual_function_dirs != sorted(ordered):
        raise AdoptError("live configfs function set mismatch")
    actual_links = sorted(path.name for path in configs_dir.iterdir() if path.is_symlink())
    if actual_links != sorted(ordered):
        raise AdoptError("live configfs function symlink set mismatch")
    for function in ordered:
        target = normalized_symlink_target(gadget, configs_dir / function)
        if target != f"functions/{function}":
            raise AdoptError(f"live configfs symlink target mismatch: {function}")
        function_dev = parse_major_minor(
            read_config_text(
                gadget / "functions" / function / "dev", f"{function} device number"
            ),
            f"{function} device number",
        )
        node_dev = device_major_minor(
            dev_root / str(dev_nodes[function]),
            allow_regular_fixture=allow_regular_dev_fixtures,
        )
        if function_dev != node_dev:
            raise AdoptError(f"device-node mapping mismatch: {function}")

    validate_identity_against_configfs(gadget, identity)
    final_entries = snapshot_configfs_entries(gadget)
    validate_ep0_max_packet_size(gadget)
    if not snapshots_match_allowing_ep0_normalization(actual_entries, final_entries):
        raise AdoptError("configfs changed while it was being verified")
    return name, udc, list(ordered)


def validate_report_descriptors(
    gadget: Path,
    accepted_descriptors: object,
    runtime_descriptor_sha256: object,
    ordered_functions: list[str],
) -> None:
    descriptors = require_object(accepted_descriptors, "accepted descriptor contract")
    reports = require_object(descriptors.get("reports"), "accepted descriptor reports")
    declared_contract_sha = require_sha256(
        descriptors.get("contract_sha256"), "accepted descriptor contract sha256"
    )
    if canonical_sha256(reports) != declared_contract_sha:
        raise AdoptError("accepted descriptor records do not match their contract hash")
    if declared_contract_sha != require_sha256(
        runtime_descriptor_sha256, "runtime descriptor contract sha256"
    ):
        raise AdoptError("runtime descriptor contract differs from accepted manifest")
    uncontracted = sorted(set(ordered_functions) - set(E1_REPORT_FUNCTIONS.values()))
    if uncontracted:
        raise AdoptError(
            "E1 has no descriptor contract for function(s): " + ", ".join(uncontracted)
        )
    for report_name, function in E1_REPORT_FUNCTIONS.items():
        if function not in ordered_functions:
            continue
        record = require_object(reports.get(report_name), f"descriptor {report_name}")
        expected_size = record.get("size")
        expected_sha = require_sha256(record.get("sha256"), f"descriptor {report_name} sha256")
        try:
            data = (gadget / "functions" / function / "report_desc").read_bytes()
        except OSError as exc:
            raise AdoptError(f"cannot read live descriptor {function}: {exc}") from exc
        if len(data) != expected_size or sha256_bytes(data) != expected_sha:
            raise AdoptError(f"live report descriptor mismatch: {function}")


def read_live_kernel_release(proc_root: Path) -> str:
    try:
        release = (proc_root / "sys/kernel/osrelease").read_text(
            encoding="utf-8"
        ).strip()
    except (OSError, UnicodeError) as exc:
        raise AdoptError(f"cannot read live kernel release: {exc}") from exc
    return require_string(release, "live kernel release")


def secure_file_signature(path: Path, label: str, owner_uid: int) -> tuple[int, ...]:
    details = require_regular_secure(path, label, owner_uid)
    return (
        details.st_dev,
        details.st_ino,
        stat.S_IMODE(details.st_mode),
        details.st_uid,
        details.st_gid,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
    )


def clear_marker_after_unbind(args: argparse.Namespace) -> dict[str, Any]:
    marker, marker_bytes = read_secure_json(
        args.marker,
        "runtime marker",
        args.expected_owner_uid,
    )
    validate_marker_shape(marker)
    marker_signature = secure_file_signature(
        args.marker,
        "runtime marker",
        args.expected_owner_uid,
    )
    runtime, runtime_bytes = read_secure_json(
        args.runtime_contract,
        "runtime early contract",
        args.expected_owner_uid,
    )
    if runtime.get("schema") != RUNTIME_CONTRACT_SCHEMA:
        raise AdoptError("runtime contract schema mismatch during service stop")
    runtime_sha = sha256_bytes(runtime_bytes)
    if marker.get("runtime_contract_sha256") != runtime_sha:
        raise AdoptError("runtime marker contract hash mismatch during service stop")
    if marker.get("kernel_release") != runtime.get("kernel_release"):
        raise AdoptError("runtime marker kernel mismatch during service stop")

    gadget_name = require_string(args.gadget_name, "gadget name")
    gadget = args.configfs_root / gadget_name
    validate_stably_unbound_gadget(gadget)

    final_marker, final_bytes = read_secure_json(
        args.marker,
        "runtime marker",
        args.expected_owner_uid,
    )
    validate_marker_shape(final_marker)
    final_signature = secure_file_signature(
        args.marker,
        "runtime marker",
        args.expected_owner_uid,
    )
    if final_bytes != marker_bytes or final_signature != marker_signature:
        raise AdoptError("runtime marker changed while preparing service-stop cleanup")
    validate_stably_unbound_gadget(gadget)
    if (
        secure_file_signature(
            args.marker,
            "runtime marker",
            args.expected_owner_uid,
        )
        != marker_signature
    ):
        raise AdoptError("runtime marker changed before service-stop cleanup")
    try:
        args.marker.unlink()
    except OSError as exc:
        raise AdoptError(f"cannot clear ephemeral early marker: {args.marker}: {exc}") from exc
    if path_exists_no_follow(args.marker):
        raise AdoptError("ephemeral early marker still exists after service-stop cleanup")
    return {
        "status": "marker-cleared",
        "schema": MARKER_SCHEMA,
        "marker": str(args.marker),
        "runtime_contract_sha256": runtime_sha,
        "configfs_mutations": 0,
        "marker_mutations": 1,
    }


def capture(args: argparse.Namespace) -> dict[str, Any]:
    destination = capture_output_path(args)
    manifest, _ = read_secure_json(
        args.manifest,
        "input E1 manifest",
        args.expected_owner_uid,
    )
    e1 = validate_e1_manifest(manifest)

    live_kernel = read_live_kernel_release(args.proc_root)
    if live_kernel != e1["kernel_release"]:
        raise AdoptError("live kernel release differs from E1 image")
    if not architectures_match(platform.machine(), e1["architecture"]):
        raise AdoptError("live machine architecture differs from E1 image")

    live_identity = effective_identity(args.proc_root)
    if live_identity != e1["identity"]:
        raise AdoptError("effective normal-system identity differs from E1 image")

    packages = capture_package_contract(
        args.package_root,
        args.core_package_name,
        args.profile_package_name,
        e1["source"],
        e1["architecture"],
        args.expected_owner_uid,
    )
    validate_profile(
        args.profile_root,
        args.runtime_profile_marker,
        e1["profile"],
        args.expected_owner_uid,
    )
    validate_helper(
        args.helper,
        require_object(e1["helper"], "helper contract").get("sha256"),
        args.expected_owner_uid,
    )

    runtime = require_object(e1["runtime_contract"], "runtime contract")
    gadget = capture_gadget_contract(
        args.configfs_root,
        args.sys_root,
        args.dev_root,
        args.gadget_name,
        args.config_name,
        e1["identity"],
        e1["descriptors"],
        runtime.get("descriptor_contract_sha256"),
        allow_regular_dev_fixtures=args.allow_regular_dev_fixtures,
    )
    accepted = dict(manifest)
    accepted["adopt"] = {
        "schema": ADOPT_CONTRACT_SCHEMA,
        "packages": packages,
        "gadget": gadget,
    }
    data = (json.dumps(accepted, indent=2, sort_keys=True) + "\n").encode()
    write_exclusive_0600(destination, data)
    return {
        "status": "captured",
        "schema": ADOPT_CONTRACT_SCHEMA,
        "output": str(destination),
        "sha256": sha256_bytes(data),
        "size": len(data),
        "gadget": gadget["name"],
        "udc": gadget["udc"],
        "configfs_mutations": 0,
    }


def verify(args: argparse.Namespace) -> dict[str, Any]:
    gadget_name = require_string(args.gadget_name, "gadget name")
    marker_exists = path_exists_no_follow(args.marker)
    gadget_hint = args.configfs_root / gadget_name
    gadget_exists = path_exists_no_follow(gadget_hint)
    if not marker_exists and not gadget_exists:
        return {
            "status": "create-required",
            "schema": MARKER_SCHEMA,
            "reason": "runtime marker and configfs gadget are absent",
        }
    if not marker_exists:
        validate_stably_unbound_gadget(gadget_hint)
        return {
            "status": "create-required",
            "schema": MARKER_SCHEMA,
            "reason": "runtime marker is absent and configfs gadget is stably unbound",
        }
    if not gadget_exists:
        raise AdoptError("early runtime marker exists but configfs gadget is absent")

    marker, _ = read_secure_json(args.marker, "runtime marker", args.expected_owner_uid)
    accepted, accepted_bytes = read_secure_json(
        args.accepted_manifest,
        "accepted early-image manifest",
        args.expected_owner_uid,
    )
    runtime, runtime_bytes = read_secure_json(
        args.runtime_contract,
        "runtime early contract",
        args.expected_owner_uid,
    )
    if accepted.get("schema") != IMAGE_SCHEMA:
        raise AdoptError("accepted early-image manifest schema mismatch")
    validate_runtime_contract(runtime, accepted, runtime_bytes)
    adopt = require_object(accepted.get("adopt"), "accepted adopt contract")
    if adopt.get("schema") != ADOPT_CONTRACT_SCHEMA:
        raise AdoptError("accepted adopt contract schema mismatch")
    if set(adopt) != {"schema", "packages", "gadget"}:
        raise AdoptError("accepted adopt contract contains unsupported fields")
    accepted_sha = sha256_bytes(accepted_bytes)
    runtime_sha = sha256_bytes(runtime_bytes)
    validate_marker(marker, accepted, runtime_sha)

    kernel_release = require_string(accepted.get("kernel_release"), "kernel release")
    live_kernel = read_live_kernel_release(args.proc_root)
    if live_kernel != kernel_release or runtime.get("kernel_release") != kernel_release:
        raise AdoptError("live/runtime kernel release mismatch")
    helper_contract = require_object(accepted.get("helper"), "accepted helper")
    architecture = require_string(helper_contract.get("architecture"), "helper architecture")
    if helper_contract.get("static") is not True:
        raise AdoptError("accepted helper is not declared static")
    if not architectures_match(platform.machine(), architecture):
        raise AdoptError("live machine architecture differs from early image")
    if runtime.get("source") != accepted.get("source"):
        raise AdoptError("runtime source differs from accepted early image")

    identity = normalize_identity(accepted.get("identity"))
    live_identity = effective_identity(args.proc_root)
    if live_identity != identity:
        raise AdoptError("effective normal-system identity differs from early image")
    identity_item = overlay_file(accepted, "conf/hidloom-early-usb.env")
    if require_sha256(identity_item.get("sha256"), "identity overlay sha256") != require_sha256(
        runtime.get("identity_sha256"), "runtime identity sha256"
    ):
        raise AdoptError("identity file hash differs from runtime contract")

    profile_contract = runtime.get("profile")
    if profile_contract != accepted.get("profile"):
        raise AdoptError("runtime profile differs from accepted manifest")
    validate_packages(
        args.package_root,
        adopt.get("packages"),
        accepted.get("source"),
        architecture,
        args.expected_owner_uid,
    )
    validate_profile(
        args.profile_root,
        args.runtime_profile_marker,
        profile_contract,
        args.expected_owner_uid,
    )
    if helper_contract.get("sha256") != runtime.get("helper_sha256"):
        raise AdoptError("helper hash differs between image and runtime contract")
    helper_item = overlay_file(
        accepted, "usr/lib/hidloom/early/hidloom-usb-gadget-fast"
    )
    if require_sha256(helper_item.get("sha256"), "helper overlay sha256") != require_sha256(
        runtime.get("helper_sha256"), "runtime helper sha256"
    ):
        raise AdoptError("helper overlay hash differs from runtime contract")
    validate_helper(args.helper, runtime.get("helper_sha256"), args.expected_owner_uid)

    gadget_contract = require_object(adopt.get("gadget"), "runtime gadget contract")
    if gadget_contract.get("name") != gadget_name:
        raise AdoptError("CLI gadget name differs from runtime contract")
    name, udc, ordered = validate_gadget_contract(
        args.configfs_root,
        args.sys_root,
        args.dev_root,
        gadget_contract,
        identity,
        allow_regular_dev_fixtures=args.allow_regular_dev_fixtures,
    )
    validate_report_descriptors(
        args.configfs_root / name,
        accepted.get("descriptors"),
        runtime.get("descriptor_contract_sha256"),
        ordered,
    )
    return {
        "status": "adopted",
        "schema": MARKER_SCHEMA,
        "gadget": name,
        "udc": udc,
        "kernel_release": kernel_release,
        "profile": require_object(profile_contract, "profile contract").get("id"),
        "accepted_manifest_sha256": accepted_sha,
        "runtime_contract_sha256": runtime_sha,
        "configfs_mutations": 0,
    }


def add_live_arguments(target: argparse.ArgumentParser) -> None:
    target.add_argument("--configfs-root", type=Path, required=True)
    target.add_argument("--proc-root", type=Path, required=True)
    target.add_argument("--sys-root", type=Path, required=True)
    target.add_argument("--dev-root", type=Path, required=True)
    target.add_argument("--package-root", type=Path, required=True)
    target.add_argument("--profile-root", type=Path, required=True)
    target.add_argument("--runtime-profile-marker", type=Path, required=True)
    target.add_argument("--helper", type=Path, required=True)
    target.add_argument("--gadget-name", default="cqa02303v5")
    target.add_argument("--expected-owner-uid", type=int, default=0)
    target.add_argument(
        "--allow-regular-dev-fixtures",
        action="store_true",
        help="test-only: read major:minor from regular fake /dev files",
    )


def parser() -> argparse.ArgumentParser:
    result = AdoptArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)

    verify_parser = commands.add_parser(
        "verify",
        help="verify a marked early gadget against an accepted contract",
    )
    verify_parser.add_argument("--marker", type=Path, required=True)
    verify_parser.add_argument("--accepted-manifest", type=Path, required=True)
    verify_parser.add_argument("--runtime-contract", type=Path, required=True)
    add_live_arguments(verify_parser)

    capture_parser = commands.add_parser(
        "capture",
        help="capture a verified normal gadget into a new accepted contract",
    )
    capture_parser.add_argument("--manifest", type=Path, required=True)
    capture_parser.add_argument("--output", type=Path, required=True)
    capture_parser.add_argument("--core-package-name", required=True)
    capture_parser.add_argument("--profile-package-name", required=True)
    capture_parser.add_argument("--config-name", default="c.1")
    add_live_arguments(capture_parser)

    clear_parser = commands.add_parser(
        "clear-marker-after-unbind",
        help="clear a validated early marker after a stable service-stop unbind",
    )
    clear_parser.add_argument("--marker", type=Path, required=True)
    clear_parser.add_argument("--runtime-contract", type=Path, required=True)
    clear_parser.add_argument("--configfs-root", type=Path, required=True)
    clear_parser.add_argument("--gadget-name", default="cqa02303v5")
    clear_parser.add_argument("--expected-owner-uid", type=int, default=0)
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0].startswith("-"):
        # Preserve the original verifier-only CLI while exposing explicit commands.
        raw.insert(0, "verify")
    return parser().parse_args(raw)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        if args.command == "capture":
            result = capture(args)
        elif args.command == "clear-marker-after-unbind":
            result = clear_marker_after_unbind(args)
        else:
            result = verify(args)
    except (AdoptError, OSError, UnicodeError, json.JSONDecodeError, KeyError) as exc:
        print(f"unsafe: {exc}", file=sys.stderr)
        return EXIT_UNSAFE
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.command == "verify" and result["status"] == "create-required":
        return EXIT_CREATE_SENTINEL
    return EXIT_ADOPTED


if __name__ == "__main__":
    raise SystemExit(main())
