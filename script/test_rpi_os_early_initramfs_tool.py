#!/usr/bin/env python3
"""Regression checks for the Raspberry Pi OS E1 initramfs builder/verifier."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "rpi_os_early_initramfs.py"
FAST_HELPER_SOURCE = (
    ROOT / "tools" / "hidloom_usb_gadget_fast" / "hidloom_usb_gadget_fast.c"
)
sys.path.insert(0, str(ROOT / "tools"))

import rpi_os_early_initramfs as early  # noqa: E402


KERNEL_RELEASE = "6.18.34+rpt-rpi-v8"
SOURCE_ID = "deadbeefcafebabe"
PROFILE_ID = "keyboard-ver1"
PROFILE_SHA256 = "0123456789abcdef" * 4
IDENTITY_TEXT = """\
HIDLOOM_USB_VENDOR_ID=0x1D6B
HIDLOOM_USB_PRODUCT_ID=0x0105
HIDLOOM_USB_MANUFACTURER=HIDloom Fixture
HIDLOOM_USB_PRODUCT_NAME=HIDloom E1 Keyboard
HIDLOOM_USB_SERIAL=vial:f64c2b3c
HIDLOOM_USB_SERIAL_SUFFIX=e1
HIDLOOM_USB_US_SUB_KEYBOARD=yes
HIDLOOM_WINDOWS_IME_CUSTOM_HID=no
"""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and completed.returncode:
        raise AssertionError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def require_commands() -> dict[str, str]:
    commands = {}
    for name in ("aarch64-linux-gnu-gcc", "modinfo", "unmkinitramfs", "zstd"):
        resolved = shutil.which(name)
        assert resolved, f"required test command is missing: {name}"
        commands[name] = resolved
    return commands


def cpio_newc(entries: dict[str, tuple[int, bytes]], *, alignment: int = 512) -> bytes:
    """Build a small independent newc fixture, including deliberately unsafe names."""
    output = bytearray()
    for inode, (name, (mode, payload)) in enumerate(sorted(entries.items()), 1):
        encoded_name = name.encode("utf-8") + b"\0"
        fields = (
            inode,
            mode,
            0,
            0,
            2 if mode & 0o170000 == 0o040000 else 1,
            0,
            len(payload),
            0,
            0,
            0,
            0,
            len(encoded_name),
            0,
        )
        output += b"070701" + b"".join(f"{value:08X}".encode() for value in fields)
        output += encoded_name
        output += b"\0" * (-len(output) % 4)
        output += payload
        output += b"\0" * (-len(output) % 4)

    trailer = b"TRAILER!!!\0"
    fields = (len(entries) + 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, len(trailer), 0)
    output += b"070701" + b"".join(f"{value:08X}".encode() for value in fields)
    output += trailer
    output += b"\0" * (-len(output) % alignment)
    return bytes(output)


def zstd_compress(commands: dict[str, str], payload: bytes) -> bytes:
    completed = subprocess.run(
        [commands["zstd"], "-q", "-1", "-c"],
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert completed.stdout.startswith(early.ZSTD_MAGIC)
    return completed.stdout


def base_bytes(
    commands: dict[str, str],
    *,
    early_entries: dict[str, tuple[int, bytes]] | None = None,
    main_extra: dict[str, tuple[int, bytes]] | None = None,
) -> bytes:
    early_archive = cpio_newc(
        early_entries
        if early_entries is not None
        else {"early-fixture": (0o100644, b"early archive remains byte-identical\n")}
    )
    main_entries = {
        "main-fixture": (0o100644, b"compressed main archive remains byte-identical\n"),
        "scripts": (0o040755, b""),
        "scripts/init-premount": (0o040755, b""),
        "scripts/init-premount/ORDER": (
            0o100644,
            b'/scripts/init-premount/plymouth "$@"\n'
            + early.ORDER_PARAM_LINE
            + b"\n",
        ),
    }
    if main_extra:
        main_entries.update(main_extra)
    return early_archive + zstd_compress(commands, cpio_newc(main_entries))


def c_descriptor(name: str) -> bytes:
    text = FAST_HELPER_SOURCE.read_text(encoding="utf-8")
    match = re.search(
        rf"static const uint8_t {re.escape(name)}\[\] = \{{(.*?)\}};", text, re.S
    )
    assert match, f"production descriptor is missing: {name}"
    values = re.findall(r"0x([0-9A-Fa-f]{2})", match.group(1))
    assert values, f"production descriptor is empty: {name}"
    return bytes(int(value, 16) for value in values)


def production_descriptors() -> dict[str, bytes]:
    return {
        "main": c_descriptor("HID_USB0_REPORT_DESC"),
        "raw": c_descriptor("HID_USB1_REPORT_DESC"),
        "us_sub": c_descriptor("HID_USB2_REPORT_DESC"),
        "windows_ime_custom": c_descriptor("HID_USB4_REPORT_DESC"),
    }


def c_bytes(payload: bytes) -> str:
    return ", ".join(f"0x{value:02x}" for value in payload)


def compile_helper(
    commands: dict[str, str],
    directory: Path,
    name: str,
    descriptors: dict[str, bytes],
    *,
    static: bool,
) -> Path:
    source = directory / f"{name}.c"
    output = directory / name
    source.write_text(
        "#include <stdint.h>\n"
        + "\n".join(
            f"static const uint8_t descriptor_{key}[] __attribute__((used)) = "
            f"{{ {c_bytes(payload)} }};"
            for key, payload in sorted(descriptors.items())
        )
        + "\nint main(void) {\n"
        + "    volatile unsigned int value = descriptor_main[0] + descriptor_raw[0] "
        "+ descriptor_us_sub[0];\n"
        + "    return value == 0xffffffffU;\n}\n",
        encoding="utf-8",
    )
    command = [commands["aarch64-linux-gnu-gcc"], "-std=c11", "-Os"]
    if static:
        command.append("-static")
    command += [str(source), "-o", str(output)]
    run(command)
    data = output.read_bytes()
    for descriptor in descriptors.values():
        assert data.count(descriptor) == 1
    return output


def compile_module(
    commands: dict[str, str],
    directory: Path,
    name: str,
    *,
    kernel_release: str,
    depends: str,
) -> Path:
    source = directory / f"{name}.c"
    output = directory / f"{name}.ko"
    source.write_text(
        "static const char fixture_vermagic[] __attribute__((section(\".modinfo\"), used)) = "
        f"\"vermagic={kernel_release} SMP preempt mod_unload modversions aarch64\";\n"
        "static const char fixture_depends[] __attribute__((section(\".modinfo\"), used)) = "
        f"\"depends={depends}\";\n"
        "int hidloom_fixture_module_symbol;\n",
        encoding="utf-8",
    )
    run(
        [
            commands["aarch64-linux-gnu-gcc"],
            "-c",
            "-O2",
            str(source),
            "-o",
            str(output),
        ]
    )
    return output


def module_field(commands: dict[str, str], module: Path, field: str) -> str:
    return run([commands["modinfo"], "-F", field, str(module)]).stdout.strip()


def build_command(
    *,
    base: Path,
    output: Path,
    manifest: Path,
    helper: Path,
    libcomposite: Path,
    usb_f_hid: Path,
    identity: Path,
) -> list[str]:
    return [
        sys.executable,
        str(TOOL_PATH),
        "build",
        "--base",
        str(base),
        "--output",
        str(output),
        "--manifest",
        str(manifest),
        "--kernel-release",
        KERNEL_RELEASE,
        "--source",
        SOURCE_ID,
        "--profile-id",
        PROFILE_ID,
        "--profile-sha256",
        PROFILE_SHA256,
        "--helper",
        str(helper),
        "--libcomposite",
        str(libcomposite),
        "--usb-f-hid",
        str(usb_f_hid),
        "--identity-env",
        str(identity),
    ]


def verify_command(base: Path, image: Path, manifest: Path, *, deep: bool = True) -> list[str]:
    command = [
        sys.executable,
        str(TOOL_PATH),
        "verify",
        "--base",
        str(base),
        "--image",
        str(image),
        "--manifest",
        str(manifest),
    ]
    if not deep:
        command.append("--skip-unmkinitramfs")
    return command


def expect_failure(command: list[str], phrase: str) -> None:
    completed = run(command, check=False)
    assert completed.returncode != 0, f"command unexpectedly passed: {' '.join(command)}"
    output = completed.stdout + completed.stderr
    assert phrase.lower() in output.lower(), (phrase, output)


def negative_build(
    directory: Path,
    label: str,
    *,
    base: Path,
    helper: Path,
    libcomposite: Path,
    usb_f_hid: Path,
    identity: Path,
    phrase: str,
) -> None:
    target = directory / label
    expect_failure(
        build_command(
            base=base,
            output=target / "initramfs-hidloom-e1",
            manifest=target / "early-image.json",
            helper=helper,
            libcomposite=libcomposite,
            usb_f_hid=usb_f_hid,
            identity=identity,
        ),
        phrase,
    )


def main() -> None:
    commands = require_commands()
    assert TOOL_PATH.is_file()
    descriptors = production_descriptors()
    assert early.REPORT_DESCRIPTORS == descriptors

    with tempfile.TemporaryDirectory(prefix="hidloom-e1-tool-test-") as temporary:
        fixture = Path(temporary)
        helper = compile_helper(commands, fixture, "helper-static", descriptors, static=True)
        early.verify_arm64_static_elf(helper.read_bytes())
        assert early.verify_descriptors(helper.read_bytes())["reports"]

        dynamic_helper = compile_helper(
            commands, fixture, "helper-dynamic", descriptors, static=False
        )
        wrong_arch_helper = fixture / "helper-wrong-arch"
        wrong_arch_data = bytearray(helper.read_bytes())
        struct.pack_into("<H", wrong_arch_data, 18, 62)
        wrong_arch_helper.write_bytes(wrong_arch_data)
        mismatched_descriptors = dict(descriptors)
        mismatched_main = bytearray(mismatched_descriptors["main"])
        mismatched_main[12] ^= 0x01
        mismatched_descriptors["main"] = bytes(mismatched_main)
        descriptor_mismatch_helper = compile_helper(
            commands,
            fixture,
            "helper-descriptor-mismatch",
            mismatched_descriptors,
            static=True,
        )

        libcomposite = compile_module(
            commands,
            fixture,
            "libcomposite",
            kernel_release=KERNEL_RELEASE,
            depends="",
        )
        usb_f_hid = compile_module(
            commands,
            fixture,
            "usb_f_hid",
            kernel_release=KERNEL_RELEASE,
            depends="libcomposite",
        )
        wrong_abi_module = compile_module(
            commands,
            fixture,
            "libcomposite_wrong_abi",
            kernel_release="6.18.33-wrong-rpi-v8",
            depends="",
        )
        wrong_arch_module = fixture / "libcomposite_wrong_arch.ko"
        wrong_arch_module_data = bytearray(libcomposite.read_bytes())
        struct.pack_into("<H", wrong_arch_module_data, 18, 62)
        wrong_arch_module.write_bytes(wrong_arch_module_data)
        wrong_dependency_module = compile_module(
            commands,
            fixture,
            "usb_f_hid_wrong_dependency",
            kernel_release=KERNEL_RELEASE,
            depends="libcomposite,unexpected",
        )
        assert module_field(commands, libcomposite, "vermagic").split()[0] == KERNEL_RELEASE
        assert module_field(commands, libcomposite, "depends") == ""
        assert module_field(commands, usb_f_hid, "vermagic").split()[0] == KERNEL_RELEASE
        assert module_field(commands, usb_f_hid, "depends") == "libcomposite"

        identity_path = fixture / "usb-identity.env"
        identity_path.write_text(IDENTITY_TEXT, encoding="utf-8")
        expected_identity = early.read_identity(identity_path)

        base = fixture / "base-initramfs8"
        base.write_bytes(base_bytes(commands))
        base_data = base.read_bytes()
        base_records, base_boundary = early.locate_base_boundary(base_data)
        assert {record["path"] for record in base_records} == {"early-fixture"}
        assert base_data[base_boundary:].startswith(early.ZSTD_MAGIC)
        main_records = early.validate_main_archive(base_data[base_boundary:])
        main_by_path = {record["path"]: record for record in main_records}
        for path in ("scripts", "scripts/init-premount"):
            assert main_by_path[path]["mode"] == 0o040755

        unpack_records = {"probe": {"data": b"overlay\n"}}
        unpack_modes = {"probe": 0o100644}
        legacy_unpack = fixture / "legacy-unpack"
        legacy_unpack.mkdir()
        (legacy_unpack / "probe").write_bytes(b"overlay\n")
        early.verify_unmkinitramfs_overlay(legacy_unpack, unpack_records, unpack_modes)
        split_unpack = fixture / "split-unpack"
        for component in ("early", "early2", "main"):
            (split_unpack / component).mkdir(parents=True)
        (split_unpack / "early2" / "probe").write_bytes(b"overlay\n")
        early.verify_unmkinitramfs_overlay(split_unpack, unpack_records, unpack_modes)
        (split_unpack / "early2" / "probe").write_bytes(b"wrong\n")
        try:
            early.verify_unmkinitramfs_overlay(split_unpack, unpack_records, unpack_modes)
        except early.VerifyError as exc:
            assert "content mismatch: probe" in str(exc)
        else:
            raise AssertionError("unmkinitramfs content mismatch was accepted")

        builds: list[tuple[Path, Path]] = []
        build_results = []
        for number in (1, 2):
            output = fixture / f"build-{number}" / "initramfs-hidloom-e1"
            manifest_path = fixture / f"build-{number}" / "early-image.json"
            result = run(
                build_command(
                    base=base,
                    output=output,
                    manifest=manifest_path,
                    helper=helper,
                    libcomposite=libcomposite,
                    usb_f_hid=usb_f_hid,
                    identity=identity_path,
                )
            )
            build_results.append(json.loads(result.stdout))
            builds.append((output, manifest_path))

        (image, manifest_path), (image_second, manifest_second) = builds
        assert image.read_bytes() == image_second.read_bytes()
        assert manifest_path.read_bytes() == manifest_second.read_bytes()
        assert {
            key: value for key, value in build_results[0].items() if key != "output"
        } == {
            key: value for key, value in build_results[1].items() if key != "output"
        }

        deep_result = json.loads(run(verify_command(base, image, manifest_path)).stdout)
        assert deep_result["status"] == "pass"
        assert deep_result["kernel_release"] == KERNEL_RELEASE

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        image_data = image.read_bytes()
        boundary = manifest["base"]["zstd_offset"]
        overlay_size = manifest["overlay"]["size"]
        output_boundary = boundary + overlay_size
        assert boundary == base_boundary
        assert image_data[:boundary] == base_data[:boundary]
        assert image_data[output_boundary:] == base_data[boundary:]
        assert manifest["base"]["prefix"] == {
            "size": boundary,
            "sha256": sha256(base_data[:boundary]),
        }
        assert manifest["base"]["suffix"] == {
            "size": len(base_data) - boundary,
            "sha256": sha256(base_data[boundary:]),
        }
        assert overlay_size % 512 == 0
        assert image_data[output_boundary:].startswith(early.ZSTD_MAGIC)

        overlay = image_data[boundary:output_boundary]
        records = early.overlay_records(overlay)
        assert set(records) == early.EXPECTED_PATHS
        for path, mode in {**early.DIR_MODES, **early.FILE_MODES}.items():
            record = records[path]
            assert record["mode"] == mode
            assert record["uid"] == record["gid"] == record["mtime"] == 0
        assert records["conf/param.conf"]["data"] == early.PARAM_CONF
        assert records["scripts/init-premount/hidloom-early-gadget"]["data"] == early.hook_bytes(
            KERNEL_RELEASE, manifest["runtime_contract"]["sha256"]
        )
        assert records["usr/lib/hidloom/early/hidloom-usb-gadget-fast"]["data"] == helper.read_bytes()

        assert manifest["source"] == SOURCE_ID
        assert manifest["kernel_release"] == KERNEL_RELEASE
        assert manifest["profile"] == {"id": PROFILE_ID, "sha256": PROFILE_SHA256}
        assert manifest["identity"] == expected_identity
        embedded_identity = early.parse_identity_text(
            records["conf/hidloom-early-usb.env"]["data"].decode("utf-8"), embedded=True
        )
        assert embedded_identity == expected_identity
        contract = json.loads(records["conf/hidloom-early-contract.json"]["data"])
        assert {
            key: value
            for key, value in manifest["runtime_contract"].items()
            if key != "sha256"
        } == contract
        assert manifest["runtime_contract"]["sha256"] == sha256(
            records["conf/hidloom-early-contract.json"]["data"]
        )
        assert contract["profile"] == manifest["profile"]
        assert contract["identity_sha256"] == sha256(
            records["conf/hidloom-early-usb.env"]["data"]
        )
        assert contract["helper_sha256"] == sha256(helper.read_bytes())
        assert manifest["helper"] == {
            "architecture": "aarch64",
            "static": True,
            "sha256": sha256(helper.read_bytes()),
        }
        assert manifest["modules"]["libcomposite"]["depends"] == []
        assert manifest["modules"]["usb_f_hid"]["depends"] == ["libcomposite"]
        assert manifest["descriptors"] == early.verify_descriptors(helper.read_bytes())

        tampered_image = fixture / "tampered-initramfs"
        tampered_manifest = fixture / "tampered-manifest.json"
        tampered_data = bytearray(image_data)
        marker = b"HIDLOOM_USB_SERIAL='vial:f64c2b3c'"
        marker_offset = tampered_data.find(marker, boundary, output_boundary)
        assert marker_offset >= 0
        tampered_data[marker_offset + len(marker) - 2] ^= 0x01
        tampered_image.write_bytes(tampered_data)
        tampered = json.loads(json.dumps(manifest))
        tampered["output"]["name"] = tampered_image.name
        tampered["output"]["sha256"] = sha256(tampered_data)
        tampered["overlay"]["sha256"] = sha256(
            tampered_data[boundary:output_boundary]
        )
        tampered_manifest.write_text(
            json.dumps(tampered, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        expect_failure(
            verify_command(base, tampered_image, tampered_manifest, deep=False),
            "embedded file hash",
        )

        identity_manifest = fixture / "identity-tamper.json"
        identity_tamper = json.loads(json.dumps(manifest))
        identity_tamper["identity"]["HIDLOOM_USB_SERIAL"] = "vial:tampered"
        identity_manifest.write_text(
            json.dumps(identity_tamper, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        expect_failure(
            verify_command(base, image, identity_manifest, deep=False), "identity"
        )

        profile_manifest = fixture / "profile-tamper.json"
        profile_tamper = json.loads(json.dumps(manifest))
        profile_tamper["profile"]["id"] = "keyboard-tampered"
        profile_manifest.write_text(
            json.dumps(profile_tamper, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        expect_failure(
            verify_command(base, image, profile_manifest, deep=False), "runtime contract"
        )

        unsafe_base = fixture / "unsafe-base-initramfs"
        unsafe_base.write_bytes(
            base_bytes(
                commands,
                early_entries={"../escape": (0o100644, b"must be rejected\n")},
            )
        )
        unknown_base = fixture / "unknown-base-initramfs"
        unknown_base.write_bytes(b"not a supported initramfs\n")
        collision_base = fixture / "collision-base-initramfs"
        collision_base.write_bytes(
            base_bytes(
                commands,
                main_extra={"conf/param.conf": (0o100644, b"collision\n")},
            )
        )

        negative_build(
            fixture,
            "unsafe-cpio",
            base=unsafe_base,
            helper=helper,
            libcomposite=libcomposite,
            usb_f_hid=usb_f_hid,
            identity=identity_path,
            phrase="unsafe cpio",
        )
        negative_build(
            fixture,
            "unknown-base",
            base=unknown_base,
            helper=helper,
            libcomposite=libcomposite,
            usb_f_hid=usb_f_hid,
            identity=identity_path,
            phrase="newc",
        )
        negative_build(
            fixture,
            "base-collision",
            base=collision_base,
            helper=helper,
            libcomposite=libcomposite,
            usb_f_hid=usb_f_hid,
            identity=identity_path,
            phrase="collides",
        )
        negative_build(
            fixture,
            "wrong-module-abi",
            base=base,
            helper=helper,
            libcomposite=wrong_abi_module,
            usb_f_hid=usb_f_hid,
            identity=identity_path,
            phrase="vermagic",
        )
        negative_build(
            fixture,
            "wrong-module-arch",
            base=base,
            helper=helper,
            libcomposite=wrong_arch_module,
            usb_f_hid=usb_f_hid,
            identity=identity_path,
            phrase="ARM64",
        )
        negative_build(
            fixture,
            "wrong-module-dependency",
            base=base,
            helper=helper,
            libcomposite=libcomposite,
            usb_f_hid=wrong_dependency_module,
            identity=identity_path,
            phrase="dependency contract",
        )
        negative_build(
            fixture,
            "dynamic-helper",
            base=base,
            helper=dynamic_helper,
            libcomposite=libcomposite,
            usb_f_hid=usb_f_hid,
            identity=identity_path,
            phrase="dynamically linked",
        )
        negative_build(
            fixture,
            "wrong-arch-helper",
            base=base,
            helper=wrong_arch_helper,
            libcomposite=libcomposite,
            usb_f_hid=usb_f_hid,
            identity=identity_path,
            phrase="ARM64",
        )
        negative_build(
            fixture,
            "descriptor-mismatch",
            base=base,
            helper=descriptor_mismatch_helper,
            libcomposite=libcomposite,
            usb_f_hid=usb_f_hid,
            identity=identity_path,
            phrase="descriptor",
        )

    print("ok: Raspberry Pi OS E1 initramfs builder/verifier")


if __name__ == "__main__":
    main()
