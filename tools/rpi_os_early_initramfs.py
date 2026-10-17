#!/usr/bin/env python3
"""Build and verify the Raspberry Pi OS E1 early-gadget initramfs overlay.

The Raspberry Pi OS image accepted here has exactly this shape::

    uncompressed newc archive + NUL padding + zstd-compressed newc archive

The builder never appends after the compressed archive.  It inserts a second,
deterministic newc archive immediately before the zstd frame and records hashes
that allow the verifier to prove that both parts of the source image survived
byte-for-byte.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from typing import Any


SCHEMA = "hidloom.rpi-os-early-initramfs.e1.v1"
NATIVE_INPUT_SCHEMA = "hidloom.rpi-os-early-native-input.e3.v1"
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
CPIO_MAGICS = {b"070701", b"070702"}
FIXED_MTIME = 0

BASE_FILE_MODES = {
    "conf/param.conf": 0o100644,
    "conf/hidloom-early-usb.env": 0o100644,
    "conf/hidloom-early-contract.json": 0o100644,
    "scripts/init-premount/hidloom-early-gadget": 0o100755,
    "usr/lib/hidloom/early/hidloom-usb-gadget-fast": 0o100755,
    "usr/lib/hidloom/early/modules/libcomposite.ko": 0o100644,
    "usr/lib/hidloom/early/modules/usb_f_hid.ko": 0o100644,
}
NATIVE_FILE_MODES = {
    "scripts/init-bottom/hidloom-early-input": 0o100755,
    "usr/lib/hidloom/early/hidloom-early-input-launch": 0o100755,
    "usr/lib/hidloom/early/hidloom-hidd": 0o100755,
    "usr/lib/hidloom/early/hidloom-outputd": 0o100755,
    "usr/lib/hidloom/early/hidloom-logicd-core": 0o100755,
    "usr/lib/hidloom/early/matrixd": 0o100755,
    "usr/lib/hidloom/early/keymap.json": 0o100644,
    "usr/lib/hidloom/early/keycodes.json": 0o100644,
    "usr/lib/hidloom/early/config.json": 0o100644,
    "usr/lib/hidloom/early/matrixd.json": 0o100644,
    "usr/lib/hidloom/early/modules/raspberrypi-gpiomem.ko": 0o100644,
}
ALL_FILE_MODES = {**BASE_FILE_MODES, **NATIVE_FILE_MODES}
# Kept as the original E1-only inventory for existing callers and fixtures.
FILE_MODES = BASE_FILE_MODES
DIR_MODES = {
    ".": 0o040755,
    "conf": 0o040755,
    "scripts": 0o040755,
    "scripts/init-bottom": 0o040755,
    "scripts/init-premount": 0o040755,
    "usr": 0o040755,
    "usr/lib": 0o040755,
    "usr/lib/hidloom": 0o040755,
    "usr/lib/hidloom/early": 0o040755,
    "usr/lib/hidloom/early/modules": 0o040755,
}
BASE_EXPECTED_PATHS = set(BASE_FILE_MODES) | set(DIR_MODES)
NATIVE_EXPECTED_PATHS = set(ALL_FILE_MODES) | set(DIR_MODES)
# Backward-compatible public fixture name for the original E1 inventory.
EXPECTED_PATHS = BASE_EXPECTED_PATHS

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
REQUIRED_IDENTITY_KEYS = IDENTITY_KEYS - {"HIDLOOM_USB_SERIAL_SUFFIX"}
BOOL_KEYS = {
    "HIDLOOM_USB_US_SUB_KEYBOARD",
    "HIDLOOM_WINDOWS_IME_CUSTOM_HID",
}
ORDER_PARAM_LINE = b"[ -e /conf/param.conf ] && . /conf/param.conf"

# E3's init-bottom hook and chrooted launcher use absolute paths for every
# external utility.  Keep this inventory explicit as a reviewable contract and
# compare it with paths extracted from both pinned templates before accepting a
# native image.  Shell builtins (for example printf, kill, wait, and test) are
# intentionally absent.
NATIVE_BASE_REQUIRED_COMMAND_PATHS = frozenset(
    {
        "/bin/cat",
        "/bin/sh",
        "/usr/bin/chmod",
        "/usr/bin/cp",
        "/usr/bin/cut",
        "/usr/bin/grep",
        "/usr/bin/ln",
        "/usr/bin/mkdir",
        "/usr/bin/mv",
        "/usr/bin/rm",
        "/usr/bin/sed",
        "/usr/bin/setsid",
        "/usr/bin/sleep",
        "/usr/bin/stat",
        "/usr/bin/timeout",
        "/usr/sbin/chroot",
    }
)

# Production descriptor bytes from tools/hidloom_usb_gadget_fast.  E1 must not
# boot a helper built with the earlier Buildroot-only descriptor contract.
REPORT_DESCRIPTORS = {
    "main": bytes.fromhex(
        "05010906a1018501050719e029e71500250175019508810295017508810395067508"
        "150026ff00050719002aff0081000508190129051500250175019505910275039501"
        "9103c005010902a10185020901a10005091901290515002501750195058102750395"
        "01810305010930093109381581257f750895038106c0c0050c0901a1018503150026"
        "ff0319002aff03751095018100c0"
    ),
    "raw": bytes.fromhex("0660ff0961a101150026ff007508952009628102952009639102c0"),
    "us_sub": bytes.fromhex(
        "05010906a101050719e029e715002501750195088102950175088103950675081500"
        "26ff00050719002aff00810005081901290515002501750195059102750395019103c0"
    ),
    "windows_ime_custom": bytes.fromhex(
        "0670ff0901a101150026ff007508950809028102950809039102c0"
    ),
}


class VerifyError(ValueError):
    """An input or artifact failed a fail-closed verification guard."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def align(value: int, boundary: int) -> int:
    return (value + boundary - 1) // boundary * boundary


def safe_archive_path(name: str) -> None:
    if not name or name.startswith("/") or "\x00" in name:
        raise VerifyError(f"unsafe cpio member path: {name!r}")
    if any(part in {"", ".."} for part in name.split("/")) and name != ".":
        raise VerifyError(f"unsafe cpio member path: {name!r}")


def parse_newc(data: bytes, start: int = 0) -> tuple[list[dict[str, Any]], int]:
    """Parse one newc archive and return records plus its aligned logical end."""
    offset = start
    records: list[dict[str, Any]] = []
    names: set[str] = set()
    while True:
        if offset + 110 > len(data):
            raise VerifyError("truncated newc header")
        header = data[offset : offset + 110]
        if header[:6] not in CPIO_MAGICS:
            raise VerifyError(f"invalid newc magic at offset {offset}")
        try:
            fields = [int(header[6 + index * 8 : 14 + index * 8], 16) for index in range(13)]
        except ValueError as exc:
            raise VerifyError(f"invalid newc hexadecimal header at offset {offset}") from exc
        ino, mode, uid, gid, nlink, mtime, size, devmajor, devminor, name_size = (
            fields[0],
            fields[1],
            fields[2],
            fields[3],
            fields[4],
            fields[5],
            fields[6],
            fields[7],
            fields[8],
            fields[11],
        )
        if name_size < 1:
            raise VerifyError(f"invalid newc name size at offset {offset}")
        name_start = offset + 110
        name_end = name_start + name_size
        if name_end > len(data) or data[name_end - 1] != 0:
            raise VerifyError(f"unterminated newc member name at offset {offset}")
        try:
            name = data[name_start : name_end - 1].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise VerifyError("non-UTF-8 newc member name") from exc
        data_start = align(name_end, 4)
        data_end = data_start + size
        next_offset = align(data_end, 4)
        if next_offset > len(data):
            raise VerifyError(f"truncated newc member {name!r}")
        payload = data[data_start:data_end]
        if name != "TRAILER!!!":
            safe_archive_path(name)
            if name in names:
                raise VerifyError(f"duplicate newc member: {name}")
            names.add(name)
            records.append(
                {
                    "path": name,
                    "ino": ino,
                    "mode": mode,
                    "uid": uid,
                    "gid": gid,
                    "nlink": nlink,
                    "devmajor": devmajor,
                    "devminor": devminor,
                    "mtime": mtime,
                    "data": payload,
                }
            )
        offset = next_offset
        if name == "TRAILER!!!":
            if size != 0:
                raise VerifyError("newc TRAILER!!! has a payload")
            return records, offset


def locate_base_boundary(data: bytes) -> tuple[list[dict[str, Any]], int]:
    """Locate the zstd frame only through the first parsed TRAILER and NUL pad."""
    records, trailer_end = parse_newc(data)
    boundary = trailer_end
    while boundary < len(data) and data[boundary] == 0:
        boundary += 1
    if data[boundary : boundary + len(ZSTD_MAGIC)] != ZSTD_MAGIC:
        raise VerifyError(
            "base must be uncompressed newc + NUL padding + one zstd main archive"
        )
    if boundary % 4:
        raise VerifyError("zstd boundary is not 4-byte aligned")
    return records, boundary


def decompress_zstd(data: bytes) -> bytes:
    zstd = shutil.which("zstd")
    if not zstd:
        raise VerifyError("zstd command is required")
    result = subprocess.run(
        [zstd, "-q", "-d", "-c"],
        input=data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        raise VerifyError("zstd main archive is invalid: " + result.stderr.decode(errors="replace"))
    return result.stdout


def validate_main_archive(suffix: bytes) -> list[dict[str, Any]]:
    if not suffix.startswith(ZSTD_MAGIC):
        raise VerifyError("main archive does not start with zstd magic")
    plain = decompress_zstd(suffix)
    records, end = parse_newc(plain)
    if any(plain[end:]):
        raise VerifyError("zstd main contains data after its newc TRAILER")
    return records


def native_template_command_paths() -> frozenset[str]:
    """Return absolute external-command paths embedded in the E3 templates."""
    pattern = rb"(?<![A-Za-z0-9_./-])/(?:bin|usr/bin|usr/sbin)/[A-Za-z0-9_.+-]+"
    paths: set[str] = set()
    for template in (NATIVE_HOOK_TEMPLATE, NATIVE_LAUNCHER_TEMPLATE):
        paths.update(match.decode("ascii") for match in re.findall(pattern, template))
    return frozenset(paths)


def _resolve_archive_path(
    absolute_path: str,
    by_path: dict[str, tuple[dict[str, Any], int]],
) -> tuple[dict[str, Any], int]:
    """Resolve one absolute path against newc records without host filesystem I/O."""
    pending = absolute_path.lstrip("/").split("/")
    resolved: list[str] = []
    symlink_hops = 0
    while pending:
        part = pending.pop(0)
        if part in {"", "."}:
            continue
        if part == "..":
            if not resolved:
                raise VerifyError(f"path escapes archive root: {absolute_path}")
            resolved.pop()
            continue
        candidate = "/".join([*resolved, part])
        indexed = by_path.get(candidate)
        if indexed is None:
            raise VerifyError(f"missing archive member {candidate}")
        record, archive_index = indexed
        file_type = record["mode"] & 0o170000
        if file_type == 0o120000:
            symlink_hops += 1
            if symlink_hops > 32:
                raise VerifyError(f"symlink loop while resolving {absolute_path}")
            try:
                target = record["data"].decode("utf-8")
            except UnicodeDecodeError as exc:
                raise VerifyError(f"non-UTF-8 symlink target: {candidate}") from exc
            if not target or "\x00" in target:
                raise VerifyError(f"invalid symlink target: {candidate}")
            if target.startswith("/"):
                resolved = []
            pending = target.lstrip("/").split("/") + pending
            continue
        resolved.append(part)
        if pending and file_type != 0o040000:
            raise VerifyError(f"non-directory archive path component: {candidate}")
    return record, archive_index


def validate_native_base_prerequisites(
    archives: tuple[list[dict[str, Any]], list[dict[str, Any]]],
) -> None:
    """Fail closed unless every E3 template utility is executable in the base."""
    extracted = native_template_command_paths()
    if extracted != NATIVE_BASE_REQUIRED_COMMAND_PATHS:
        missing = sorted(NATIVE_BASE_REQUIRED_COMMAND_PATHS - extracted)
        unexpected = sorted(extracted - NATIVE_BASE_REQUIRED_COMMAND_PATHS)
        raise VerifyError(
            "E3 native external command inventory mismatch: "
            f"missing={missing}, unexpected={unexpected}"
        )

    by_path: dict[str, tuple[dict[str, Any], int]] = {}
    for archive_index, records in enumerate(archives):
        for record in records:
            by_path[record["path"]] = (record, archive_index)

    failures: list[str] = []
    for path in sorted(NATIVE_BASE_REQUIRED_COMMAND_PATHS):
        try:
            record, archive_index = _resolve_archive_path(path, by_path)
        except VerifyError as exc:
            failures.append(f"{path} ({exc})")
            continue
        if record["mode"] & 0o170000 != 0o100000:
            failures.append(f"{path} (resolved member is not a regular file)")
            continue
        if not record["mode"] & 0o111:
            failures.append(f"{path} (resolved member is not executable)")
            continue
        if not record["data"]:
            hardlink_has_data = record["nlink"] > 1 and any(
                candidate["ino"] == record["ino"]
                and candidate["devmajor"] == record["devmajor"]
                and candidate["devminor"] == record["devminor"]
                and bool(candidate["data"])
                for candidate in archives[archive_index]
            )
            if not hardlink_has_data:
                failures.append(f"{path} (executable has no payload or backed hardlink)")
    if failures:
        raise VerifyError("E3 native base prerequisites failed: " + "; ".join(failures))


def validate_base_contract(
    data: bytes, *, require_native_prerequisites: bool = False
) -> tuple[int, list[dict[str, Any]]]:
    early_records, boundary = locate_base_boundary(data)
    main_records = validate_main_archive(data[boundary:])
    all_paths = {record["path"] for record in early_records + main_records}
    collisions = sorted(set(ALL_FILE_MODES) & all_paths)
    if collisions:
        raise VerifyError("base collides with overlay file paths: " + ", ".join(collisions))
    order = next(
        (record["data"] for record in main_records if record["path"] == "scripts/init-premount/ORDER"),
        None,
    )
    if order is None or ORDER_PARAM_LINE not in order.splitlines():
        raise VerifyError("base init-premount ORDER lacks the exact param.conf source line")
    if require_native_prerequisites:
        validate_native_base_prerequisites((early_records, main_records))
    return boundary, main_records


def parse_identity_text(text: str, *, embedded: bool = False) -> dict[str, str]:
    values: dict[str, str] = {}
    exported: set[str] = set()
    for number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
            if "=" not in line:
                if not embedded or line not in values or line in exported:
                    raise VerifyError(f"invalid identity export on line {number}")
                exported.add(line)
                continue
        if "=" not in line:
            raise VerifyError(f"identity line {number} is not KEY=VALUE")
        key, raw_value = line.split("=", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if key not in IDENTITY_KEYS:
            raise VerifyError(f"identity key is not allowlisted: {key}")
        if key in values:
            raise VerifyError(f"duplicate identity key: {key}")
        if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] and raw_value[0] in "'\"":
            value = raw_value[1:-1]
        else:
            value = raw_value
        if any(ord(char) < 0x20 or ord(char) > 0x7E for char in value):
            raise VerifyError(f"identity value for {key} is not printable ASCII")
        if any(token in value for token in ("$", "`", "\\", "__HOSTNAME__")):
            raise VerifyError(f"dynamic or shell-active identity value for {key} is forbidden")
        if not re.fullmatch(r"[A-Za-z0-9 ._:,+/@-]{0,127}", value):
            raise VerifyError(f"unsafe identity value for {key}")
        values[key] = value
    missing = sorted(REQUIRED_IDENTITY_KEYS - values.keys())
    if missing:
        raise VerifyError("identity is missing required keys: " + ", ".join(missing))
    for key in (
        "HIDLOOM_USB_MANUFACTURER",
        "HIDLOOM_USB_PRODUCT_NAME",
        "HIDLOOM_USB_SERIAL",
    ):
        if not values[key]:
            raise VerifyError(f"identity value for {key} must not be empty")
    for key in ("HIDLOOM_USB_VENDOR_ID", "HIDLOOM_USB_PRODUCT_ID"):
        if not re.fullmatch(r"0x[0-9A-Fa-f]{4}", values[key]):
            raise VerifyError(f"{key} must be 0x followed by four hex digits")
        values[key] = values[key].lower()
    for key in BOOL_KEYS:
        normalized = values[key].lower()
        if normalized in {"1", "true", "yes", "on", "enabled"}:
            values[key] = "1"
        elif normalized in {"0", "false", "no", "off", "disabled"}:
            values[key] = "0"
        else:
            raise VerifyError(f"{key} must be a boolean")
    if embedded and exported != set(values):
        raise VerifyError("embedded identity does not export every assignment exactly once")
    return {key: values[key] for key in sorted(values)}


def read_identity(path: Path) -> dict[str, str]:
    return parse_identity_text(path.read_text(encoding="utf-8"))


def identity_env_bytes(identity: dict[str, str]) -> bytes:
    lines = ["# Generated by rpi_os_early_initramfs.py; do not edit."]
    for key in sorted(identity):
        value = identity[key]
        lines.append(f"{key}='{value}'")
        lines.append(f"export {key}")
    return ("\n".join(lines) + "\n").encode()


def module_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    if path.name.endswith(".xz"):
        try:
            data = lzma.decompress(data)
        except lzma.LZMAError as exc:
            raise VerifyError(f"cannot decompress module {path.name}") from exc
    if not data.startswith(b"\x7fELF"):
        raise VerifyError(f"kernel module is not ELF: {path.name}")
    return data


def module_field(data: bytes, field: str) -> str:
    modinfo = shutil.which("modinfo")
    if not modinfo:
        raise VerifyError("modinfo command is required")
    with tempfile.NamedTemporaryFile(suffix=".ko") as module:
        module.write(data)
        module.flush()
        result = subprocess.run(
            [modinfo, "-F", field, module.name],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    if result.returncode:
        raise VerifyError(f"modinfo {field} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def verify_aarch64_elf(data: bytes, label: str) -> None:
    if len(data) < 20 or data[:4] != b"\x7fELF" or data[4] != 2 or data[5] != 1:
        raise VerifyError(f"{label} must be 64-bit little-endian ELF")
    if struct.unpack_from("<H", data, 18)[0] != 183:
        raise VerifyError(f"{label} must target ARM64/AArch64")


def verify_modules(
    libcomposite: bytes,
    usb_f_hid: bytes,
    kernel: str,
    raspberrypi_gpiomem: bytes | None = None,
) -> dict[str, Any]:
    details: dict[str, Any] = {}
    module_inputs = [
        ("libcomposite", libcomposite, []),
        ("usb_f_hid", usb_f_hid, ["libcomposite"]),
    ]
    if raspberrypi_gpiomem is not None:
        module_inputs.append(("raspberrypi_gpiomem", raspberrypi_gpiomem, []))
    for name, data, expected in module_inputs:
        verify_aarch64_elf(data, name)
        vermagic = module_field(data, "vermagic")
        if not vermagic or vermagic.split()[0] != kernel:
            raise VerifyError(f"{name} vermagic does not match exact kernel {kernel}: {vermagic}")
        dependencies = [item for item in module_field(data, "depends").split(",") if item]
        if dependencies != expected:
            raise VerifyError(f"{name} dependency contract mismatch: {dependencies!r}")
        details[name] = {
            "architecture": "aarch64",
            "vermagic": vermagic,
            "depends": dependencies,
            "sha256": sha256_bytes(data),
        }
    return details


def verify_descriptors(helper: bytes) -> dict[str, Any]:
    records: dict[str, Any] = {}
    for name, descriptor in sorted(REPORT_DESCRIPTORS.items()):
        count = helper.count(descriptor)
        if count != 1:
            raise VerifyError(f"helper must contain exact {name} descriptor once, found {count}")
        records[name] = {"size": len(descriptor), "sha256": sha256_bytes(descriptor)}
    canonical = json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    return {"contract_sha256": sha256_bytes(canonical), "reports": records}


def verify_arm64_static_elf(data: bytes, label: str = "gadget helper") -> None:
    verify_aarch64_elf(data, label)
    if len(data) < 64:
        raise VerifyError(f"{label} has a truncated ELF header")
    program_offset = struct.unpack_from("<Q", data, 32)[0]
    entry_size = struct.unpack_from("<H", data, 54)[0]
    entry_count = struct.unpack_from("<H", data, 56)[0]
    if entry_size < 56 or not entry_count or program_offset + entry_size * entry_count > len(data):
        raise VerifyError(f"{label} has invalid program headers")
    types = [
        struct.unpack_from("<I", data, program_offset + index * entry_size)[0]
        for index in range(entry_count)
    ]
    if 3 in types:
        raise VerifyError(f"{label} has PT_INTERP and is dynamically linked")
    if 1 not in types:
        raise VerifyError(f"{label} has no PT_LOAD segment")


def json_file_bytes(path: Path, label: str) -> bytes:
    data = path.read_bytes()
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerifyError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise VerifyError(f"{label} JSON root must be an object")
    return data


def verify_early_matrix_config(data: bytes) -> None:
    value = json.loads(data)
    ipc = value.get("ipc")
    if not isinstance(ipc, dict):
        raise VerifyError("matrixd config lacks its ipc object")
    if ipc.get("socket_path") != "/dev/hidloom-early/matrix-events.sock":
        raise VerifyError("matrixd config must use the pinned early matrix socket")
    if str(ipc.get("tap_socket_path", "")).strip().lower() not in {"", "none", "disabled"}:
        raise VerifyError("matrixd early tap socket must be disabled")
    matrix = value.get("matrix")
    if not isinstance(matrix, dict) or matrix.get("gpio_enabled") is not True:
        raise VerifyError("matrixd early config must explicitly enable GPIO")


PARAM_CONF = b"""# HIDloom E1/E3 is invoked through initramfs-tools ORDER files.\nif [ \"${HIDLOOM_EARLY_E1_PARAM_RAN:-0}\" != 1 ]; then\n    HIDLOOM_EARLY_E1_PARAM_RAN=1\n    export HIDLOOM_EARLY_E1_PARAM_RAN\n    /scripts/init-premount/hidloom-early-gadget \"$@\" || true\nfi\nif [ \"${HIDLOOM_EARLY_E3_BOTTOM_RAN:-0}\" != 1 ] \\\n        && [ -x /scripts/init-bottom/hidloom-early-input ] \\\n        && [ -n \"${rootmnt:-}\" ] && [ -L /dev ]; then\n    HIDLOOM_EARLY_E3_BOTTOM_RAN=1\n    export HIDLOOM_EARLY_E3_BOTTOM_RAN\n    /scripts/init-bottom/hidloom-early-input \"$@\" || true\nfi\n"""

HOOK_TEMPLATE = b"""#!/bin/sh
# E1 is deliberately fail-open: every failure returns to normal initramfs.
set +e
case " $(cat /proc/cmdline 2>/dev/null) " in
    *" hidloom.early=e1 "*) ;;
    *) exit 0 ;;
esac
run=/run/hidloom-early
marker=$run/e1-gadget.state
mkdir -p "$run" || exit 0
[ -e "$marker" ] && exit 0
/usr/bin/cp /conf/hidloom-early-contract.json "$run/contract.json" >/dev/null 2>&1 || true
printf '%s\n' starting >"$marker"
actual_kernel=$(/usr/bin/uname -r 2>/dev/null)
if [ "$actual_kernel" != "@KERNEL_RELEASE@" ]; then
    printf 'kernel-mismatch:%s\n' "$actual_kernel" >"$marker"
    exit 0
fi
load_exact_module() {
    module_name=$1
    module_path=$2
    [ -d "/sys/module/$module_name" ] && return 0
    /usr/sbin/insmod "$module_path" >/dev/null 2>&1
    [ -d "/sys/module/$module_name" ]
}
load_exact_module libcomposite /usr/lib/hidloom/early/modules/libcomposite.ko || { printf '%s\n' libcomposite-failed >"$marker"; exit 0; }
load_exact_module usb_f_hid /usr/lib/hidloom/early/modules/usb_f_hid.ko || { printf '%s\n' usb-f-hid-failed >"$marker"; exit 0; }
if [ -f /usr/lib/hidloom/early/modules/raspberrypi-gpiomem.ko ]; then
    if load_exact_module raspberrypi_gpiomem /usr/lib/hidloom/early/modules/raspberrypi-gpiomem.ko; then
        printf '%s\n' ready >"$run/e3-gpiomem.state"
    else
        printf '%s\n' failed >"$run/e3-gpiomem.state"
    fi
fi
mkdir -p /sys/kernel/config
[ -d /sys/kernel/config/usb_gadget ] || /usr/bin/mount -t configfs configfs /sys/kernel/config >/dev/null 2>&1
. /conf/hidloom-early-usb.env || { printf '%s\n' identity-failed >"$marker"; exit 0; }
/usr/bin/timeout -k 1 4 /usr/lib/hidloom/early/hidloom-usb-gadget-fast >/dev/null 2>&1
rc=$?
if [ "$rc" -eq 0 ]; then
    /usr/bin/timeout -k 1 1 /bin/sh -c "printf '\\001\\000\\000\\000\\000\\000\\000\\000\\000' > /dev/hidg0" >/dev/null 2>&1 || true
    /usr/bin/timeout -k 1 1 /bin/sh -c "printf '\\000\\000\\000\\000\\000\\000\\000\\000' > /dev/hidg2" >/dev/null 2>&1 || true
    printf '%s\n' ready >"$marker"
    printf '%s\n' ready >"$run/e1-gadget.ready"
    ready_uptime=$(/usr/bin/cut -d ' ' -f 1 /proc/uptime 2>/dev/null)
    [ -n "$ready_uptime" ] || ready_uptime=0
    printf '{"schema":"hidloom.early-gadget-bound.v1","state":"bound","kernel_release":"@KERNEL_RELEASE@","runtime_contract_sha256":"@CONTRACT_SHA256@","ready_uptime_seconds":%s}\n' "$ready_uptime" >"$run/gadget-bound.json"
else
    printf 'helper-failed:%s\n' "$rc" >"$marker"
fi
exit 0
"""


NATIVE_HOOK_TEMPLATE = b"""#!/bin/sh
# Stage the pinned E3 runtime only after initramfs-tools has mounted the real
# root and moved /dev.  The daemons are chrooted into the real root and use a
# /dev-backed live directory, so pathname sockets survive the later /run move.
set +e
case " $(/bin/cat /proc/cmdline 2>/dev/null) " in
    *" hidloom.early=e1 "*) ;;
    *) exit 0 ;;
esac
run=/run/hidloom-early
state=$run/e3-input.state
root=${rootmnt:-}
[ -n "$root" ] && [ -d "$root/dev" ] || exit 0
[ -e "$state" ] && exit 0
printf '%s\n' staging-after-dev-move >"$state"
if [ ! -e "$run/e1-gadget.ready" ]; then
    printf '%s\n' gadget-not-ready >"$state"
    exit 0
fi
if [ ! -e /dev/gpiomem ]; then
    printf '%s\n' gpiomem-not-ready >"$state"
    exit 0
fi
live=$root/dev/hidloom-early
runtime=$live/runtime
leader_alive() {
    kill -0 "$launcher" >/dev/null 2>&1
}
group_alive() {
    kill -0 -"$launcher" >/dev/null 2>&1
}
launcher_or_group_alive() {
    leader_alive || group_alive
}
remove_early_markers() {
    /usr/bin/rm -f "$run/gadget-bound.json" "$run/e1-gadget.ready"
    printf '%s\n' cleanup-unbound >"$run/e1-gadget.state" 2>/dev/null || true
}
outer_release_endpoints() {
    main_rc=1
    us_sub_rc=1
    /usr/bin/timeout -k 1 1 /bin/sh -c \
        'printf "\\001\\000\\000\\000\\000\\000\\000\\000\\000" >"$1"' \
        hidloom-release "$root/dev/hidg0" >/dev/null 2>&1 && main_rc=0
    /usr/bin/timeout -k 1 1 /bin/sh -c \
        'printf "\\000\\000\\000\\000\\000\\000\\000\\000" >"$1"' \
        hidloom-release "$root/dev/hidg2" >/dev/null 2>&1 && us_sub_rc=0
    [ "$main_rc" -eq 0 ] && [ "$us_sub_rc" -eq 0 ]
}
outer_unbind() {
    udc=/sys/kernel/config/usb_gadget/cqa02303v5/UDC
    [ -f "$udc" ] && [ ! -L "$udc" ] || return 1
    printf '\n' >"$udc" 2>/dev/null || return 1
    current=$(/bin/cat "$udc" 2>/dev/null) || return 1
    [ -z "$current" ] || return 1
    remove_early_markers
    : >"$live/gadget-fallback-unbound"
    return 0
}
outer_safe_cleanup() {
    if [ -f "$live/gadget-fallback-unbound" ]; then
        remove_early_markers
        cleanup_result=unbound
    elif [ "$(/usr/bin/sed -n '1p' "$live/cleanup.state" 2>/dev/null)" = released ]; then
        cleanup_result=released
    elif outer_release_endpoints; then
        cleanup_result=released
    elif outer_unbind; then
        cleanup_result=unbound
    else
        cleanup_result=unsafe-release-and-unbind-failed
    fi
    printf '%s\n' "$cleanup_result" >"$live/outer-cleanup.state"
    [ "$cleanup_result" != unsafe-release-and-unbind-failed ]
}
/usr/bin/mkdir -p "$runtime" || { printf '%s\n' live-dir-failed >"$state"; exit 0; }
for name in hidloom-hidd hidloom-outputd hidloom-logicd-core matrixd \
        hidloom-early-input-launch keymap.json keycodes.json config.json matrixd.json; do
    /usr/bin/cp "/usr/lib/hidloom/early/$name" "$runtime/$name" >/dev/null 2>&1 || {
        printf 'copy-failed:%s\n' "$name" >"$state"
        exit 0
    }
done
/usr/bin/chmod 0700 "$runtime"/hidloom-hidd "$runtime"/hidloom-outputd \
    "$runtime"/hidloom-logicd-core "$runtime"/matrixd \
    "$runtime"/hidloom-early-input-launch >/dev/null 2>&1 || {
        printf '%s\n' chmod-failed >"$state"
        exit 0
    }
/usr/bin/setsid /usr/sbin/chroot "$root" /bin/sh \
    /dev/hidloom-early/runtime/hidloom-early-input-launch &
launcher=$!
group_ready=0
count=0
while [ "$count" -lt 100 ]; do
    leader_alive || break
    if group_alive && leader_alive; then
        group_ready=1
        break
    fi
    /usr/bin/sleep 0.01
    count=$((count + 1))
done
count=0
if [ "$group_ready" -eq 1 ]; then
    while [ "$count" -lt 300 ]; do
        if [ -e "$live/chain-staged" ]; then
            printf '%s\n' chain-staged-before-run-move >"$state"
            exit 0
        fi
        group_alive || break
        /usr/bin/sleep 0.01
        count=$((count + 1))
    done
fi
kill "$launcher" >/dev/null 2>&1 || true
count=0
while launcher_or_group_alive && [ "$count" -lt 100 ]; do
    /usr/bin/sleep 0.02
    count=$((count + 1))
done
if launcher_or_group_alive; then
    # A hung launcher cannot prove terminal reports.  Disconnect the host
    # before killing the isolated process group so no late nonzero can escape.
    outer_unbind || true
    kill -9 "$launcher" >/dev/null 2>&1 || true
    kill -9 -"$launcher" >/dev/null 2>&1 || true
    count=0
    while launcher_or_group_alive && [ "$count" -lt 50 ]; do
        /usr/bin/sleep 0.02
        count=$((count + 1))
    done
fi
/usr/bin/rm -f "$live/chain-ready"
if launcher_or_group_alive; then
    # A producer survived SIGKILL (for example uninterruptible I/O).  A direct
    # zero is not terminal; only a verified host disconnect is safe.
    if outer_unbind; then
        cleanup_result=unbound
    else
        cleanup_result=unsafe-live-launcher-or-group-and-unbind-failed
    fi
    printf '%s\n' "$cleanup_result" >"$live/outer-cleanup.state"
else
    wait "$launcher" >/dev/null 2>&1 || true
    outer_safe_cleanup
fi
cleanup_published=0
cleanup_tmp=$live/.cleanup.state.outer.tmp.$$
if printf '%s\n' "$cleanup_result" >"$cleanup_tmp" \
        && /usr/bin/chmod 0600 "$cleanup_tmp" \
        && /usr/bin/mv "$cleanup_tmp" "$live/cleanup.state"; then
    cleanup_published=1
fi
case "$cleanup_result:$cleanup_published" in
    released:1|unbound:1) /usr/bin/rm -f "$live/chain-staged" ;;
    *) : >"$live/chain-staged" ;;
esac
printf 'launcher-failed:%s\n' "$cleanup_result" >"$state"
exit 0
"""


NATIVE_LAUNCHER_TEMPLATE = b"""#!/bin/sh
set +e
live=${HIDLOOM_EARLY_LIVE:-/dev/hidloom-early}
official=${HIDLOOM_EARLY_RUN:-/run/hidloom-early}
hidg0=${HIDLOOM_EARLY_HIDG0:-/dev/hidg0}
hidg2=${HIDLOOM_EARLY_HIDG2:-/dev/hidg2}
gadget=${HIDLOOM_EARLY_GADGET_PATH:-/sys/kernel/config/usb_gadget/cqa02303v5}
runtime=$live/runtime
umask 077
cleanup_in_progress=0

alive() {
    eval "candidate=\\${$1_pid:-}"
    [ -n "$candidate" ] && kill -0 "$candidate" >/dev/null 2>&1
}
stop_one() {
    label=$1
    eval "candidate=\\${${label}_pid:-}"
    [ -n "$candidate" ] || return 0
    kill "$candidate" >/dev/null 2>&1 || true
    count=0
    while kill -0 "$candidate" >/dev/null 2>&1 && [ "$count" -lt 50 ]; do
        /usr/bin/sleep 0.02
        count=$((count + 1))
    done
    if kill -0 "$candidate" >/dev/null 2>&1; then
        kill -9 "$candidate" >/dev/null 2>&1 || true
    fi
    wait "$candidate" >/dev/null 2>&1 || true
}
stop_chain() {
    stop_one matrixd
    stop_one logicd_core
    stop_one outputd
    stop_one hidd
}
remove_partial_evidence() {
    # Keep chain-staged visible until cleanup.state is terminal.  systemd uses
    # it as a fail-closed transition marker after the init-bottom hook returns.
    /usr/bin/rm -f "$live/chain-ready"
    /usr/bin/rm -f "$official/e3-input.ready" "$official/pids/hidd.pid" \
        "$official/pids/outputd.pid" "$official/pids/logicd-core.pid" \
        "$official/pids/matrixd.pid" "$official"/.e3-input.ready.tmp.*
}
release_endpoints() {
    main_rc=1
    us_sub_rc=1
    /usr/bin/timeout -k 1 1 /bin/sh -c \
        'printf "\\001\\000\\000\\000\\000\\000\\000\\000\\000" >"$1"' \
        hidloom-release "$hidg0" >/dev/null 2>&1 && main_rc=0
    /usr/bin/timeout -k 1 1 /bin/sh -c \
        'printf "\\000\\000\\000\\000\\000\\000\\000\\000" >"$1"' \
        hidloom-release "$hidg2" >/dev/null 2>&1 && us_sub_rc=0
    printf 'main_rc=%s us_sub_rc=%s\n' "$main_rc" "$us_sub_rc" \
        >"$live/cleanup-release.state"
    [ "$main_rc" -eq 0 ] && [ "$us_sub_rc" -eq 0 ]
}
unbind_for_fallback() {
    udc=$gadget/UDC
    [ -f "$udc" ] && [ ! -L "$udc" ] || return 1
    printf '\n' >"$udc" 2>/dev/null || return 1
    current=$(/bin/cat "$udc" 2>/dev/null) || return 1
    [ -z "$current" ] || return 1
    /usr/bin/rm -f "$official/gadget-bound.json" "$official/e1-gadget.ready"
    printf '%s\n' cleanup-unbound >"$official/e1-gadget.state" 2>/dev/null || true
    : >"$live/gadget-fallback-unbound"
    return 0
}
release_or_disconnect() {
    if release_endpoints; then
        cleanup_result=released
    elif unbind_for_fallback; then
        cleanup_result=unbound
    else
        cleanup_result=unsafe-release-and-unbind-failed
    fi
    cleanup_tmp=$live/.cleanup.state.tmp.$$
    printf '%s\n' "$cleanup_result" >"$cleanup_tmp" || return 1
    /usr/bin/chmod 0600 "$cleanup_tmp" || return 1
    /usr/bin/mv "$cleanup_tmp" "$live/cleanup.state" || return 1
    [ "$cleanup_result" != unsafe-release-and-unbind-failed ]
}
fail() {
    reason=$1
    [ "$cleanup_in_progress" -eq 0 ] || exit 0
    cleanup_in_progress=1
    trap - 0 HUP INT TERM
    remove_partial_evidence
    stop_chain
    cleanup_published=0
    release_or_disconnect && cleanup_published=1
    printf 'failed:%s:%s\n' "$reason" "$cleanup_result" >"$live/chain-state"
    [ "$cleanup_published" -eq 1 ] && /usr/bin/rm -f "$live/chain-staged"
    exit 0
}
trap 'fail unexpected-exit' 0
trap 'fail terminated' HUP INT TERM
wait_status() {
    label=$1
    path=$2
    needle=$3
    count=0
    while [ "$count" -lt 200 ]; do
        alive "$label" || return 1
        if [ -s "$path" ] && /usr/bin/grep -q "$needle" "$path" 2>/dev/null; then
            return 0
        fi
        /usr/bin/sleep 0.01
        count=$((count + 1))
    done
    return 1
}

export USBD_HID_REPORT_SOCKET=$live/usbd-hid-reports.sock
export USBD_HID_REPORT_PATH=$hidg0
export USBD_US_SUB_HID_REPORT_PATH=$hidg2
export HIDD_STATUS_PATH=$live/hidd-status.json
export HIDD_RAW_HID_BRIDGE_ENABLED=0
export HIDD_FRAME_LOG_PATH=$live/hidd-frames.ndjson
# E4 requires a fresh, observable zero write to both endpoints even when the
# last early report was already zero.  Keep normal-system dedup unchanged.
export USBD_KEYBOARD_REPORT_DEDUP=0
$runtime/hidloom-hidd >>"$live/hidd.log" 2>&1 &
hidd_pid=$!
printf '%s\n' "$hidd_pid" >"$live/hidd.pid"
wait_status hidd "$HIDD_STATUS_PATH" '"startup_release_reports":2' || fail hidd-ready

export OUTPUTD_REPORT_SOCKET=$live/output-reports.sock
export OUTPUTD_CTRL_SOCKET=$live/output-ctrl.sock
export OUTPUTD_USB_SOCKET=$USBD_HID_REPORT_SOCKET
export OUTPUTD_UIDD_SOCKET=$live/disabled-uidd.sock
export OUTPUTD_BT_SOCKET=$live/disabled-btd.sock
export OUTPUTD_STATUS_PATH=$live/outputd-status.json
export OUTPUTD_TARGET=usb
$runtime/hidloom-outputd >>"$live/outputd.log" 2>&1 &
outputd_pid=$!
printf '%s\n' "$outputd_pid" >"$live/outputd.pid"
wait_status outputd "$OUTPUTD_STATUS_PATH" '"target":"usb"' || fail outputd-ready

export HIDLOOM_REPO_ROOT=$runtime
export LOGICD_CORE_KEYMAP_PATH=$runtime/keymap.json
export LOGICD_CORE_DEFAULT_KEYMAP_PATH=$runtime/keymap.json
export LOGICD_CORE_KEYCODES_PATH=$runtime/keycodes.json
export LOGICD_CORE_DEFAULT_KEYCODES_PATH=$runtime/keycodes.json
export LOGICD_CORE_CONFIG_PATH=$runtime/config.json
export LOGICD_CORE_DEFAULT_CONFIG_PATH=$runtime/config.json
export LOGICD_CORE_MATRIX_SOCKET=$live/matrix-events.sock
export LOGICD_CORE_CTRL_SOCKET=$live/logicd-core-ctrl.sock
export LOGICD_CORE_DELEGATE_SOCKET=
export LOGICD_CORE_MATRIX_TAP_SOCKET=
export LOGICD_CORE_HID_REPORT_SOCKET=$OUTPUTD_REPORT_SOCKET
export LOGICD_CORE_STATUS_PATH=$live/logicd-core-status.json
export LOGICD_CORE_PREVIEW_LOG_PATH=$live/logicd-core-preview.ndjson
export LOGICD_CORE_OUTPUT_ENABLED=1
$runtime/hidloom-logicd-core --serve >>"$live/logicd-core.log" 2>&1 &
logicd_core_pid=$!
printf '%s\n' "$logicd_core_pid" >"$live/logicd-core.pid"
wait_status logicd_core "$LOGICD_CORE_STATUS_PATH" '"output_enabled":true' || fail logicd-core-ready
[ -S "$LOGICD_CORE_MATRIX_SOCKET" ] || fail logicd-core-matrix-socket

export MATRIXD_EVENT_LOG_PATH=$live/matrixd-events.ndjson
export MATRIXD_STATUS_PATH=$live/matrixd-status.json
$runtime/matrixd $runtime/matrixd.json >>"$live/matrixd.log" 2>&1 &
matrixd_pid=$!
printf '%s\n' "$matrixd_pid" >"$live/matrixd.pid"
wait_status matrixd "$MATRIXD_STATUS_PATH" '"connected":true' || fail matrixd-ready
printf '%s\n' ready >"$live/chain-state"
: >"$live/chain-staged"

count=0
run_move_polls=${HIDLOOM_EARLY_RUN_MOVE_POLLS:-500}
while [ "$count" -lt "$run_move_polls" ]; do
    if [ -r "$official/contract.json" ] && [ -r /proc/uptime ]; then
        break
    fi
    /usr/bin/sleep 0.01
    count=$((count + 1))
done
[ -r "$official/contract.json" ] && [ -r /proc/uptime ] || fail run-move-timeout
/usr/bin/mkdir -p "$official/pids" || fail pid-dir
for label in hidd outputd logicd-core matrixd; do
    case "$label" in
        hidd) candidate=$hidd_pid ;;
        outputd) candidate=$outputd_pid ;;
        logicd-core) candidate=$logicd_core_pid ;;
        matrixd) candidate=$matrixd_pid ;;
    esac
    starttime=$(/usr/bin/cut -d ' ' -f 22 "/proc/$candidate/stat" 2>/dev/null)
    [ -n "$starttime" ] || fail "$label-starttime"
    exe_identity=$(/usr/bin/stat -Lc '%d %i' "/proc/$candidate/exe" 2>/dev/null)
    [ -n "$exe_identity" ] || fail "$label-exe-identity"
    printf '%s %s %s\n' "$candidate" "$starttime" "$exe_identity" \
        >"$official/pids/$label.pid"
    /usr/bin/chmod 0600 "$official/pids/$label.pid" || fail "$label-pid-mode"
done
/usr/bin/ln -s /dev/hidloom-early "$official/live" 2>/dev/null || \
    [ -L "$official/live" ] || fail live-link
ready_uptime=$(/usr/bin/cut -d ' ' -f 1 /proc/uptime 2>/dev/null)
[ -n "$ready_uptime" ] || ready_uptime=0
ready_tmp=$official/.e3-input.ready.tmp.$$
printf '{"schema":"hidloom.early-input.v1","state":"ready","kernel_release":"@KERNEL_RELEASE@","runtime_contract_sha256":"@CONTRACT_SHA256@","ready_uptime_seconds":%s,"live_root":"/dev/hidloom-early","pids":{"hidd":%s,"outputd":%s,"logicd-core":%s,"matrixd":%s}}\n' \
    "$ready_uptime" "$hidd_pid" "$outputd_pid" "$logicd_core_pid" "$matrixd_pid" \
    >"$ready_tmp" || fail ready-write
/usr/bin/chmod 0600 "$ready_tmp" || fail ready-mode
printf '%s\n' ready >"$official/e3-input.state" || fail ready-state
: >"$live/chain-ready" || fail chain-ready
/usr/bin/mv "$ready_tmp" "$official/e3-input.ready" || fail ready-publish
trap - 0 HUP INT TERM
/usr/bin/rm -f "$live/chain-staged"
exit 0
"""


def hook_bytes(kernel_release: str, contract_sha256: str) -> bytes:
    return HOOK_TEMPLATE.replace(b"@KERNEL_RELEASE@", kernel_release.encode()).replace(
        b"@CONTRACT_SHA256@", contract_sha256.encode()
    )


def native_hook_bytes(kernel_release: str, contract_sha256: str) -> bytes:
    return NATIVE_HOOK_TEMPLATE.replace(
        b"@KERNEL_RELEASE@", kernel_release.encode()
    ).replace(b"@CONTRACT_SHA256@", contract_sha256.encode())


def native_launcher_bytes(kernel_release: str, contract_sha256: str) -> bytes:
    return NATIVE_LAUNCHER_TEMPLATE.replace(
        b"@KERNEL_RELEASE@", kernel_release.encode()
    ).replace(b"@CONTRACT_SHA256@", contract_sha256.encode())


def cpio_header(ino: int, mode: int, name_size: int, size: int) -> bytes:
    fields = (ino, mode, 0, 0, 2 if mode & 0o170000 == 0o040000 else 1, FIXED_MTIME,
              size, 0, 0, 0, 0, name_size, 0)
    return b"070701" + b"".join(f"{value:08X}".encode() for value in fields)


def make_newc(files: dict[str, tuple[int, bytes]]) -> bytes:
    entries = {path: (mode, b"") for path, mode in DIR_MODES.items()}
    entries.update(files)
    expected_paths = NATIVE_EXPECTED_PATHS if set(NATIVE_FILE_MODES) <= set(files) else BASE_EXPECTED_PATHS
    if set(entries) != expected_paths:
        raise VerifyError("internal overlay path inventory mismatch")
    output = bytearray()
    for ino, path in enumerate(sorted(entries), 1):
        mode, payload = entries[path]
        name = path.encode() + b"\0"
        output += cpio_header(ino, mode, len(name), len(payload))
        output += name
        output += b"\0" * (-len(output) % 4)
        output += payload
        output += b"\0" * (-len(output) % 4)
    trailer = b"TRAILER!!!\0"
    output += cpio_header(len(entries) + 1, 0, len(trailer), 0)
    output += trailer
    output += b"\0" * (-len(output) % 512)
    return bytes(output)


def overlay_records(
    data: bytes, file_modes: dict[str, int] | None = None
) -> dict[str, dict[str, Any]]:
    if file_modes is None:
        file_modes = BASE_FILE_MODES
    records, end = parse_newc(data)
    if end > len(data) or any(data[end:]):
        raise VerifyError("overlay contains non-NUL data after TRAILER")
    by_path = {record["path"]: record for record in records}
    if set(by_path) != set(file_modes) | set(DIR_MODES):
        raise VerifyError("overlay required/forbidden path inventory mismatch")
    for path, expected_mode in {**DIR_MODES, **file_modes}.items():
        record = by_path[path]
        if record["mode"] != expected_mode or record["uid"] or record["gid"]:
            raise VerifyError(f"overlay metadata mismatch: {path}")
        if record["mtime"] != FIXED_MTIME:
            raise VerifyError(f"overlay mtime is not deterministic: {path}")
    return by_path


def build(args: argparse.Namespace) -> dict[str, Any]:
    base_path = args.base.resolve()
    output_path = args.output.resolve()
    manifest_path = args.manifest.resolve()
    if output_path == base_path or manifest_path in {base_path, output_path}:
        raise VerifyError("base, output, and manifest paths must be distinct")
    if not re.fullmatch(r"[A-Za-z0-9.+_~-]+", args.kernel_release):
        raise VerifyError("unsafe kernel release")
    if not re.fullmatch(r"[A-Za-z0-9._+-]{7,80}", args.source):
        raise VerifyError("unsafe source identifier")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", args.profile_id):
        raise VerifyError("unsafe profile id")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", args.profile_sha256):
        raise VerifyError("profile sha256 must be exactly 64 hex digits")
    profile = {"id": args.profile_id, "sha256": args.profile_sha256.lower()}
    native_argument_names = (
        "hidd",
        "outputd",
        "logicd_core",
        "matrixd",
        "keymap",
        "keycodes",
        "logicd_config",
        "matrixd_config",
        "gpiomem",
    )
    supplied_native = {
        name: getattr(args, name, None) for name in native_argument_names
    }
    native_enabled = any(value is not None for value in supplied_native.values())
    if native_enabled and not all(value is not None for value in supplied_native.values()):
        missing = sorted(name.replace("_", "-") for name, value in supplied_native.items() if value is None)
        raise VerifyError("E3 native input arguments are all-or-none; missing: " + ", ".join(missing))

    base = base_path.read_bytes()
    boundary, _ = validate_base_contract(
        base, require_native_prerequisites=native_enabled
    )

    identity = read_identity(args.identity_env)
    helper = args.helper.read_bytes()
    verify_arm64_static_elf(helper)
    descriptors = verify_descriptors(helper)
    libcomposite = module_bytes(args.libcomposite)
    usb_f_hid = module_bytes(args.usb_f_hid)
    gpiomem = module_bytes(args.gpiomem) if native_enabled else None
    modules = verify_modules(libcomposite, usb_f_hid, args.kernel_release, gpiomem)
    identity_bytes = identity_env_bytes(identity)
    native_payloads: dict[str, bytes] = {}
    native_contract: dict[str, Any] | None = None
    if native_enabled:
        binary_arguments = {
            "hidd": ("hidloom-hidd", args.hidd),
            "outputd": ("hidloom-outputd", args.outputd),
            "logicd_core": ("hidloom-logicd-core", args.logicd_core),
            "matrixd": ("matrixd", args.matrixd),
        }
        binary_contract: dict[str, Any] = {}
        for key, (filename, path) in binary_arguments.items():
            data = path.read_bytes()
            verify_arm64_static_elf(data, filename)
            archive_path = f"usr/lib/hidloom/early/{filename}"
            native_payloads[archive_path] = data
            binary_contract[key] = {
                "path": f"/dev/hidloom-early/runtime/{filename}",
                "architecture": "aarch64",
                "static": True,
                "size": len(data),
                "sha256": sha256_bytes(data),
            }
        config_arguments = {
            "keymap": ("keymap.json", args.keymap),
            "keycodes": ("keycodes.json", args.keycodes),
            "logicd_config": ("config.json", args.logicd_config),
            "matrixd_config": ("matrixd.json", args.matrixd_config),
        }
        config_contract: dict[str, Any] = {}
        for key, (filename, path) in config_arguments.items():
            data = json_file_bytes(path, key.replace("_", " "))
            if key == "matrixd_config":
                verify_early_matrix_config(data)
            archive_path = f"usr/lib/hidloom/early/{filename}"
            native_payloads[archive_path] = data
            config_contract[key] = {
                "path": f"/dev/hidloom-early/runtime/{filename}",
                "size": len(data),
                "sha256": sha256_bytes(data),
            }
        native_contract = {
            "schema": NATIVE_INPUT_SCHEMA,
            "start_order": ["hidd", "outputd", "logicd_core", "matrixd"],
            "live_root": "/dev/hidloom-early",
            "runtime_evidence_root": "/run/hidloom-early",
            "binaries": binary_contract,
            "configs": config_contract,
            "gpiomem_module_sha256": modules["raspberrypi_gpiomem"]["sha256"],
            "startup_release": {
                "main_report_hex": "010000000000000000",
                "main_report_size": 9,
                "us_sub_report_hex": "0000000000000000",
                "us_sub_report_size": 8,
            },
            "handoff_release": {
                "keyboard_report_dedup": False,
                "required_endpoint_zero_writes": ["main", "us_sub"],
            },
        }
    contract_content = {
        "schema": "hidloom.rpi-os-early-runtime-contract.e1.v1",
        "source": args.source,
        "kernel_release": args.kernel_release,
        "profile": profile,
        "identity_sha256": sha256_bytes(identity_bytes),
        "helper_sha256": sha256_bytes(helper),
        "descriptor_contract_sha256": descriptors["contract_sha256"],
        "module_sha256": {
            name: details["sha256"] for name, details in sorted(modules.items())
        },
    }
    if native_contract is not None:
        contract_content["native_input"] = native_contract
    contract_bytes = (
        json.dumps(contract_content, indent=2, sort_keys=True) + "\n"
    ).encode()
    contract_sha256 = sha256_bytes(contract_bytes)
    files = {
        "conf/param.conf": (FILE_MODES["conf/param.conf"], PARAM_CONF),
        "conf/hidloom-early-usb.env": (
            FILE_MODES["conf/hidloom-early-usb.env"], identity_bytes
        ),
        "conf/hidloom-early-contract.json": (
            FILE_MODES["conf/hidloom-early-contract.json"], contract_bytes
        ),
        "scripts/init-premount/hidloom-early-gadget": (
            FILE_MODES["scripts/init-premount/hidloom-early-gadget"],
            hook_bytes(args.kernel_release, contract_sha256),
        ),
        "usr/lib/hidloom/early/hidloom-usb-gadget-fast": (
            FILE_MODES["usr/lib/hidloom/early/hidloom-usb-gadget-fast"], helper
        ),
        "usr/lib/hidloom/early/modules/libcomposite.ko": (
            FILE_MODES["usr/lib/hidloom/early/modules/libcomposite.ko"], libcomposite
        ),
        "usr/lib/hidloom/early/modules/usb_f_hid.ko": (
            FILE_MODES["usr/lib/hidloom/early/modules/usb_f_hid.ko"], usb_f_hid
        ),
    }
    if native_enabled:
        assert gpiomem is not None and native_contract is not None
        native_payloads.update(
            {
                "scripts/init-bottom/hidloom-early-input": native_hook_bytes(
                    args.kernel_release, contract_sha256
                ),
                "usr/lib/hidloom/early/hidloom-early-input-launch": native_launcher_bytes(
                    args.kernel_release, contract_sha256
                ),
                "usr/lib/hidloom/early/modules/raspberrypi-gpiomem.ko": gpiomem,
            }
        )
        for path, payload in native_payloads.items():
            files[path] = (NATIVE_FILE_MODES[path], payload)
    file_modes = ALL_FILE_MODES if native_enabled else BASE_FILE_MODES
    overlay = make_newc(files)
    overlay_records(overlay, file_modes)
    image = base[:boundary] + overlay + base[boundary:]
    file_manifest = [
        {
            "path": path,
            "mode": f"{mode & 0o7777:04o}",
            "size": len(payload),
            "sha256": sha256_bytes(payload),
        }
        for path, (mode, payload) in sorted(files.items())
    ]
    manifest = {
        "schema": SCHEMA,
        "kernel_release": args.kernel_release,
        "source": args.source,
        "base": {
            "name": base_path.name,
            "size": len(base),
            "sha256": sha256_bytes(base),
            "zstd_offset": boundary,
            "prefix": {"size": boundary, "sha256": sha256_bytes(base[:boundary])},
            "suffix": {"size": len(base) - boundary, "sha256": sha256_bytes(base[boundary:])},
        },
        "overlay": {
            "size": len(overlay),
            "sha256": sha256_bytes(overlay),
            "alignment": 512,
            "files": file_manifest,
        },
        "output": {
            "name": output_path.name,
            "size": len(image),
            "sha256": sha256_bytes(image),
            "zstd_offset": boundary + len(overlay),
        },
        "identity": identity,
        "profile": profile,
        "descriptors": descriptors,
        "modules": modules,
        "helper": {"architecture": "aarch64", "static": True, "sha256": sha256_bytes(helper)},
        "runtime_contract": {**contract_content, "sha256": contract_sha256},
    }
    if native_contract is not None:
        manifest["native_input"] = native_contract
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return verify_artifact(base_path, output_path, manifest_path, run_unmkinitramfs=False)


def verify_unmkinitramfs_overlay(
    root: Path,
    records: dict[str, dict[str, Any]],
    file_modes: dict[str, int],
) -> None:
    """Verify files extracted by both split-archive and legacy unmkinitramfs."""
    split_layout = all((root / name).is_dir() for name in ("early", "early2", "main"))
    overlay_root = root / "early2" if split_layout else root
    for path in file_modes:
        extracted = overlay_root / path
        if not extracted.is_file():
            raise VerifyError(f"unmkinitramfs output is missing {path}")
        if extracted.read_bytes() != records[path]["data"]:
            raise VerifyError(f"unmkinitramfs output content mismatch: {path}")


def verify_artifact(
    base_path: Path, image_path: Path, manifest_path: Path, *, run_unmkinitramfs: bool
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise VerifyError("unexpected manifest schema")
    if not re.fullmatch(r"[A-Za-z0-9._+-]{7,80}", manifest.get("source", "")):
        raise VerifyError("manifest source identifier is invalid")
    native_enabled = "native_input" in manifest
    file_modes = ALL_FILE_MODES if native_enabled else BASE_FILE_MODES
    base = base_path.read_bytes()
    image = image_path.read_bytes()
    boundary = manifest["base"]["zstd_offset"]
    overlay_size = manifest["overlay"]["size"]
    output_boundary = boundary + overlay_size
    if manifest["base"]["name"] != base_path.name:
        raise VerifyError("base filename does not match manifest")
    if sha256_bytes(base) != manifest["base"]["sha256"] or len(base) != manifest["base"]["size"]:
        raise VerifyError("base image hash/size does not match manifest")
    actual_boundary, _ = validate_base_contract(
        base, require_native_prerequisites=native_enabled
    )
    if actual_boundary != boundary:
        raise VerifyError("base zstd boundary does not match manifest")
    expected_prefix = {"size": boundary, "sha256": sha256_bytes(base[:boundary])}
    expected_suffix = {
        "size": len(base) - boundary,
        "sha256": sha256_bytes(base[boundary:]),
    }
    if manifest["base"]["prefix"] != expected_prefix:
        raise VerifyError("base prefix manifest fields mismatch")
    if manifest["base"]["suffix"] != expected_suffix:
        raise VerifyError("base suffix manifest fields mismatch")
    if manifest["overlay"].get("alignment") != 512 or overlay_size % 512:
        raise VerifyError("overlay is not declared and sized to 512-byte alignment")
    if manifest["output"].get("zstd_offset") != output_boundary:
        raise VerifyError("output zstd boundary field mismatch")
    if manifest["output"].get("name") != image_path.name:
        raise VerifyError("output filename does not match manifest")
    if sha256_bytes(image) != manifest["output"]["sha256"] or len(image) != manifest["output"]["size"]:
        raise VerifyError("output image hash/size does not match manifest")
    if image[:boundary] != base[:boundary]:
        raise VerifyError("base prefix bytes changed")
    if image[output_boundary:] != base[boundary:]:
        raise VerifyError("base zstd suffix bytes changed or data was appended")
    if image[output_boundary : output_boundary + 4] != ZSTD_MAGIC:
        raise VerifyError("output zstd boundary is invalid")
    overlay = image[boundary:output_boundary]
    if sha256_bytes(overlay) != manifest["overlay"]["sha256"]:
        raise VerifyError("overlay hash mismatch")
    records = overlay_records(overlay, file_modes)
    file_manifest_items = manifest["overlay"]["files"]
    file_manifest = {item["path"]: item for item in file_manifest_items}
    if len(file_manifest_items) != len(file_manifest) or set(file_manifest) != set(file_modes):
        raise VerifyError("manifest file inventory mismatch")
    for path, expected_mode in file_modes.items():
        record = records[path]
        item = file_manifest[path]
        if item["sha256"] != sha256_bytes(record["data"]) or item["size"] != len(record["data"]):
            raise VerifyError(f"embedded file hash/size mismatch: {path}")
        if item["mode"] != f"{expected_mode & 0o7777:04o}":
            raise VerifyError(f"manifest mode mismatch: {path}")
    if b"hidloom.early=e1" not in records["scripts/init-premount/hidloom-early-gadget"]["data"]:
        raise VerifyError("early hook is missing its command-line guard")
    hook = records["scripts/init-premount/hidloom-early-gadget"]["data"]
    if manifest["kernel_release"].encode() not in hook or b"/sys/module/$module_name" not in hook:
        raise VerifyError("early hook lacks kernel or idempotent module guard")
    if (
        b"contract.json" not in hook
        or b"e1-gadget.ready" not in hook
        or b"gadget-bound.json" not in hook
    ):
        raise VerifyError("early hook lacks runtime contract/ready evidence")

    identity = parse_identity_text(
        records["conf/hidloom-early-usb.env"]["data"].decode("utf-8"), embedded=True
    )
    if identity != manifest["identity"]:
        raise VerifyError("embedded identity does not match manifest identity")
    profile = manifest["profile"]
    if (
        not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", profile.get("id", ""))
        or not re.fullmatch(r"[0-9a-f]{64}", profile.get("sha256", ""))
    ):
        raise VerifyError("manifest profile contract is invalid")

    helper_data = records["usr/lib/hidloom/early/hidloom-usb-gadget-fast"]["data"]
    verify_arm64_static_elf(helper_data)
    expected_helper = {
        "architecture": "aarch64",
        "static": True,
        "sha256": sha256_bytes(helper_data),
    }
    if manifest["helper"] != expected_helper:
        raise VerifyError("helper manifest fields mismatch")
    descriptors = verify_descriptors(helper_data)
    if manifest["descriptors"] != descriptors:
        raise VerifyError("descriptor contract manifest fields mismatch")
    contract_data = records["conf/hidloom-early-contract.json"]["data"]
    runtime_contract = manifest["runtime_contract"]
    contract_sha256 = sha256_bytes(contract_data)
    if runtime_contract.get("sha256") != contract_sha256:
        raise VerifyError("runtime contract hash mismatch")
    gpiomem_data = (
        records["usr/lib/hidloom/early/modules/raspberrypi-gpiomem.ko"]["data"]
        if native_enabled
        else None
    )
    modules = verify_modules(
        records["usr/lib/hidloom/early/modules/libcomposite.ko"]["data"],
        records["usr/lib/hidloom/early/modules/usb_f_hid.ko"]["data"],
        manifest["kernel_release"],
        gpiomem_data,
    )
    if manifest["modules"] != modules:
        raise VerifyError("module manifest fields mismatch")

    native_contract: dict[str, Any] | None = None
    if native_enabled:
        binary_paths = {
            "hidd": "hidloom-hidd",
            "outputd": "hidloom-outputd",
            "logicd_core": "hidloom-logicd-core",
            "matrixd": "matrixd",
        }
        binary_contract: dict[str, Any] = {}
        for key, filename in binary_paths.items():
            data = records[f"usr/lib/hidloom/early/{filename}"]["data"]
            verify_arm64_static_elf(data, filename)
            binary_contract[key] = {
                "path": f"/dev/hidloom-early/runtime/{filename}",
                "architecture": "aarch64",
                "static": True,
                "size": len(data),
                "sha256": sha256_bytes(data),
            }
        config_paths = {
            "keymap": "keymap.json",
            "keycodes": "keycodes.json",
            "logicd_config": "config.json",
            "matrixd_config": "matrixd.json",
        }
        config_contract: dict[str, Any] = {}
        for key, filename in config_paths.items():
            data = records[f"usr/lib/hidloom/early/{filename}"]["data"]
            try:
                decoded = json.loads(data)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise VerifyError(f"embedded {key} is invalid JSON") from exc
            if not isinstance(decoded, dict):
                raise VerifyError(f"embedded {key} JSON root must be an object")
            if key == "matrixd_config":
                verify_early_matrix_config(data)
            config_contract[key] = {
                "path": f"/dev/hidloom-early/runtime/{filename}",
                "size": len(data),
                "sha256": sha256_bytes(data),
            }
        native_contract = {
            "schema": NATIVE_INPUT_SCHEMA,
            "start_order": ["hidd", "outputd", "logicd_core", "matrixd"],
            "live_root": "/dev/hidloom-early",
            "runtime_evidence_root": "/run/hidloom-early",
            "binaries": binary_contract,
            "configs": config_contract,
            "gpiomem_module_sha256": modules["raspberrypi_gpiomem"]["sha256"],
            "startup_release": {
                "main_report_hex": "010000000000000000",
                "main_report_size": 9,
                "us_sub_report_hex": "0000000000000000",
                "us_sub_report_size": 8,
            },
            "handoff_release": {
                "keyboard_report_dedup": False,
                "required_endpoint_zero_writes": ["main", "us_sub"],
            },
        }
        if manifest.get("native_input") != native_contract:
            raise VerifyError("native input manifest contract mismatch")
        bottom_hook = records["scripts/init-bottom/hidloom-early-input"]["data"]
        launcher = records[
            "usr/lib/hidloom/early/hidloom-early-input-launch"
        ]["data"]
        if bottom_hook != native_hook_bytes(manifest["kernel_release"], contract_sha256):
            raise VerifyError("native input init-bottom hook differs from its pinned template")
        if launcher != native_launcher_bytes(manifest["kernel_release"], contract_sha256):
            raise VerifyError("native input launcher differs from its pinned template")
        if b"/usr/sbin/chroot" not in bottom_hook or b"/dev/hidloom-early" not in launcher:
            raise VerifyError("native input hook lacks the root-transition contract")
    try:
        contract_content = json.loads(contract_data)
    except json.JSONDecodeError as exc:
        raise VerifyError("embedded runtime contract is invalid JSON") from exc
    expected_contract = {
        "schema": "hidloom.rpi-os-early-runtime-contract.e1.v1",
        "source": manifest["source"],
        "kernel_release": manifest["kernel_release"],
        "profile": profile,
        "identity_sha256": sha256_bytes(records["conf/hidloom-early-usb.env"]["data"]),
        "helper_sha256": expected_helper["sha256"],
        "descriptor_contract_sha256": descriptors["contract_sha256"],
        "module_sha256": {
            name: details["sha256"] for name, details in sorted(modules.items())
        },
    }
    if native_contract is not None:
        expected_contract["native_input"] = native_contract
    expected_manifest_contract = {**expected_contract, "sha256": contract_sha256}
    if contract_content != expected_contract or runtime_contract != expected_manifest_contract:
        raise VerifyError("runtime contract content does not match verified inputs")
    if runtime_contract["sha256"].encode() not in hook:
        raise VerifyError("early hook does not bind evidence to the runtime contract hash")
    if run_unmkinitramfs:
        command = shutil.which("unmkinitramfs")
        if not command:
            raise VerifyError("unmkinitramfs command is required for deep verify")
        with tempfile.TemporaryDirectory(prefix="hidloom-e1-unpack-") as directory:
            result = subprocess.run(
                [command, str(image_path), directory],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if result.returncode:
                raise VerifyError("unmkinitramfs rejected output: " + result.stderr.decode(errors="replace"))
            verify_unmkinitramfs_overlay(Path(directory), records, file_modes)
    return {
        "status": "pass",
        "schema": SCHEMA,
        "kernel_release": manifest["kernel_release"],
        "output": str(image_path),
        "sha256": manifest["output"]["sha256"],
        "size": manifest["output"]["size"],
        "overlay_size": overlay_size,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build", help="insert a deterministic E1 overlay")
    build_parser.add_argument("--base", "--base-initramfs", dest="base", type=Path, required=True)
    build_parser.add_argument("--output", "--output-initramfs", dest="output", type=Path, required=True)
    build_parser.add_argument("--manifest", type=Path, required=True)
    build_parser.add_argument("--kernel-release", required=True)
    build_parser.add_argument("--source", "--source-commit", dest="source", required=True)
    build_parser.add_argument("--profile-id", required=True)
    build_parser.add_argument(
        "--profile-sha256",
        required=True,
        help="SHA-256 of the installed /usr/share/hidloom/profiles/<id>/profile.json",
    )
    build_parser.add_argument("--helper", "--usb-gadget-helper", dest="helper", type=Path, required=True)
    build_parser.add_argument("--libcomposite", "--libcomposite-module", dest="libcomposite", type=Path, required=True)
    build_parser.add_argument("--usb-f-hid", "--usb-f-hid-module", dest="usb_f_hid", type=Path, required=True)
    build_parser.add_argument("--identity-env", type=Path, required=True)
    native = build_parser.add_argument_group(
        "optional E3 native input extension (all arguments are required together)"
    )
    native.add_argument("--hidd", type=Path)
    native.add_argument("--outputd", type=Path)
    native.add_argument("--logicd-core", dest="logicd_core", type=Path)
    native.add_argument("--matrixd", type=Path)
    native.add_argument("--keymap", type=Path)
    native.add_argument("--keycodes", type=Path)
    native.add_argument("--logicd-config", dest="logicd_config", type=Path)
    native.add_argument("--matrixd-config", dest="matrixd_config", type=Path)
    native.add_argument("--gpiomem", "--gpiomem-module", dest="gpiomem", type=Path)
    verify_parser = commands.add_parser("verify", help="deeply verify an E1 image")
    verify_parser.add_argument("--base", "--base-initramfs", dest="base", type=Path, required=True)
    verify_parser.add_argument("--image", "--output-initramfs", dest="image", type=Path, required=True)
    verify_parser.add_argument("--manifest", type=Path, required=True)
    verify_parser.add_argument("--skip-unmkinitramfs", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "build":
            result = build(args)
        else:
            result = verify_artifact(
                args.base.resolve(), args.image.resolve(), args.manifest.resolve(),
                run_unmkinitramfs=not args.skip_unmkinitramfs,
            )
    except (
        OSError,
        IndexError,
        KeyError,
        TypeError,
        UnicodeError,
        json.JSONDecodeError,
        VerifyError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
