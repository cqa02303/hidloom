#!/usr/bin/env python3
"""Safely place a reviewed HIDloom E2 tryboot tree without activating it.

The host-side ``rpi_os_early_tryboot.py`` tool creates and verifies the staged
bytes.  This device-side helper adds the narrower placement transaction:

* prove that the stage, live board, kernel, and normal boot inputs still match;
* back up every normal boot input before adding alternate files;
* create every destination without overwriting an existing path;
* publish ``tryboot.txt`` last; and
* leave the Raspberry Pi tryboot one-shot flag untouched.

It deliberately has no reboot or activation command.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
from typing import Any

import rpi_os_early_initramfs as early
import rpi_os_early_tryboot as tryboot


SCHEMA = "hidloom.rpi-os-early-tryboot-install.v1"
BACKUP_SCHEMA = "hidloom.rpi-os-normal-boot-backup.v1"
RECEIPT_NAME = "tryboot-install.json"
BACKUP_MANIFEST_NAME = "normal-boot-backup.json"
FORBIDDEN_BOOT_NAMES = {"autoboot.txt", "boot.img", "boot.sig", "tryboot.img"}
MAX_STAGE_FILE_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_CONTROL_FILE_BYTES = 128 * 1024
MAX_CMDLINE_BYTES = 4 * 1024
MAX_TOTAL_STAGE_BYTES = 768 * 1024 * 1024
DEFAULT_MINIMUM_FREE_BYTES = 16 * 1024 * 1024
RENAME_NOREPLACE = 1
AT_FDCWD = -100


class PlacementError(ValueError):
    """The requested placement is unsafe or differs from its reviewed input."""


@dataclass(frozen=True)
class CreatedFile:
    path: Path
    device: int
    inode: int
    size: int
    sha256: str


@dataclass(frozen=True)
class VerifiedFile:
    """One streamed, race-checked regular file snapshot.

    Large boot artifacts deliberately remain on disk.  The identity fields
    make a later copy fail closed if the reviewed source inode changes, while
    the size and digest bind its bytes to the host-reviewed placement manifest.
    """

    path: Path
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    sha256: str
    mode: int
    owner_uid: int
    fd: int


@dataclass
class PlacementContext:
    stage_dir: Path
    boot_root: Path
    accepted_root: Path
    accepted_root_exists: bool
    backup_dir: Path
    model_path: Path
    kernel_release_path: Path
    expected_owner_uid: int
    placement: dict[str, Any]
    accepted_manifest: dict[str, Any]
    stage: dict[str, VerifiedFile]
    stage_small: dict[str, bytes]
    placement_sha256: str
    boot_records: dict[str, dict[str, Any]]
    normal_paths: dict[str, Path]
    normal_files: dict[str, VerifiedFile]
    normal_small: dict[str, bytes]
    normal_records: dict[str, dict[str, Any]]
    expected_model: str
    kernel_release: str
    minimum_free_bytes: int
    free_space: list[dict[str, Any]]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def path_exists(path: Path) -> bool:
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise PlacementError(f"cannot inspect path {path}: {exc}") from exc


def secure_directory(path: Path, label: str, owner_uid: int) -> Path:
    try:
        resolved = path.resolve(strict=True)
        details = resolved.lstat()
    except OSError as exc:
        raise PlacementError(f"cannot resolve {label}: {path}: {exc}") from exc
    if not stat.S_ISDIR(details.st_mode):
        raise PlacementError(f"{label} is not a directory: {resolved}")
    if details.st_uid != owner_uid:
        raise PlacementError(
            f"{label} owner mismatch: {resolved}: {details.st_uid} != {owner_uid}"
        )
    if details.st_mode & 0o022:
        raise PlacementError(f"{label} is group/world writable: {resolved}")
    return resolved


def destination_directory(
    path: Path, label: str, owner_uid: int
) -> tuple[Path, bool]:
    if path.name in {"", ".", ".."}:
        raise PlacementError(f"{label} must not be a filesystem root")
    if path_exists(path):
        return secure_directory(path, label, owner_uid), True
    parent = secure_directory(path.parent, f"{label} parent", owner_uid)
    candidate = parent / path.name
    if path_exists(candidate):
        raise PlacementError(f"{label} appeared while resolving: {candidate}")
    return candidate, False


def paths_overlap(left: Path, right: Path) -> bool:
    try:
        left.relative_to(right)
        return True
    except ValueError:
        pass
    try:
        right.relative_to(left)
        return True
    except ValueError:
        return False


def require_separate_roots(
    stage_dir: Path, boot_root: Path, accepted_root: Path, backup_dir: Path
) -> None:
    labelled = {
        "stage directory": stage_dir,
        "boot root": boot_root,
        "accepted root": accepted_root,
        "backup directory": backup_dir,
    }
    pairs = list(labelled.items())
    for index, (left_label, left) in enumerate(pairs):
        for right_label, right in pairs[index + 1 :]:
            if paths_overlap(left, right):
                raise PlacementError(
                    f"{left_label} and {right_label} must be separate: {left}, {right}"
                )


def read_regular(
    path: Path,
    label: str,
    owner_uid: int,
    *,
    exact_mode: int | None = None,
    max_bytes: int = MAX_STAGE_FILE_BYTES,
) -> bytes:
    """Read one non-writable regular file while rejecting replacement races."""
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        before_path = path.lstat()
        fd = os.open(path, flags)
    except OSError as exc:
        raise PlacementError(f"cannot open {label}: {path}: {exc}") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise PlacementError(f"{label} is not a regular file: {path}")
        if before.st_uid != owner_uid:
            raise PlacementError(
                f"{label} owner mismatch: {path}: {before.st_uid} != {owner_uid}"
            )
        if before.st_mode & 0o022:
            raise PlacementError(f"{label} is group/world writable: {path}")
        mode = stat.S_IMODE(before.st_mode)
        if exact_mode is not None and mode != exact_mode:
            raise PlacementError(
                f"{label} mode mismatch: {path}: {mode:04o} != {exact_mode:04o}"
            )
        if before.st_size > max_bytes:
            raise PlacementError(f"{label} is unexpectedly large: {before.st_size} bytes")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                raise PlacementError(f"short read from {label}: {path}")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(fd, 1):
            raise PlacementError(f"{label} grew while being read: {path}")
        after = os.fstat(fd)
    finally:
        os.close(fd)
    try:
        after_path = path.lstat()
    except OSError as exc:
        raise PlacementError(f"cannot restat {label}: {path}: {exc}") from exc
    identity_before = (
        before_path.st_dev,
        before_path.st_ino,
        before_path.st_size,
        before_path.st_mtime_ns,
        before_path.st_ctime_ns,
    )
    identity_fd = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    identity_path_after = (
        after_path.st_dev,
        after_path.st_ino,
        after_path.st_size,
        after_path.st_mtime_ns,
        after_path.st_ctime_ns,
    )
    if len({identity_before, identity_fd, identity_after, identity_path_after}) != 1:
        raise PlacementError(f"{label} changed while being read: {path}")
    return b"".join(chunks)


def inspect_regular(
    path: Path,
    label: str,
    owner_uid: int,
    *,
    exact_mode: int | None = None,
    max_bytes: int = MAX_STAGE_FILE_BYTES,
    retain_fd: bool = False,
) -> VerifiedFile:
    """Hash a regular file in bounded chunks and pin its inode identity."""
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        before_path = path.lstat()
        fd = os.open(path, flags)
    except OSError as exc:
        raise PlacementError(f"cannot open {label}: {path}: {exc}") from exc
    retained = False
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise PlacementError(f"{label} is not a regular file: {path}")
        if before.st_uid != owner_uid:
            raise PlacementError(
                f"{label} owner mismatch: {path}: {before.st_uid} != {owner_uid}"
            )
        if before.st_mode & 0o022:
            raise PlacementError(f"{label} is group/world writable: {path}")
        mode = stat.S_IMODE(before.st_mode)
        if exact_mode is not None and mode != exact_mode:
            raise PlacementError(
                f"{label} mode mismatch: {path}: {mode:04o} != {exact_mode:04o}"
            )
        if before.st_size > max_bytes:
            raise PlacementError(f"{label} is unexpectedly large: {before.st_size} bytes")
        digest = hashlib.sha256()
        remaining = before.st_size
        while remaining:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                raise PlacementError(f"short read from {label}: {path}")
            digest.update(chunk)
            remaining -= len(chunk)
        if os.read(fd, 1):
            raise PlacementError(f"{label} grew while being read: {path}")
        after = os.fstat(fd)
        after_path = path.lstat()
        identity_before = (
            before_path.st_dev,
            before_path.st_ino,
            before_path.st_size,
            before_path.st_mtime_ns,
            before_path.st_ctime_ns,
        )
        identity_fd = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        identity_path_after = (
            after_path.st_dev,
            after_path.st_ino,
            after_path.st_size,
            after_path.st_mtime_ns,
            after_path.st_ctime_ns,
        )
        if len({identity_before, identity_fd, identity_after, identity_path_after}) != 1:
            raise PlacementError(f"{label} changed while being hashed: {path}")
        result = VerifiedFile(
            path=path,
            device=before.st_dev,
            inode=before.st_ino,
            size=before.st_size,
            mtime_ns=before.st_mtime_ns,
            ctime_ns=before.st_ctime_ns,
            sha256=digest.hexdigest(),
            mode=mode,
            owner_uid=before.st_uid,
            fd=fd if retain_fd else -1,
        )
        retained = retain_fd
        return result
    except OSError as exc:
        raise PlacementError(f"cannot inspect {label}: {path}: {exc}") from exc
    finally:
        if not retained:
            os.close(fd)


def same_verified_file(left: VerifiedFile, right: VerifiedFile) -> bool:
    return (
        left.device,
        left.inode,
        left.size,
        left.mtime_ns,
        left.ctime_ns,
        left.sha256,
    ) == (
        right.device,
        right.inode,
        right.size,
        right.mtime_ns,
        right.ctime_ns,
        right.sha256,
    )


def assert_verified_file_unchanged(
    expected: VerifiedFile, label: str, owner_uid: int, *, exact_mode: int | None = None
) -> None:
    if expected.fd < 0:
        raise PlacementError(f"{label} does not have a retained source descriptor")
    if expected.owner_uid != owner_uid:
        raise PlacementError(f"{label} retained owner contract is invalid")
    if exact_mode is not None and expected.mode != exact_mode:
        raise PlacementError(f"{label} retained mode contract is invalid")
    try:
        before_path = expected.path.lstat()
        before = os.fstat(expected.fd)
        os.lseek(expected.fd, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        remaining = expected.size
        while remaining:
            chunk = os.read(expected.fd, min(1024 * 1024, remaining))
            if not chunk:
                raise PlacementError(f"short read from retained {label}: {expected.path}")
            digest.update(chunk)
            remaining -= len(chunk)
        if os.read(expected.fd, 1):
            raise PlacementError(f"retained {label} grew: {expected.path}")
        after = os.fstat(expected.fd)
        after_path = expected.path.lstat()
    except OSError as exc:
        raise PlacementError(f"cannot recheck retained {label}: {expected.path}: {exc}") from exc
    identities = {
        (
            details.st_dev,
            details.st_ino,
            details.st_size,
            details.st_mtime_ns,
            details.st_ctime_ns,
        )
        for details in (before_path, before, after, after_path)
    }
    expected_identity = (
        expected.device,
        expected.inode,
        expected.size,
        expected.mtime_ns,
        expected.ctime_ns,
    )
    if identities != {expected_identity} or digest.hexdigest() != expected.sha256:
        raise PlacementError(f"{label} changed after placement preflight")


def close_verified_files(*collections: dict[str, VerifiedFile]) -> None:
    closed: set[int] = set()
    for records in collections:
        for record in records.values():
            if record.fd < 0 or record.fd in closed:
                continue
            try:
                os.close(record.fd)
            except OSError:
                pass
            closed.add(record.fd)


def pseudo_file_identity(details: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        details.st_dev,
        details.st_ino,
        stat.S_IFMT(details.st_mode),
        details.st_uid,
        details.st_gid,
    )


def read_bounded_pseudo_file(
    path: Path,
    label: str,
    owner_uid: int,
    *,
    max_bytes: int = 4096,
) -> bytes:
    """Read a stable read-only procfs/sysfs value without trusting st_size.

    procfs and device-tree attributes commonly report ``st_size == 0`` even
    when a read returns bytes.  Read to EOF with a hard max+1 bound, validate
    the inode before and after each open, and require two identical snapshots.
    This is intentionally separate from ``read_regular``: staged and boot
    artifacts must continue to obey their exact on-disk size metadata.
    """
    if max_bytes <= 0:
        raise PlacementError(f"{label} maximum size must be positive")
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    def read_once() -> tuple[bytes, tuple[int, int, int, int, int]]:
        try:
            before_path = path.lstat()
            fd = os.open(path, flags)
        except OSError as exc:
            raise PlacementError(f"cannot open {label}: {path}: {exc}") from exc
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                raise PlacementError(f"{label} is not a regular pseudo-file: {path}")
            if before.st_uid != owner_uid:
                raise PlacementError(
                    f"{label} owner mismatch: {path}: {before.st_uid} != {owner_uid}"
                )
            if before.st_mode & 0o222:
                raise PlacementError(f"{label} is writable: {path}")
            expected_identity = pseudo_file_identity(before)
            if pseudo_file_identity(before_path) != expected_identity:
                raise PlacementError(f"{label} path changed before read: {path}")
            result = bytearray()
            while True:
                chunk = os.read(fd, min(4096, max_bytes + 1 - len(result)))
                if not chunk:
                    break
                result.extend(chunk)
                if len(result) > max_bytes:
                    raise PlacementError(
                        f"{label} exceeds the {max_bytes}-byte safety bound: {path}"
                    )
            after = os.fstat(fd)
        finally:
            os.close(fd)
        try:
            after_path = path.lstat()
        except OSError as exc:
            raise PlacementError(f"cannot restat {label}: {path}: {exc}") from exc
        if (
            pseudo_file_identity(after) != expected_identity
            or pseudo_file_identity(after_path) != expected_identity
        ):
            raise PlacementError(f"{label} inode changed while being read: {path}")
        return bytes(result), expected_identity

    first, first_identity = read_once()
    second, second_identity = read_once()
    if first_identity != second_identity or first != second:
        raise PlacementError(f"{label} was not stable across two reads: {path}")
    return first


def read_verified_small(
    source: VerifiedFile, label: str, owner_uid: int, *, max_bytes: int = MAX_MANIFEST_BYTES
) -> bytes:
    if source.size > max_bytes:
        raise PlacementError(f"{label} is unexpectedly large: {source.size} bytes")
    assert_verified_file_unchanged(source, label, owner_uid, exact_mode=source.mode)
    try:
        os.lseek(source.fd, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        remaining = source.size
        while remaining:
            chunk = os.read(source.fd, min(64 * 1024, remaining))
            if not chunk:
                raise PlacementError(f"short read from retained {label}: {source.path}")
            chunks.append(chunk)
            remaining -= len(chunk)
    except OSError as exc:
        raise PlacementError(f"cannot read retained {label}: {source.path}: {exc}") from exc
    result = b"".join(chunks)
    if sha256_bytes(result) != source.sha256:
        raise PlacementError(f"{label} differs from its streamed digest")
    return result


def decode_json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PlacementError(f"cannot decode {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise PlacementError(f"{label} root is not an object")
    return value


def verify_pinned_stage_contract(
    snapshots: dict[str, VerifiedFile],
    small: dict[str, bytes],
    placement: dict[str, Any],
    placement_raw: bytes,
) -> dict[str, Any]:
    """Validate the host-deep-verified contract without expanding E1 again.

    The caller has already matched ``placement_raw`` to an explicit digest
    copied from the successful host-side deep verification.  Every large file
    is therefore checked as an opaque streamed payload against that pinned
    manifest; semantic expansion remains a host responsibility.
    """
    placement = tryboot.require_exact_object(
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
    if placement.get("schema") != tryboot.SCHEMA:
        raise PlacementError("placement manifest schema is not accepted")
    if placement_raw != canonical_bytes(placement):
        raise PlacementError("placement manifest is not canonical")

    e1_record = tryboot.require_exact_object(
        placement.get("e1"),
        {"schema", "image_name", "image_sha256", "manifest_sha256"},
        "placement E1 record",
    )
    image_name = tryboot.safe_basename(e1_record.get("image_name", ""), "E1 image name")
    if image_name.casefold() in {name.casefold() for name in tryboot.RESERVED_NAMES}:
        raise PlacementError("E1 image name collides with a reserved filename")

    kernel_record = tryboot.require_exact_object(
        placement.get("kernel"),
        {"release", "compression", "payload_format", "input", "staged"},
        "placement kernel record",
    )
    kernel_input = tryboot.validate_file_record(
        kernel_record.get("input"), "kernel input record", expected_role="kernel_input"
    )
    staged_kernel = tryboot.validate_file_record(
        kernel_record.get("staged"),
        "staged kernel record",
        expected_role="alternate_kernel",
    )
    kernel_name = staged_kernel["path"]
    if not kernel_name.endswith(".img"):
        raise PlacementError("staged kernel name must end in .img")
    if kernel_name.casefold() in {
        name.casefold() for name in tryboot.DEFAULT_KERNEL_NAMES | tryboot.RESERVED_NAMES
    }:
        raise PlacementError("staged kernel name is not an alternate basename")
    if kernel_name.casefold() == image_name.casefold():
        raise PlacementError("staged kernel and E1 image names collide")

    file_values = placement.get("files")
    if not isinstance(file_values, list):
        raise PlacementError("placement file inventory must be a list")
    file_records: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(file_values):
        record = tryboot.validate_file_record(value, f"placement file record {index}")
        if record["path"] in file_records:
            raise PlacementError("placement file inventory contains duplicate paths")
        file_records[record["path"]] = record
    if [record["path"] for record in file_values] != sorted(file_records):
        raise PlacementError("placement file inventory is not sorted")
    expected_roles = {
        tryboot.TRYBOOT_NAME: "tryboot_config",
        tryboot.CMDLINE_NAME: "alternate_cmdline",
        kernel_name: "alternate_kernel",
        image_name: "alternate_initramfs",
        tryboot.ACCEPTED_MANIFEST_NAME: "accepted_e1_manifest",
    }
    if set(file_records) != set(expected_roles):
        raise PlacementError("placement file inventory is incomplete or contains extras")
    expected_names = set(expected_roles) | {tryboot.PLACEMENT_MANIFEST_NAME}
    if set(snapshots) != expected_names:
        raise PlacementError("stage directory is incomplete or contains extra entries")
    for name, role in expected_roles.items():
        record = tryboot.validate_file_record(
            file_records[name],
            f"staged file {name}",
            expected_path=name,
            expected_role=role,
        )
        actual = snapshots[name]
        if record["size"] != actual.size or record["sha256"] != actual.sha256:
            raise PlacementError(f"staged file hash/size mismatch: {name}")
    if staged_kernel != file_records[kernel_name]:
        raise PlacementError("nested staged kernel record differs from file inventory")
    if (
        kernel_input["size"] != staged_kernel["size"]
        or kernel_input["sha256"] != staged_kernel["sha256"]
    ):
        raise PlacementError("kernel input and staged kernel are not byte-identical")

    accepted_raw = small[tryboot.ACCEPTED_MANIFEST_NAME]
    accepted = decode_json_object(accepted_raw, "accepted E1 manifest")
    if (
        accepted.get("schema") != early.SCHEMA
        or e1_record.get("schema") != early.SCHEMA
    ):
        raise PlacementError("accepted E1 manifest schema is not accepted")
    adopt = accepted.get("adopt")
    if (
        not isinstance(adopt, dict)
        or adopt.get("schema") != tryboot.ADOPT_SCHEMA
        or set(adopt) != {"schema", "packages", "gadget"}
        or not isinstance(adopt.get("packages"), dict)
        or not isinstance(adopt.get("gadget"), dict)
    ):
        raise PlacementError("accepted E1 manifest lacks the required adopt contract")
    try:
        base = tryboot.require_exact_object(
            accepted["base"],
            {"name", "size", "sha256", "zstd_offset", "prefix", "suffix"},
            "accepted E1 base record",
        )
        overlay = tryboot.require_exact_object(
            accepted["overlay"],
            {"alignment", "files", "sha256", "size"},
            "accepted E1 overlay record",
        )
        output = tryboot.require_exact_object(
            accepted["output"],
            {"name", "size", "sha256", "zstd_offset"},
            "accepted E1 output record",
        )
        base_offset = base["zstd_offset"]
        overlay_size = overlay["size"]
        output_offset = output["zstd_offset"]
    except (KeyError, TypeError) as exc:
        raise PlacementError("accepted E1 manifest lacks image boundary records") from exc
    if not all(
        isinstance(value, int) and not isinstance(value, bool)
        for value in (base_offset, overlay_size, output_offset)
    ):
        raise PlacementError("accepted E1 offsets and sizes must be integers")
    image = snapshots[image_name]
    if (
        base_offset < 0
        or overlay_size <= 0
        or output_offset != base_offset + overlay_size
        or output_offset > image.size
    ):
        raise PlacementError("accepted E1 manifest has an invalid image boundary")
    if (
        output.get("name") != image_name
        or output.get("size") != image.size
        or output.get("sha256") != image.sha256
    ):
        raise PlacementError("accepted E1 output differs from the pinned staged image")
    if e1_record != {
        "schema": accepted["schema"],
        "image_name": image_name,
        "image_sha256": image.sha256,
        "manifest_sha256": sha256_bytes(accepted_raw),
    }:
        raise PlacementError("placement E1 record differs from accepted E1 manifest")
    if placement.get("source") != accepted.get("source"):
        raise PlacementError("placement source differs from accepted E1 manifest")
    if placement.get("profile") != accepted.get("profile"):
        raise PlacementError("placement profile differs from accepted E1 manifest")
    release = kernel_record.get("release")
    if release != accepted.get("kernel_release"):
        raise PlacementError("staged kernel release differs from accepted E1 manifest")
    if kernel_record.get("compression") not in {"gzip", "none"}:
        raise PlacementError("staged kernel compression record is invalid")
    if kernel_record.get("payload_format") not in {"elf", "arm64-image"}:
        raise PlacementError("staged kernel payload format record is invalid")

    normal_inputs = tryboot.require_exact_object(
        placement.get("normal_boot_inputs"),
        {"config", "cmdline"},
        "normal boot inputs",
    )
    config_record = tryboot.validate_file_record(
        normal_inputs.get("config"),
        "normal config record",
        expected_path="config.txt",
        expected_role="normal_config_input",
    )
    cmdline_record = tryboot.validate_file_record(
        normal_inputs.get("cmdline"),
        "normal cmdline record",
        expected_path="cmdline.txt",
        expected_role="normal_cmdline_input",
    )
    tryboot_raw = small[tryboot.TRYBOOT_NAME]
    normal_config = tryboot_raw[: config_record["size"]]
    if (
        len(normal_config) != config_record["size"]
        or sha256_bytes(normal_config) != config_record["sha256"]
        or tryboot.render_tryboot(normal_config, kernel_name, image_name) != tryboot_raw
    ):
        raise PlacementError("tryboot config is not linked to recorded normal config")
    alternate_cmdline = small[tryboot.CMDLINE_NAME]
    normal_cmdline = tryboot.reconstruct_normal_cmdline(alternate_cmdline)
    if (
        len(normal_cmdline) != cmdline_record["size"]
        or sha256_bytes(normal_cmdline) != cmdline_record["sha256"]
        or tryboot.render_cmdline(normal_cmdline) != alternate_cmdline
    ):
        raise PlacementError("alternate cmdline is not linked to recorded normal cmdline")
    expected_activation = {
        "default_boot_modified": False,
        "one_shot_only": True,
        "tryboot_config": tryboot.TRYBOOT_NAME,
        "alternate_cmdline": tryboot.CMDLINE_NAME,
        "cmdline_tokens_added": ["hidloom.early=e1", "panic=10"],
        "panic_seconds": 10,
    }
    if placement.get("activation") != expected_activation:
        raise PlacementError("placement activation contract is invalid")
    return accepted


def secure_stage_snapshot(
    stage_dir: Path, owner_uid: int, expected_placement_sha256: str
) -> tuple[
    dict[str, VerifiedFile], dict[str, bytes], dict[str, Any], dict[str, Any]
]:
    stage_dir = secure_directory(stage_dir, "stage directory", owner_uid)
    if stat.S_IMODE(stage_dir.stat().st_mode) != 0o755:
        raise PlacementError("stage directory mode must be 0755")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_placement_sha256):
        raise PlacementError("expected placement SHA-256 must be 64 lowercase hex digits")
    try:
        names_before = sorted(item.name for item in stage_dir.iterdir())
    except OSError as exc:
        raise PlacementError(f"cannot enumerate stage directory: {exc}") from exc
    if tryboot.PLACEMENT_MANIFEST_NAME not in names_before:
        raise PlacementError("stage directory lacks tryboot-placement.json")
    if len({name.casefold() for name in names_before}) != len(names_before):
        raise PlacementError("stage directory contains case-colliding names")
    snapshots: dict[str, VerifiedFile] = {}
    try:
        for name in names_before:
            tryboot.safe_basename(name, "stage filename")
            snapshots[name] = inspect_regular(
                stage_dir / name,
                f"staged file {name}",
                owner_uid,
                exact_mode=0o644,
                retain_fd=True,
            )
        if sum(item.size for item in snapshots.values()) > MAX_TOTAL_STAGE_BYTES:
            raise PlacementError("stage directory exceeds the total size safety bound")
        placement_file = snapshots[tryboot.PLACEMENT_MANIFEST_NAME]
        placement_raw = read_verified_small(
            placement_file, "placement manifest", owner_uid
        )
        placement_sha256 = sha256_bytes(placement_raw)
        if placement_sha256 != expected_placement_sha256:
            raise PlacementError(
                "placement manifest differs from the host deep-verification digest"
            )
        placement = decode_json_object(placement_raw, "placement manifest")
        small_names = {
            tryboot.PLACEMENT_MANIFEST_NAME,
            tryboot.ACCEPTED_MANIFEST_NAME,
            tryboot.TRYBOOT_NAME,
            tryboot.CMDLINE_NAME,
        }
        if not small_names <= snapshots.keys():
            raise PlacementError("stage directory lacks required control files")
        small = {
            name: (
                placement_raw
                if name == tryboot.PLACEMENT_MANIFEST_NAME
                else read_verified_small(
                    snapshots[name],
                    f"staged control file {name}",
                    owner_uid,
                    max_bytes=(
                        MAX_MANIFEST_BYTES
                        if name == tryboot.ACCEPTED_MANIFEST_NAME
                        else (
                            MAX_CMDLINE_BYTES
                            if name == tryboot.CMDLINE_NAME
                            else MAX_CONTROL_FILE_BYTES
                        )
                    ),
                )
            )
            for name in small_names
        }
        accepted = verify_pinned_stage_contract(
            snapshots, small, placement, placement_raw
        )
        try:
            names_after = sorted(item.name for item in stage_dir.iterdir())
        except OSError as exc:
            raise PlacementError(f"cannot re-enumerate stage directory: {exc}") from exc
        if names_after != names_before:
            raise PlacementError("stage directory changed while being verified")
        return snapshots, small, placement, accepted
    except BaseException:
        close_verified_files(snapshots)
        raise


def normalize_text_file(data: bytes, label: str, *, allow_nul_suffix: bool = False) -> str:
    if allow_nul_suffix:
        data = data.rstrip(b"\x00\r\n")
    else:
        data = data.rstrip(b"\r\n")
        if b"\x00" in data:
            raise PlacementError(f"{label} contains NUL")
    if not data or b"\n" in data or b"\r" in data or b"\x00" in data:
        raise PlacementError(f"{label} is not exactly one non-empty line")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PlacementError(f"{label} is not UTF-8") from exc


def file_record(name: str, role: str, data: bytes) -> dict[str, Any]:
    return {
        "path": name,
        "role": role,
        "size": len(data),
        "sha256": sha256_bytes(data),
    }


def placement_file_records(placement: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    values = placement.get("files")
    if not isinstance(values, list):
        raise PlacementError("placement file inventory is invalid")
    for value in values:
        if not isinstance(value, dict):
            raise PlacementError("placement file record is invalid")
        name = tryboot.safe_basename(value.get("path", ""), "placement filename")
        records[name] = value
    return records


def directory_casefold_names(directory: Path, label: str) -> dict[str, str]:
    try:
        names = [item.name for item in directory.iterdir()]
    except OSError as exc:
        raise PlacementError(f"cannot enumerate {label}: {directory}: {exc}") from exc
    folded: dict[str, str] = {}
    for name in names:
        key = name.casefold()
        if key in folded and folded[key] != name:
            raise PlacementError(f"{label} contains case-colliding names: {folded[key]}, {name}")
        folded[key] = name
    return folded


def ensure_absent_names(directory: Path, names: set[str], label: str) -> None:
    present = directory_casefold_names(directory, label)
    for name in sorted(names):
        match = present.get(name.casefold())
        if match is not None:
            raise PlacementError(f"{label} destination already exists: {match}")


def existing_storage_root(path: Path, exists: bool) -> Path:
    return path if exists else path.parent


def check_free_space(
    boot_root: Path,
    boot_bytes: int,
    accepted_root: Path,
    accepted_exists: bool,
    accepted_bytes: int,
    backup_dir: Path,
    backup_bytes: int,
    reserve: int,
) -> list[dict[str, Any]]:
    requirements: dict[int, dict[str, Any]] = {}
    for label, root, needed in (
        ("boot", boot_root, boot_bytes),
        ("accepted", existing_storage_root(accepted_root, accepted_exists), accepted_bytes),
        ("backup", backup_dir.parent, backup_bytes),
    ):
        try:
            details = root.stat()
            values = os.statvfs(root)
        except OSError as exc:
            raise PlacementError(f"cannot inspect free space for {label}: {root}: {exc}") from exc
        item = requirements.setdefault(
            details.st_dev,
            {
                "device": details.st_dev,
                "paths": [],
                "required_bytes": reserve,
                "available_bytes": values.f_bavail * values.f_frsize,
            },
        )
        item["paths"].append(str(root))
        item["required_bytes"] += needed
        item["available_bytes"] = min(
            item["available_bytes"], values.f_bavail * values.f_frsize
        )
    result = sorted(requirements.values(), key=lambda item: item["device"])
    for item in result:
        item["paths"] = sorted(set(item["paths"]))
        if item["available_bytes"] < item["required_bytes"]:
            raise PlacementError(
                "insufficient free space for "
                f"{', '.join(item['paths'])}: {item['available_bytes']} < "
                f"{item['required_bytes']} bytes"
            )
    return result


def verified_file_record(name: str, role: str, source: VerifiedFile) -> dict[str, Any]:
    return {
        "path": name,
        "role": role,
        "size": source.size,
        "sha256": source.sha256,
    }


def build_context(args: argparse.Namespace, state: str) -> PlacementContext:
    if args.expected_owner_uid < 0:
        raise PlacementError("expected owner UID must be non-negative")
    if args.minimum_free_bytes < 0:
        raise PlacementError("minimum free bytes must be non-negative")

    stage_dir = secure_directory(args.stage_dir, "stage directory", args.expected_owner_uid)
    boot_root = secure_directory(args.boot_root, "boot root", args.expected_owner_uid)
    accepted_root, accepted_exists = destination_directory(
        args.accepted_root, "accepted root", args.expected_owner_uid
    )
    backup_dir, backup_exists = destination_directory(
        args.backup_dir, "backup directory", args.expected_owner_uid
    )
    require_separate_roots(stage_dir, boot_root, accepted_root, backup_dir)

    if state == "absent" and backup_exists:
        raise PlacementError(f"backup directory already exists: {backup_dir}")
    if state == "installed" and not backup_exists:
        raise PlacementError(f"backup directory is missing: {backup_dir}")

    stage: dict[str, VerifiedFile] = {}
    normal_files: dict[str, VerifiedFile] = {}
    try:
        stage, stage_small, placement, accepted_manifest = secure_stage_snapshot(
            stage_dir,
            args.expected_owner_uid,
            args.expected_placement_sha256,
        )
        placement_raw = stage_small[tryboot.PLACEMENT_MANIFEST_NAME]
        placement_sha = sha256_bytes(placement_raw)
        kernel = placement.get("kernel")
        normal = placement.get("normal_boot_inputs")
        if not isinstance(kernel, dict) or not isinstance(normal, dict):
            raise PlacementError("verified placement manifest lacks normal input records")
        kernel_release = kernel.get("release")
        if not isinstance(kernel_release, str) or args.expected_kernel_release != kernel_release:
            raise PlacementError(
                "expected kernel release differs from the staged E1 kernel release"
            )

        model_path = args.model_path.resolve(strict=True)
        release_path = args.kernel_release_path.resolve(strict=True)
        live_model = normalize_text_file(
            read_bounded_pseudo_file(
                model_path, "live Raspberry Pi model", args.expected_owner_uid, max_bytes=4096
            ),
            "live Raspberry Pi model",
            allow_nul_suffix=True,
        )
        if live_model != args.expected_model:
            raise PlacementError(
                f"live model mismatch: {live_model!r} != {args.expected_model!r}"
            )
        live_release = normalize_text_file(
            read_bounded_pseudo_file(
                release_path, "live kernel release", args.expected_owner_uid, max_bytes=4096
            ),
            "live kernel release",
        )
        if live_release != args.expected_kernel_release:
            raise PlacementError(
                f"live kernel release mismatch: {live_release!r} != "
                f"{args.expected_kernel_release!r}"
            )

        config_record = normal.get("config")
        cmdline_record = normal.get("cmdline")
        kernel_input = kernel.get("input")
        if not all(
            isinstance(item, dict) for item in (config_record, cmdline_record, kernel_input)
        ):
            raise PlacementError("normal boot input records are invalid")
        config_name = tryboot.safe_basename(
            config_record.get("path", ""), "normal config name"
        )
        cmdline_name = tryboot.safe_basename(
            cmdline_record.get("path", ""), "normal cmdline name"
        )
        kernel_name = tryboot.safe_basename(
            kernel_input.get("path", ""), "default kernel name"
        )
        initramfs_name = tryboot.safe_basename(
            args.normal_initramfs_name, "normal initramfs name"
        )
        if config_name != "config.txt" or cmdline_name != "cmdline.txt":
            raise PlacementError("normal config/cmdline names are not canonical")
        if kernel_name not in tryboot.DEFAULT_KERNEL_NAMES:
            raise PlacementError(
                f"recorded normal kernel is not a default kernel name: {kernel_name}"
            )

        records = placement_file_records(placement)
        accepted_name = tryboot.ACCEPTED_MANIFEST_NAME
        if accepted_name not in records:
            raise PlacementError("placement inventory lacks the accepted manifest")
        boot_records = {
            name: record for name, record in records.items() if name != accepted_name
        }
        if tryboot.TRYBOOT_NAME not in boot_records:
            raise PlacementError("placement inventory lacks tryboot.txt")
        collisions = set(boot_records) | {kernel_name, config_name, cmdline_name}
        if initramfs_name in collisions or initramfs_name.casefold() in {
            name.casefold() for name in collisions
        }:
            raise PlacementError("normal initramfs name collides with a staged/default boot name")

        normal_paths = {
            "config": boot_root / config_name,
            "cmdline": boot_root / cmdline_name,
            "kernel": boot_root / kernel_name,
            "initramfs": boot_root / initramfs_name,
        }
        for key, path in normal_paths.items():
            normal_files[key] = inspect_regular(
                path,
                f"normal {key}",
                args.expected_owner_uid,
                retain_fd=True,
            )
        normal_small = {
            "config": read_verified_small(
                normal_files["config"],
                "normal config",
                args.expected_owner_uid,
                max_bytes=MAX_CONTROL_FILE_BYTES,
            ),
            "cmdline": read_verified_small(
                normal_files["cmdline"],
                "normal cmdline",
                args.expected_owner_uid,
                max_bytes=MAX_CMDLINE_BYTES,
            ),
        }
        for label, record in (
            ("config", config_record),
            ("cmdline", cmdline_record),
            ("kernel", kernel_input),
        ):
            source = normal_files[label]
            if record.get("size") != source.size or record.get("sha256") != source.sha256:
                raise PlacementError(
                    f"live normal {label} differs from the staged input hash/size"
                )

        base = tryboot.require_exact_object(
            accepted_manifest.get("base"),
            {"name", "size", "sha256", "zstd_offset", "prefix", "suffix"},
            "accepted E1 base record",
        )
        base_name = tryboot.safe_basename(base.get("name", ""), "accepted E1 base name")
        if base_name != initramfs_name:
            raise PlacementError(
                "normal initramfs name differs from the accepted E1 base name"
            )
        normal_initramfs = normal_files["initramfs"]
        if (
            base.get("size") != normal_initramfs.size
            or base.get("sha256") != normal_initramfs.sha256
        ):
            raise PlacementError(
                "live normal initramfs differs from the accepted E1 base hash/size"
            )

        normal_records = {
            "config": verified_file_record(
                config_name, "normal_config", normal_files["config"]
            ),
            "cmdline": verified_file_record(
                cmdline_name, "normal_cmdline", normal_files["cmdline"]
            ),
            "kernel": verified_file_record(
                kernel_name, "normal_kernel", normal_files["kernel"]
            ),
            "initramfs": verified_file_record(
                initramfs_name, "normal_initramfs", normal_files["initramfs"]
            ),
        }

        if state == "absent":
            ensure_absent_names(
                boot_root,
                FORBIDDEN_BOOT_NAMES | set(boot_records),
                "boot root",
            )
            if accepted_exists:
                ensure_absent_names(
                    accepted_root,
                    {tryboot.ACCEPTED_MANIFEST_NAME, RECEIPT_NAME},
                    "accepted root",
                )
        else:
            ensure_absent_names(boot_root, FORBIDDEN_BOOT_NAMES, "boot root")
            if not accepted_exists:
                raise PlacementError(f"accepted root is missing: {accepted_root}")

        # The receipt and backup JSON are intentionally bounded above here.
        boot_bytes = sum(stage[name].size for name in boot_records)
        accepted_bytes = stage[accepted_name].size + 256 * 1024
        backup_bytes = sum(item.size for item in normal_files.values()) + 256 * 1024
        free_space = []
        if state == "absent":
            free_space = check_free_space(
                boot_root,
                boot_bytes,
                accepted_root,
                accepted_exists,
                accepted_bytes,
                backup_dir,
                backup_bytes,
                args.minimum_free_bytes,
            )
        return PlacementContext(
            stage_dir=stage_dir,
            boot_root=boot_root,
            accepted_root=accepted_root,
            accepted_root_exists=accepted_exists,
            backup_dir=backup_dir,
            model_path=model_path,
            kernel_release_path=release_path,
            expected_owner_uid=args.expected_owner_uid,
            placement=placement,
            accepted_manifest=accepted_manifest,
            stage=stage,
            stage_small=stage_small,
            placement_sha256=placement_sha,
            boot_records=boot_records,
            normal_paths=normal_paths,
            normal_files=normal_files,
            normal_small=normal_small,
            normal_records=normal_records,
            expected_model=args.expected_model,
            kernel_release=kernel_release,
            minimum_free_bytes=args.minimum_free_bytes,
            free_space=free_space,
        )
    except BaseException:
        close_verified_files(normal_files, stage)
        raise


def close_context(context: PlacementContext) -> None:
    close_verified_files(context.normal_files, context.stage)


def assert_normal_unchanged(context: PlacementContext) -> None:
    for label, source in context.normal_files.items():
        assert_verified_file_unchanged(
            source,
            f"normal {label}",
            context.expected_owner_uid,
        )


def backup_manifest(context: PlacementContext) -> dict[str, Any]:
    return {
        "schema": BACKUP_SCHEMA,
        "boot_root": str(context.boot_root),
        "placement_sha256": context.placement_sha256,
        "kernel_release": context.kernel_release,
        "model": context.expected_model,
        "files": [context.normal_records[key] for key in sorted(context.normal_records)],
    }


def install_receipt(context: PlacementContext, backup_raw: bytes) -> dict[str, Any]:
    accepted = context.stage[tryboot.ACCEPTED_MANIFEST_NAME]
    return {
        "schema": SCHEMA,
        "status": "installed-disabled",
        "placement_sha256": context.placement_sha256,
        "source": context.placement.get("source"),
        "kernel_release": context.kernel_release,
        "model": context.expected_model,
        "normal_boot_inputs": {
            key: context.normal_records[key] for key in sorted(context.normal_records)
        },
        "backup": {
            "directory": str(context.backup_dir),
            "manifest": file_record(
                BACKUP_MANIFEST_NAME, "normal_boot_backup_manifest", backup_raw
            ),
        },
        "installed": {
            "boot_root": str(context.boot_root),
            "boot_files": [
                context.boot_records[name] for name in sorted(context.boot_records)
            ],
            "accepted_root": str(context.accepted_root),
            "accepted_manifest": verified_file_record(
                tryboot.ACCEPTED_MANIFEST_NAME,
                "accepted_e1_manifest",
                accepted,
            ),
        },
        "activation": {
            "default_boot_modified": False,
            "one_shot_requested": False,
            "tryboot_published_last": True,
            "reboot_requested": False,
        },
    }


def fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    fd = os.open(path, flags)
    try:
        try:
            os.fsync(fd)
        except OSError as exc:
            # Some FAT implementations do not expose directory fsync.  Every
            # payload file itself has already been fsynced before publication.
            if exc.errno not in {errno.EINVAL, errno.ENOTSUP, errno.EROFS}:
                raise
    finally:
        os.close(fd)


def rename_noreplace(source: Path, destination: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    function = getattr(libc, "renameat2", None)
    if function is None:
        raise PlacementError("renameat2(RENAME_NOREPLACE) is unavailable")
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    result = function(
        AT_FDCWD,
        os.fsencode(source),
        AT_FDCWD,
        os.fsencode(destination),
        RENAME_NOREPLACE,
    )
    if result != 0:
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise PlacementError(f"destination already exists: {destination}")
        raise PlacementError(
            f"cannot atomically publish {destination}: {os.strerror(code)}"
        )


def unlink_created(created: CreatedFile) -> str | None:
    try:
        details = created.path.lstat()
        if not stat.S_ISREG(details.st_mode):
            return f"refused rollback of non-regular path: {created.path}"
        identity_matches = (details.st_dev, details.st_ino) == (
            created.device,
            created.inode,
        )
        actual = inspect_regular(
            created.path,
            f"rollback candidate {created.path.name}",
            details.st_uid,
        )
        content_matches = actual.size == created.size and actual.sha256 == created.sha256
        if not identity_matches or not content_matches:
            return f"refused rollback of changed path: {created.path}"
        created.path.unlink()
        return None
    except FileNotFoundError:
        return None
    except (OSError, PlacementError) as exc:
        return f"cannot roll back {created.path}: {exc}"


def publish_bytes(parent: Path, name: str, data: bytes, mode: int) -> CreatedFile:
    name = tryboot.safe_basename(name, "published filename")
    destination = parent / name
    if path_exists(destination):
        raise PlacementError(f"destination already exists: {destination}")
    fd: int | None = None
    temporary: Path | None = None
    published: CreatedFile | None = None
    try:
        fd, raw_temporary = tempfile.mkstemp(prefix=".hidloom-e2-place-", dir=parent)
        temporary = Path(raw_temporary)
        os.fchmod(fd, mode)
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise PlacementError(f"short write while publishing {destination}")
            view = view[written:]
        os.fsync(fd)
        temporary_details = os.fstat(fd)
        candidate = CreatedFile(
            path=destination,
            device=temporary_details.st_dev,
            inode=temporary_details.st_ino,
            size=len(data),
            sha256=sha256_bytes(data),
        )
        os.close(fd)
        fd = None
        rename_noreplace(temporary, destination)
        temporary = None
        # Record ownership of the new inode immediately after publication so
        # even a failure in the following lstat/read/fsync path can remove only
        # the file created by this invocation.
        published = candidate
        details = destination.lstat()
        if not stat.S_ISREG(details.st_mode):
            raise PlacementError(f"published destination is not regular: {destination}")
        if (details.st_dev, details.st_ino) != (candidate.device, candidate.inode):
            raise PlacementError(f"published destination inode changed: {destination}")
        actual = destination.read_bytes()
        if actual != data:
            raise PlacementError(f"published bytes differ at {destination}")
        fsync_directory(parent)
        return published
    except OSError as exc:
        raise PlacementError(f"cannot publish {destination}: {exc}") from exc
    finally:
        failed = sys.exc_info()[0] is not None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
        if failed and published is not None:
            cleanup_error = unlink_created(published)
            if cleanup_error is not None:
                # Raising here deliberately replaces the original exception:
                # incomplete rollback is the higher-priority operator signal.
                raise PlacementError(cleanup_error)


def publish_verified_file(
    parent: Path,
    name: str,
    source: VerifiedFile,
    mode: int,
    owner_uid: int,
) -> CreatedFile:
    """Atomically publish one retained source without materializing it in RAM."""
    name = tryboot.safe_basename(name, "published filename")
    destination = parent / name
    if path_exists(destination):
        raise PlacementError(f"destination already exists: {destination}")
    assert_verified_file_unchanged(
        source, f"source file {source.path.name}", owner_uid, exact_mode=source.mode
    )
    fd: int | None = None
    temporary: Path | None = None
    published: CreatedFile | None = None
    try:
        fd, raw_temporary = tempfile.mkstemp(prefix=".hidloom-e2-place-", dir=parent)
        temporary = Path(raw_temporary)
        os.fchmod(fd, mode)
        os.lseek(source.fd, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        total = 0
        remaining = source.size
        while remaining:
            chunk = os.read(source.fd, min(1024 * 1024, remaining))
            if not chunk:
                raise PlacementError(f"short read while copying {source.path}")
            digest.update(chunk)
            total += len(chunk)
            remaining -= len(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise PlacementError(f"short write while publishing {destination}")
                view = view[written:]
        if os.read(source.fd, 1):
            raise PlacementError(f"source grew while copying {source.path}")
        if total != source.size or digest.hexdigest() != source.sha256:
            raise PlacementError(f"source bytes changed while copying {source.path}")
        assert_verified_file_unchanged(
            source, f"source file {source.path.name}", owner_uid, exact_mode=source.mode
        )
        os.fsync(fd)
        temporary_details = os.fstat(fd)
        candidate = CreatedFile(
            path=destination,
            device=temporary_details.st_dev,
            inode=temporary_details.st_ino,
            size=source.size,
            sha256=source.sha256,
        )
        os.close(fd)
        fd = None
        rename_noreplace(temporary, destination)
        temporary = None
        published = candidate
        actual = inspect_regular(
            destination,
            f"published file {name}",
            owner_uid,
        )
        if (
            (actual.device, actual.inode) != (candidate.device, candidate.inode)
            or actual.size != candidate.size
            or actual.sha256 != candidate.sha256
        ):
            raise PlacementError(f"published file differs at {destination}")
        fsync_directory(parent)
        return published
    except OSError as exc:
        raise PlacementError(f"cannot publish {destination}: {exc}") from exc
    finally:
        failed = sys.exc_info()[0] is not None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if temporary is not None:
            try:
                temporary.unlink()
            except (FileNotFoundError, OSError):
                pass
        if failed and published is not None:
            cleanup_error = unlink_created(published)
            if cleanup_error is not None:
                raise PlacementError(cleanup_error)


def verify_file_record(
    path: Path,
    label: str,
    expected: VerifiedFile,
    owner_uid: int,
    *,
    exact_mode: int | None = None,
) -> None:
    actual = inspect_regular(
        path,
        label,
        owner_uid,
        exact_mode=exact_mode,
    )
    if actual.size != expected.size or actual.sha256 != expected.sha256:
        raise PlacementError(f"{label} hash/size differs from the installation receipt")


def verify_bytes(
    path: Path,
    label: str,
    expected: bytes,
    owner_uid: int,
    *,
    exact_mode: int | None = None,
) -> None:
    actual = read_regular(
        path,
        label,
        owner_uid,
        exact_mode=exact_mode,
        max_bytes=len(expected),
    )
    if actual != expected:
        raise PlacementError(f"{label} hash/size differs from the installation receipt")


def verify_installed_context(context: PlacementContext) -> dict[str, Any]:
    assert_normal_unchanged(context)
    backup_raw = canonical_bytes(backup_manifest(context))
    receipt_raw = canonical_bytes(install_receipt(context, backup_raw))
    expected_backup_names = {
        record["path"] for record in context.normal_records.values()
    } | {BACKUP_MANIFEST_NAME}
    actual_backup_names = set(directory_casefold_names(context.backup_dir, "backup directory").values())
    if actual_backup_names != expected_backup_names:
        raise PlacementError("backup directory inventory differs from the receipt")
    for key, path in context.normal_paths.items():
        verify_file_record(
            context.backup_dir / path.name,
            f"backup {key}",
            context.normal_files[key],
            context.expected_owner_uid,
            exact_mode=0o600,
        )
    verify_bytes(
        context.backup_dir / BACKUP_MANIFEST_NAME,
        "backup manifest",
        backup_raw,
        context.expected_owner_uid,
        exact_mode=0o600,
    )
    for name in sorted(context.boot_records):
        # Raspberry Pi OS mounts the boot VFAT with fmask=0022, so files can
        # appear as 0755 even though the source and requested mode were 0644.
        verify_file_record(
            context.boot_root / name,
            f"installed boot file {name}",
            context.stage[name],
            context.expected_owner_uid,
        )
    verify_file_record(
        context.accepted_root / tryboot.ACCEPTED_MANIFEST_NAME,
        "installed accepted manifest",
        context.stage[tryboot.ACCEPTED_MANIFEST_NAME],
        context.expected_owner_uid,
        exact_mode=0o600,
    )
    verify_bytes(
        context.accepted_root / RECEIPT_NAME,
        "install receipt",
        receipt_raw,
        context.expected_owner_uid,
        exact_mode=0o600,
    )
    return {
        "status": "pass",
        "schema": SCHEMA,
        "state": "installed-disabled",
        "source": context.placement.get("source"),
        "kernel_release": context.kernel_release,
        "model": context.expected_model,
        "placement_sha256": context.placement_sha256,
        "default_boot_modified": False,
        "one_shot_requested": False,
        "boot_files": len(context.boot_records),
    }


def preflight(args: argparse.Namespace) -> dict[str, Any]:
    context = build_context(args, "absent")
    try:
        assert_normal_unchanged(context)
        return {
            "status": "pass",
            "schema": SCHEMA,
            "state": "placement-ready-disabled",
            "source": context.placement.get("source"),
            "kernel_release": context.kernel_release,
            "model": context.expected_model,
            "placement_sha256": context.placement_sha256,
            "verification": "host-deep-verified-digest+device-streaming",
            "normal_inputs": len(context.normal_paths),
            "boot_files": len(context.boot_records),
            "free_space": context.free_space,
            "default_boot_modified": False,
            "one_shot_requested": False,
        }
    finally:
        close_context(context)


def install_disabled(args: argparse.Namespace) -> dict[str, Any]:
    context = build_context(args, "absent")
    created_files: list[CreatedFile] = []
    created_directories: list[Path] = []
    try:
        assert_normal_unchanged(context)
        os.mkdir(context.backup_dir, 0o700)
        created_directories.append(context.backup_dir)
        for key in sorted(context.normal_paths):
            created_files.append(
                publish_verified_file(
                    context.backup_dir,
                    context.normal_paths[key].name,
                    context.normal_files[key],
                    0o600,
                    context.expected_owner_uid,
                )
            )
        backup_raw = canonical_bytes(backup_manifest(context))
        created_files.append(
            publish_bytes(
                context.backup_dir, BACKUP_MANIFEST_NAME, backup_raw, 0o600
            )
        )
        assert_normal_unchanged(context)

        if not context.accepted_root_exists:
            os.mkdir(context.accepted_root, 0o755)
            created_directories.append(context.accepted_root)
        for name in sorted(context.boot_records):
            if name == tryboot.TRYBOOT_NAME:
                continue
            created_files.append(
                publish_verified_file(
                    context.boot_root,
                    name,
                    context.stage[name],
                    0o644,
                    context.expected_owner_uid,
                )
            )
        created_files.append(
            publish_verified_file(
                context.accepted_root,
                tryboot.ACCEPTED_MANIFEST_NAME,
                context.stage[tryboot.ACCEPTED_MANIFEST_NAME],
                0o600,
                context.expected_owner_uid,
            )
        )
        receipt_raw = canonical_bytes(install_receipt(context, backup_raw))
        created_files.append(
            publish_bytes(context.accepted_root, RECEIPT_NAME, receipt_raw, 0o600)
        )

        # This is the final publication in the transaction.  It merely makes
        # a tryboot configuration available; it does not set the one-shot flag.
        assert_normal_unchanged(context)
        created_files.append(
            publish_verified_file(
                context.boot_root,
                tryboot.TRYBOOT_NAME,
                context.stage[tryboot.TRYBOOT_NAME],
                0o644,
                context.expected_owner_uid,
            )
        )
        assert_normal_unchanged(context)
        result = verify_installed_context(context)
        result["state"] = "installed-disabled"
        result["backup_dir"] = str(context.backup_dir)
        result["accepted_root"] = str(context.accepted_root)
        return result
    except (OSError, PlacementError) as exc:
        rollback_errors: list[str] = []
        for created in reversed(created_files):
            error = unlink_created(created)
            if error is not None:
                rollback_errors.append(error)
        for directory in reversed(created_directories):
            try:
                directory.rmdir()
            except FileNotFoundError:
                pass
            except OSError as rollback_exc:
                rollback_errors.append(f"cannot remove created directory {directory}: {rollback_exc}")
        if rollback_errors:
            raise PlacementError(
                f"placement failed: {exc}; incomplete safe rollback: "
                + "; ".join(rollback_errors)
            ) from exc
        raise PlacementError(f"placement failed and newly created files were rolled back: {exc}") from exc
    finally:
        close_context(context)


def verify_installed(args: argparse.Namespace) -> dict[str, Any]:
    context = build_context(args, "installed")
    try:
        return verify_installed_context(context)
    finally:
        close_context(context)


def add_common_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--stage-dir", type=Path, required=True)
    command.add_argument("--boot-root", type=Path, required=True)
    command.add_argument("--accepted-root", type=Path, required=True)
    command.add_argument("--backup-dir", type=Path, required=True)
    command.add_argument("--normal-initramfs-name", required=True)
    command.add_argument("--model-path", type=Path, required=True)
    command.add_argument("--expected-model", required=True)
    command.add_argument("--kernel-release-path", type=Path, required=True)
    command.add_argument("--expected-kernel-release", required=True)
    command.add_argument(
        "--expected-placement-sha256",
        required=True,
        help="placement_sha256 from the successful host-side deep verify",
    )
    command.add_argument("--expected-owner-uid", type=int, default=0)
    command.add_argument(
        "--minimum-free-bytes",
        type=int,
        default=DEFAULT_MINIMUM_FREE_BYTES,
        help="free-space reserve retained after accounting for all writes",
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("preflight", "verify placement inputs without changing the device"),
        ("install-disabled", "back up and place tryboot files without activation"),
        ("verify-installed", "verify the disabled placement and unchanged defaults"),
    ):
        command = commands.add_parser(name, help=help_text)
        add_common_arguments(command)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "preflight":
            result = preflight(args)
        elif args.command == "install-disabled":
            result = install_disabled(args)
        else:
            result = verify_installed(args)
    except (
        OSError,
        KeyError,
        TypeError,
        UnicodeError,
        json.JSONDecodeError,
        tryboot.StageError,
        PlacementError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
