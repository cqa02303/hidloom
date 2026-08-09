#!/usr/bin/env python3
"""Create a host-only Raspberry Pi tryboot staging directory for HIDloom E1.

This command never edits the supplied normal-boot files.  It accepts a fully
verified E1 image/manifest pair, reconstructs and verifies the E1 base image,
then writes a deterministic directory that can be reviewed before any device
placement is considered.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
from typing import Any

import rpi_os_early_initramfs as e1


SCHEMA = "hidloom.rpi-os-early-tryboot-placement.v1"
TRYBOOT_NAME = "tryboot.txt"
CMDLINE_NAME = "cmdline-hidloom-e1.txt"
ACCEPTED_MANIFEST_NAME = "early-image.accepted.json"
PLACEMENT_MANIFEST_NAME = "tryboot-placement.json"
RESERVED_NAMES = {
    TRYBOOT_NAME,
    CMDLINE_NAME,
    ACCEPTED_MANIFEST_NAME,
    PLACEMENT_MANIFEST_NAME,
    "config.txt",
    "cmdline.txt",
}
DEFAULT_KERNEL_NAMES = {"kernel.img", "kernel7.img", "kernel7l.img", "kernel8.img"}
CONFIG_LINE_LIMIT = 98
ADOPT_SCHEMA = "hidloom.rpi-os-early-gadget-adopt.v1"
DIRECTIVE_RE = re.compile(r"^\s*(auto_initramfs|kernel|cmdline)\s*=\s*(.*?)\s*$")
INITRAMFS_RE = re.compile(r"^\s*initramfs\s+(.+?)\s*$")
INCLUDE_RE = re.compile(r"^\s*include(?:\s+|\s*=)", re.IGNORECASE)


class StageError(ValueError):
    """An input is unsafe or violates the deterministic staging contract."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_basename(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise StageError(f"{label} must be a string")
    if value != Path(value).name or value in {"", ".", ".."}:
        raise StageError(f"{label} must be a basename without path traversal")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", value):
        raise StageError(f"unsafe {label}: {value!r}")
    return value


def verify_e1_pair(
    image_name: str,
    image: bytes,
    manifest_name: str,
    manifest_raw: bytes,
) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StageError(f"invalid JSON: {manifest_name}") from exc
    if not isinstance(manifest, dict):
        raise StageError(f"JSON root must be an object: {manifest_name}")
    if manifest.get("schema") != e1.SCHEMA:
        raise StageError("E1 manifest schema is not accepted")
    adopt = manifest.get("adopt")
    if (
        not isinstance(adopt, dict)
        or adopt.get("schema") != ADOPT_SCHEMA
        or set(adopt) != {"schema", "packages", "gadget"}
        or not isinstance(adopt.get("packages"), dict)
        or not isinstance(adopt.get("gadget"), dict)
    ):
        raise StageError("E1 manifest lacks the required top-level adopt contract")
    try:
        base = manifest["base"]
        overlay = manifest["overlay"]
        output = manifest["output"]
        base_offset = base["zstd_offset"]
        overlay_size = overlay["size"]
        output_offset = output["zstd_offset"]
    except KeyError as exc:
        raise StageError(f"E1 manifest is missing {exc.args[0]}") from exc
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in (
        base_offset, overlay_size, output_offset
    )):
        raise StageError("E1 manifest offsets and sizes must be integers")
    if (
        base_offset < 0
        or overlay_size <= 0
        or output_offset != base_offset + overlay_size
        or output_offset > len(image)
    ):
        raise StageError("E1 manifest has an invalid overlay/output boundary")
    if output.get("size") != len(image) or output.get("sha256") != sha256_bytes(image):
        raise StageError("E1 image hash/size does not match its manifest")
    if output.get("name") != image_name:
        raise StageError("E1 image basename does not match its manifest")
    base_name = safe_basename(str(base.get("name", "")), "E1 base image name")
    reconstructed = image[:base_offset] + image[output_offset:]
    if base.get("size") != len(reconstructed) or base.get("sha256") != sha256_bytes(reconstructed):
        raise StageError("E1 base cannot be reconstructed with the recorded hash/size")
    with tempfile.TemporaryDirectory(prefix="hidloom-e2-verify-") as directory:
        snapshot_root = Path(directory)
        base_path = snapshot_root / base_name
        image_path = snapshot_root / image_name
        manifest_path = snapshot_root / safe_basename(manifest_name, "E1 manifest name")
        base_path.write_bytes(reconstructed)
        image_path.write_bytes(image)
        manifest_path.write_bytes(manifest_raw)
        try:
            e1.verify_artifact(
                base_path,
                image_path,
                manifest_path,
                run_unmkinitramfs=False,
            )
        except (
            OSError,
            AttributeError,
            KeyError,
            TypeError,
            UnicodeError,
            ValueError,
            e1.VerifyError,
        ) as exc:
            raise StageError(f"E1 deep verification failed: {exc}") from exc
    return manifest


def decode_config(raw: bytes) -> str:
    if b"\x00" in raw:
        raise StageError("config.txt contains NUL")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StageError("config.txt is not UTF-8") from exc


def active_config_directives(text: str) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {
        "auto_initramfs": [],
        "kernel": [],
        "cmdline": [],
        "initramfs": [],
    }
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if INCLUDE_RE.match(raw_line):
            raise StageError("config.txt contains an active include directive")
        match = DIRECTIVE_RE.match(raw_line)
        if match:
            values[match.group(1)].append(match.group(2).strip())
            continue
        match = INITRAMFS_RE.match(raw_line)
        if match:
            values["initramfs"].append(" ".join(match.group(1).split()))
    for key, found in values.items():
        if len(set(found)) > 1:
            raise StageError(f"config.txt has conflicting duplicate {key} directives")
    return values


def render_tryboot(config_raw: bytes, kernel_name: str, image_name: str) -> bytes:
    text = decode_config(config_raw)
    directives = active_config_directives(text)
    expected = {
        "kernel": kernel_name,
        "cmdline": CMDLINE_NAME,
        "initramfs": f"{image_name} followkernel",
    }
    for key, value in expected.items():
        if directives[key] and directives[key][0] != value:
            raise StageError(
                f"config.txt has a conflicting {key} directive: {directives[key][0]!r}"
            )
    if "hidloom.early" in text or CMDLINE_NAME in text or ACCEPTED_MANIFEST_NAME in text:
        raise StageError("config.txt already contains HIDloom E1 staging content")
    separator = b"" if not config_raw or config_raw.endswith(b"\n") else b"\n"
    block = (
        b"[all]\n"
        b"auto_initramfs=0\n"
        + f"kernel={kernel_name}\n".encode()
        + f"cmdline={CMDLINE_NAME}\n".encode()
        + f"initramfs {image_name} followkernel\n".encode()
    )
    for line in block.splitlines():
        if len(line) > CONFIG_LINE_LIMIT:
            raise StageError(
                f"generated config directive exceeds {CONFIG_LINE_LIMIT} characters"
            )
    result = config_raw + separator + block
    if not result.startswith(config_raw):
        raise AssertionError("normal config bytes were not preserved as a prefix")
    return result


def render_cmdline(raw: bytes) -> bytes:
    if b"\x00" in raw or b"\r" in raw:
        raise StageError("cmdline.txt contains NUL or CR")
    has_newline = raw.endswith(b"\n")
    body = raw[:-1] if has_newline else raw
    if b"\n" in body or not body.strip():
        raise StageError("cmdline.txt must contain exactly one non-empty line")
    try:
        tokens = body.decode("ascii").split()
    except UnicodeDecodeError as exc:
        raise StageError("cmdline.txt must be ASCII") from exc
    if any(token.startswith("hidloom.early=") for token in tokens):
        raise StageError("cmdline.txt already contains a hidloom.early token")
    if any(token.startswith("panic=") for token in tokens):
        raise StageError("cmdline.txt already contains a panic token")
    suffix = b" hidloom.early=e1 panic=10"
    return body + suffix + (b"\n" if has_newline else b"")


def kernel_payload_format(data: bytes) -> str | None:
    if data.startswith(b"\x7fELF"):
        return "elf"
    if len(data) >= 0x3C and data[0x38:0x3C] == b"ARM\x64":
        return "arm64-image"
    return None


def validate_kernel_image(data: bytes, kernel_release: str) -> dict[str, str]:
    if not isinstance(kernel_release, str) or not kernel_release:
        raise StageError("E1 kernel release must be a non-empty string")
    try:
        release = kernel_release.encode("ascii")
    except UnicodeEncodeError as exc:
        raise StageError("E1 kernel release is not ASCII") from exc
    if data.startswith(b"\x1f\x8b"):
        try:
            payload = gzip.decompress(data)
        except (EOFError, OSError) as exc:
            raise StageError("kernel image has invalid gzip compression") from exc
        compression = "gzip"
    else:
        payload = data
        compression = "none"
    payload_format = kernel_payload_format(payload)
    if payload_format is None:
        raise StageError("kernel image has an unknown compressed or raw format")
    if release not in payload:
        raise StageError("kernel image is not linked to the E1 kernel release")
    return {"compression": compression, "payload_format": payload_format}


def file_record(path: str, role: str, data: bytes) -> dict[str, Any]:
    return {"path": path, "role": role, "size": len(data), "sha256": sha256_bytes(data)}


def write_fixed(path: Path, data: bytes) -> None:
    path.write_bytes(data)
    os.chmod(path, 0o644)


def require_exact_object(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StageError(f"{label} must be an object")
    if set(value) != keys:
        raise StageError(f"{label} fields do not match the staging contract")
    return value


def validate_file_record(
    value: object,
    label: str,
    *,
    expected_path: str | None = None,
    expected_role: str | None = None,
) -> dict[str, Any]:
    record = require_exact_object(value, {"path", "role", "size", "sha256"}, label)
    path = safe_basename(record.get("path", ""), f"{label} path")
    role = record.get("role")
    size = record.get("size")
    digest = record.get("sha256")
    if not isinstance(role, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", role):
        raise StageError(f"{label} role is invalid")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise StageError(f"{label} size is invalid")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise StageError(f"{label} sha256 is invalid")
    if expected_path is not None and path != expected_path:
        raise StageError(f"{label} path does not match the staging contract")
    if expected_role is not None and role != expected_role:
        raise StageError(f"{label} role does not match the staging contract")
    return record


def is_boot_path(path: Path) -> bool:
    try:
        path.relative_to(Path("/boot"))
        return True
    except ValueError:
        return False


def snapshot_stage_directory(directory: Path) -> dict[str, bytes]:
    try:
        directory_stat = directory.lstat()
    except OSError as exc:
        raise StageError(f"cannot inspect staging directory: {exc}") from exc
    if stat.S_ISLNK(directory_stat.st_mode) or not stat.S_ISDIR(directory_stat.st_mode):
        raise StageError("staging path must be a real directory")
    if stat.S_IMODE(directory_stat.st_mode) != 0o755:
        raise StageError("staging directory mode must be 0755")
    snapshots: dict[str, bytes] = {}
    try:
        entries = list(directory.iterdir())
    except OSError as exc:
        raise StageError(f"cannot enumerate staging directory: {exc}") from exc
    for path in entries:
        name = safe_basename(path.name, "staged filename")
        try:
            item_stat = path.lstat()
        except OSError as exc:
            raise StageError(f"cannot inspect staged file {name}: {exc}") from exc
        if stat.S_ISLNK(item_stat.st_mode) or not stat.S_ISREG(item_stat.st_mode):
            raise StageError(f"staged entry is not a regular file: {name}")
        if stat.S_IMODE(item_stat.st_mode) != 0o644:
            raise StageError(f"staged file mode must be 0644: {name}")
        snapshots[name] = path.read_bytes()
    return snapshots


def reconstruct_normal_cmdline(alternate: bytes) -> bytes:
    suffix = b" hidloom.early=e1 panic=10"
    has_newline = alternate.endswith(b"\n")
    body = alternate[:-1] if has_newline else alternate
    if not body.endswith(suffix):
        raise StageError("alternate cmdline lacks the exact E1 safety tokens")
    return body[: -len(suffix)] + (b"\n" if has_newline else b"")


def verify_stage_directory(directory: Path) -> dict[str, Any]:
    snapshots = snapshot_stage_directory(directory)
    try:
        placement_raw = snapshots[PLACEMENT_MANIFEST_NAME]
    except KeyError as exc:
        raise StageError("staging directory lacks tryboot-placement.json") from exc
    try:
        placement = json.loads(placement_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StageError("tryboot-placement.json is invalid JSON") from exc
    placement = require_exact_object(
        placement,
        {
            "schema",
            "source",
            "kernel",
            "profile",
            "e1",
            "normal_boot_inputs",
            "files",
            "activation",
        },
        "placement manifest",
    )
    if placement.get("schema") != SCHEMA:
        raise StageError("placement manifest schema is not accepted")
    canonical = (json.dumps(placement, indent=2, sort_keys=True) + "\n").encode()
    if placement_raw != canonical:
        raise StageError("placement manifest is not in canonical deterministic form")

    e1_record = require_exact_object(
        placement.get("e1"),
        {"schema", "image_name", "image_sha256", "manifest_sha256"},
        "placement E1 record",
    )
    image_name = safe_basename(e1_record.get("image_name", ""), "E1 image name")
    if image_name.casefold() in {name.casefold() for name in RESERVED_NAMES}:
        raise StageError("E1 image name collides with a reserved staging filename")

    kernel_record = require_exact_object(
        placement.get("kernel"),
        {"release", "compression", "payload_format", "input", "staged"},
        "placement kernel record",
    )
    kernel_input = validate_file_record(
        kernel_record.get("input"), "kernel input record", expected_role="kernel_input"
    )
    staged_kernel = validate_file_record(
        kernel_record.get("staged"), "staged kernel record", expected_role="alternate_kernel"
    )
    kernel_name = staged_kernel["path"]
    if not kernel_name.endswith(".img"):
        raise StageError("staged kernel name must end in .img")
    if kernel_name.casefold() in {
        name.casefold() for name in DEFAULT_KERNEL_NAMES | RESERVED_NAMES
    }:
        raise StageError("staged kernel name is not an alternate basename")
    if kernel_name.casefold() == image_name.casefold():
        raise StageError("staged kernel and E1 image names collide")

    file_values = placement.get("files")
    if not isinstance(file_values, list):
        raise StageError("placement file inventory must be a list")
    file_records: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(file_values):
        record = validate_file_record(value, f"placement file record {index}")
        if record["path"] in file_records:
            raise StageError("placement file inventory contains duplicate paths")
        file_records[record["path"]] = record
    if [record["path"] for record in file_values] != sorted(file_records):
        raise StageError("placement file inventory is not sorted")

    expected_roles = {
        TRYBOOT_NAME: "tryboot_config",
        CMDLINE_NAME: "alternate_cmdline",
        kernel_name: "alternate_kernel",
        image_name: "alternate_initramfs",
        ACCEPTED_MANIFEST_NAME: "accepted_e1_manifest",
    }
    if set(file_records) != set(expected_roles):
        raise StageError("placement file inventory is incomplete or contains extras")
    expected_files = set(expected_roles) | {PLACEMENT_MANIFEST_NAME}
    if set(snapshots) != expected_files:
        raise StageError("staging directory is incomplete or contains extra entries")
    for name, role in expected_roles.items():
        record = validate_file_record(
            file_records[name], f"staged file {name}", expected_path=name, expected_role=role
        )
        data = snapshots[name]
        if record["size"] != len(data) or record["sha256"] != sha256_bytes(data):
            raise StageError(f"staged file hash/size mismatch: {name}")
    if staged_kernel != file_records[kernel_name]:
        raise StageError("nested staged kernel record differs from the file inventory")
    if (
        kernel_input["size"] != staged_kernel["size"]
        or kernel_input["sha256"] != staged_kernel["sha256"]
    ):
        raise StageError("kernel input and staged kernel records are not byte-identical")

    accepted_raw = snapshots[ACCEPTED_MANIFEST_NAME]
    accepted = verify_e1_pair(
        image_name,
        snapshots[image_name],
        ACCEPTED_MANIFEST_NAME,
        accepted_raw,
    )
    expected_e1_record = {
        "schema": accepted["schema"],
        "image_name": image_name,
        "image_sha256": accepted["output"]["sha256"],
        "manifest_sha256": sha256_bytes(accepted_raw),
    }
    if e1_record != expected_e1_record:
        raise StageError("placement E1 record differs from the accepted E1 artifact")
    if placement.get("source") != accepted["source"]:
        raise StageError("placement source differs from the accepted E1 artifact")
    if placement.get("profile") != accepted["profile"]:
        raise StageError("placement profile differs from the accepted E1 artifact")

    release = kernel_record.get("release")
    if release != accepted["kernel_release"]:
        raise StageError("staged kernel release differs from the accepted E1 artifact")
    kernel_format = validate_kernel_image(snapshots[kernel_name], release)
    if kernel_record.get("compression") != kernel_format["compression"]:
        raise StageError("staged kernel compression record is incorrect")
    if kernel_record.get("payload_format") != kernel_format["payload_format"]:
        raise StageError("staged kernel payload format record is incorrect")

    normal_inputs = require_exact_object(
        placement.get("normal_boot_inputs"), {"config", "cmdline"}, "normal boot inputs"
    )
    config_record = validate_file_record(
        normal_inputs.get("config"),
        "normal config record",
        expected_path="config.txt",
        expected_role="normal_config_input",
    )
    cmdline_record = validate_file_record(
        normal_inputs.get("cmdline"),
        "normal cmdline record",
        expected_path="cmdline.txt",
        expected_role="normal_cmdline_input",
    )
    tryboot = snapshots[TRYBOOT_NAME]
    normal_config = tryboot[: config_record["size"]]
    if (
        len(normal_config) != config_record["size"]
        or sha256_bytes(normal_config) != config_record["sha256"]
        or render_tryboot(normal_config, kernel_name, image_name) != tryboot
    ):
        raise StageError("tryboot config is not linked to its recorded normal config")
    alternate_cmdline = snapshots[CMDLINE_NAME]
    normal_cmdline = reconstruct_normal_cmdline(alternate_cmdline)
    if (
        len(normal_cmdline) != cmdline_record["size"]
        or sha256_bytes(normal_cmdline) != cmdline_record["sha256"]
        or render_cmdline(normal_cmdline) != alternate_cmdline
    ):
        raise StageError("alternate cmdline is not linked to its recorded normal cmdline")

    expected_activation = {
        "default_boot_modified": False,
        "one_shot_only": True,
        "tryboot_config": TRYBOOT_NAME,
        "alternate_cmdline": CMDLINE_NAME,
        "cmdline_tokens_added": ["hidloom.early=e1", "panic=10"],
        "panic_seconds": 10,
    }
    if placement.get("activation") != expected_activation:
        raise StageError("placement activation contract is invalid")
    return {
        "status": "pass",
        "schema": SCHEMA,
        "directory": str(directory.resolve()),
        "kernel_release": release,
        "source": accepted["source"],
        "files": len(snapshots),
        "placement_sha256": sha256_bytes(placement_raw),
    }


def stage(args: argparse.Namespace) -> dict[str, Any]:
    requested_output = args.output_dir.absolute()
    if requested_output.exists() or requested_output.is_symlink():
        raise StageError("output directory already exists")
    output_dir = requested_output.resolve()
    if (is_boot_path(requested_output) or is_boot_path(output_dir)) and not args.allow_device_path:
        raise StageError("refusing output under /boot without --allow-device-path")
    if args.config.name != "config.txt" or args.cmdline.name != "cmdline.txt":
        raise StageError("normal boot inputs must be named exactly config.txt and cmdline.txt")
    kernel_name = safe_basename(args.kernel_image_name, "kernel image name")
    if not kernel_name.endswith(".img"):
        raise StageError("kernel image name must end in .img")
    if kernel_name.casefold() in {
        name.casefold() for name in DEFAULT_KERNEL_NAMES | RESERVED_NAMES
    }:
        raise StageError("kernel image name must be an alternate, non-default basename")
    kernel_input_name = safe_basename(args.kernel_image.name, "kernel input name")
    image_name = safe_basename(args.e1_image.name, "E1 image name")
    if image_name.casefold() in {name.casefold() for name in RESERVED_NAMES} or (
        image_name.casefold() == kernel_name.casefold()
    ):
        raise StageError("E1 image name collides with a boot staging filename")
    if args.e1_manifest.name.casefold() in {name.casefold() for name in RESERVED_NAMES}:
        raise StageError("input E1 manifest uses a reserved staging filename")

    # Snapshot every explicit input once before any validation subprocess runs.
    # All verification and output below use only these bytes, closing the gap
    # between acceptance and placement if an input path changes concurrently.
    config_raw = args.config.read_bytes()
    cmdline_raw = args.cmdline.read_bytes()
    image = args.e1_image.read_bytes()
    e1_manifest_raw = args.e1_manifest.read_bytes()
    kernel = args.kernel_image.read_bytes()
    tryboot = render_tryboot(config_raw, kernel_name, image_name)
    alternate_cmdline = render_cmdline(cmdline_raw)
    e1_manifest = verify_e1_pair(
        image_name,
        image,
        args.e1_manifest.name,
        e1_manifest_raw,
    )
    kernel_format = validate_kernel_image(kernel, e1_manifest["kernel_release"])

    generated = {
        TRYBOOT_NAME: ("tryboot_config", tryboot),
        CMDLINE_NAME: ("alternate_cmdline", alternate_cmdline),
        kernel_name: ("alternate_kernel", kernel),
        image_name: ("alternate_initramfs", image),
        ACCEPTED_MANIFEST_NAME: ("accepted_e1_manifest", e1_manifest_raw),
    }
    placement = {
        "schema": SCHEMA,
        "source": e1_manifest["source"],
        "kernel": {
            "release": e1_manifest["kernel_release"],
            "compression": kernel_format["compression"],
            "payload_format": kernel_format["payload_format"],
            "input": file_record(kernel_input_name, "kernel_input", kernel),
            "staged": file_record(kernel_name, "alternate_kernel", kernel),
        },
        "profile": e1_manifest["profile"],
        "e1": {
            "schema": e1_manifest["schema"],
            "image_name": image_name,
            "image_sha256": e1_manifest["output"]["sha256"],
            "manifest_sha256": sha256_bytes(e1_manifest_raw),
        },
        "normal_boot_inputs": {
            "config": file_record(args.config.name, "normal_config_input", config_raw),
            "cmdline": file_record(args.cmdline.name, "normal_cmdline_input", cmdline_raw),
        },
        "files": [
            file_record(name, role, data)
            for name, (role, data) in sorted(generated.items())
        ],
        "activation": {
            "default_boot_modified": False,
            "one_shot_only": True,
            "tryboot_config": TRYBOOT_NAME,
            "alternate_cmdline": CMDLINE_NAME,
            "cmdline_tokens_added": ["hidloom.early=e1", "panic=10"],
            "panic_seconds": 10,
        },
    }
    placement_raw = (json.dumps(placement, indent=2, sort_keys=True) + "\n").encode()
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary_dir: Path | None = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.tmp-", dir=output_dir.parent)
    )
    try:
        os.chmod(temporary_dir, 0o755)
        for name, (_, data) in sorted(generated.items()):
            write_fixed(temporary_dir / name, data)
        write_fixed(temporary_dir / PLACEMENT_MANIFEST_NAME, placement_raw)
        verify_stage_directory(temporary_dir)
        if output_dir.exists() or output_dir.is_symlink():
            raise StageError("output directory appeared while staging")
        os.rename(temporary_dir, output_dir)
        temporary_dir = None
    finally:
        if temporary_dir is not None and temporary_dir.exists():
            shutil.rmtree(temporary_dir)
    return {
        "status": "pass",
        "schema": SCHEMA,
        "output_dir": str(output_dir),
        "kernel_release": e1_manifest["kernel_release"],
        "source": e1_manifest["source"],
        "files": len(generated) + 1,
        "placement_sha256": sha256_bytes(placement_raw),
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    stage_parser = commands.add_parser("stage", help="create a disabled host-only tryboot tree")
    stage_parser.add_argument(
        "--config", type=Path, required=True, help="current complete config.txt"
    )
    stage_parser.add_argument(
        "--cmdline", type=Path, required=True, help="current single-line cmdline.txt"
    )
    stage_parser.add_argument("--e1-image", type=Path, required=True)
    stage_parser.add_argument("--e1-manifest", type=Path, required=True)
    stage_parser.add_argument("--kernel-image", type=Path, required=True)
    stage_parser.add_argument(
        "--kernel-image-name",
        required=True,
        help="alternate output basename; standard Raspberry Pi kernel names are refused",
    )
    stage_parser.add_argument("--output-dir", type=Path, required=True)
    stage_parser.add_argument(
        "--allow-device-path",
        action="store_true",
        help="explicitly allow an output directory under /boot",
    )
    verify_parser = commands.add_parser("verify", help="deeply verify a staged tryboot tree")
    verify_parser.add_argument("--directory", type=Path, required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "stage":
            result = stage(args)
        else:
            result = verify_stage_directory(args.directory)
    except (OSError, KeyError, TypeError, UnicodeError, StageError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
