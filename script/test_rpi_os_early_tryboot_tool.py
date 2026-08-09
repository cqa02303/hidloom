#!/usr/bin/env python3
"""Focused regression tests for the host-only Raspberry Pi OS E2 staging tool."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import rpi_os_early_initramfs as e1  # noqa: E402


E1_TOOL = TOOLS / "rpi_os_early_initramfs.py"
E2_TOOL = TOOLS / "rpi_os_early_tryboot.py"
KERNEL = "6.18.34+rpt-rpi-v8"
PROFILE_SHA = "cdc8474b0363f2a303cdcf70faf054923bd233a5ac3fec6bd10cabe95630e5a8"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_elf(marker: bytes = b"") -> bytes:
    header = bytearray(64)
    header[:16] = b"\x7fELF\x02\x01\x01" + b"\x00" * 9
    struct.pack_into("<HHIQQQIHHHHHH", header, 16, 2, 183, 1, 0x400000, 64, 0, 0, 64, 56, 1, 0, 0, 0)
    payload_size = 64 + 56 + len(marker)
    program = struct.pack("<IIQQQQQQ", 1, 5, 0, 0x400000, 0x400000, payload_size, payload_size, 0x1000)
    return bytes(header) + program + marker


def make_newc(entries: dict[str, tuple[int, bytes]]) -> bytes:
    output = bytearray()
    for ino, (name, (mode, data)) in enumerate(sorted(entries.items()), 1):
        encoded = name.encode() + b"\0"
        output += e1.cpio_header(ino, mode, len(encoded), len(data))
        output += encoded
        output += b"\0" * (-len(output) % 4)
        output += data
        output += b"\0" * (-len(output) % 4)
    trailer = b"TRAILER!!!\0"
    output += e1.cpio_header(len(entries) + 1, 0, len(trailer), 0)
    output += trailer
    output += b"\0" * (-len(output) % 512)
    return bytes(output)


def write_fake_modinfo(directory: Path) -> None:
    command = directory / "modinfo"
    command.write_text(
        """#!/usr/bin/env python3
from pathlib import Path
import os
import sys
field = sys.argv[2]
data = Path(sys.argv[3]).read_bytes()
for raw in os.environ.get('HIDLOOM_TEST_DELETE_STAGE_INPUTS', '').split(os.pathsep):
    if raw:
        Path(raw).unlink(missing_ok=True)
if b'MODULE:libcomposite' in data:
    module = 'libcomposite'
elif b'MODULE:usb_f_hid' in data:
    module = 'usb_f_hid'
else:
    raise SystemExit(1)
if field == 'vermagic':
    print('6.18.34+rpt-rpi-v8 SMP preempt mod_unload modversions aarch64')
elif field == 'depends':
    print('' if module == 'libcomposite' else 'libcomposite')
else:
    raise SystemExit(1)
""",
        encoding="utf-8",
    )
    command.chmod(0o755)


def run(command: list[str], env: dict[str, str], *, expect_ok: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if expect_ok:
        assert result.returncode == 0, (command, result.stdout, result.stderr)
    else:
        assert result.returncode != 0, (command, result.stdout, result.stderr)
        assert "error:" in result.stderr
    return result


def build_e1_fixture(work: Path, env: dict[str, str]) -> tuple[Path, Path]:
    early = make_newc({".": (0o040755, b"")})
    main = make_newc(
        {
            ".": (0o040755, b""),
            "scripts": (0o040755, b""),
            "scripts/init-premount": (0o040755, b""),
            "scripts/init-premount/ORDER": (0o100644, e1.ORDER_PARAM_LINE + b"\n"),
        }
    )
    compressed = subprocess.run(
        ["zstd", "-q", "-c"], input=main, stdout=subprocess.PIPE, check=True
    ).stdout
    base = work / "base-initramfs8"
    base.write_bytes(early + compressed)

    helper = work / "hidloom-usb-gadget-fast"
    helper.write_bytes(
        make_elf(
            b"HELPER\0"
            + e1.REPORT_DESCRIPTORS["main"]
            + b"\0SEP\0"
            + e1.REPORT_DESCRIPTORS["raw"]
            + b"\0SEP\0"
            + e1.REPORT_DESCRIPTORS["us_sub"]
            + b"\0SEP\0"
            + e1.REPORT_DESCRIPTORS["windows_ime_custom"]
        )
    )
    libcomposite = work / "libcomposite.ko"
    libcomposite.write_bytes(make_elf(b"MODULE:libcomposite\0"))
    usb_f_hid = work / "usb_f_hid.ko"
    usb_f_hid.write_bytes(make_elf(b"MODULE:usb_f_hid\0"))
    identity = work / "usb.env"
    identity.write_text(
        """HIDLOOM_USB_VENDOR_ID=0x1d6b
HIDLOOM_USB_PRODUCT_ID=0x0105
HIDLOOM_USB_MANUFACTURER=HIDloom
HIDLOOM_USB_PRODUCT_NAME=HIDloom Keyboard
HIDLOOM_USB_SERIAL=vial:f64c2b3c
HIDLOOM_USB_SERIAL_SUFFIX=
HIDLOOM_USB_US_SUB_KEYBOARD=1
HIDLOOM_WINDOWS_IME_CUSTOM_HID=0
""",
        encoding="utf-8",
    )
    image = work / "initramfs8-hidloom-e1"
    manifest = work / "early-image.json"
    run(
        [
            sys.executable,
            str(E1_TOOL),
            "build",
            "--base",
            str(base),
            "--output",
            str(image),
            "--manifest",
            str(manifest),
            "--kernel-release",
            KERNEL,
            "--source",
            "0123456789ab",
            "--profile-id",
            "keyboard-ver1",
            "--profile-sha256",
            PROFILE_SHA,
            "--helper",
            str(helper),
            "--libcomposite",
            str(libcomposite),
            "--usb-f-hid",
            str(usb_f_hid),
            "--identity-env",
            str(identity),
        ],
        env,
    )
    accepted = json.loads(manifest.read_text(encoding="utf-8"))
    accepted["adopt"] = {
        "schema": "hidloom.rpi-os-early-gadget-adopt.v1",
        "packages": {
            "core": {"name": "hidloom-core", "version": "0.0.1+fixture"},
            "profile": {
                "name": "hidloom-profile-keyboard-ver1",
                "version": "0.0.1+fixture",
            },
        },
        "gadget": {"schema": "hidloom.configfs-usb-gadget.snapshot.v1"},
    }
    manifest.write_text(
        json.dumps(accepted, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return image, manifest


def stage_command(
    config: Path,
    cmdline: Path,
    image: Path,
    manifest: Path,
    kernel: Path,
    output: Path,
    *,
    kernel_name: str = "kernel8-hidloom-e1.img",
    allow_device_path: bool = False,
) -> list[str]:
    command = [
        sys.executable,
        str(E2_TOOL),
        "stage",
        "--config",
        str(config),
        "--cmdline",
        str(cmdline),
        "--e1-image",
        str(image),
        "--e1-manifest",
        str(manifest),
        "--kernel-image",
        str(kernel),
        "--kernel-image-name",
        kernel_name,
        "--output-dir",
        str(output),
    ]
    if allow_device_path:
        command.append("--allow-device-path")
    return command


def directory_bytes(path: Path) -> dict[str, bytes]:
    return {item.name: item.read_bytes() for item in sorted(path.iterdir()) if item.is_file()}


def write_boot_inputs(
    directory: Path, config_raw: bytes, cmdline_raw: bytes
) -> tuple[Path, Path]:
    directory.mkdir(parents=True)
    config = directory / "config.txt"
    cmdline = directory / "cmdline.txt"
    config.write_bytes(config_raw)
    cmdline.write_bytes(cmdline_raw)
    return config, cmdline


def main() -> None:
    assert E1_TOOL.is_file() and E2_TOOL.is_file()
    assert shutil.which("zstd")
    with tempfile.TemporaryDirectory(prefix="hidloom-e2-test-") as directory:
        work = Path(directory)
        fake_bin = work / "bin"
        fake_bin.mkdir()
        write_fake_modinfo(fake_bin)
        env = os.environ.copy()
        env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]
        image, manifest = build_e1_fixture(work, env)

        config = work / "config.txt"
        config_raw = (
            b"# ordinary Raspberry Pi OS boot\n"
            b"[all]\n"
            b"auto_initramfs=1\n"
            b"arm_64bit=1\n"
            b"dtoverlay=dwc2,dr_mode=peripheral\n"
        )
        config.write_bytes(config_raw)
        cmdline = work / "cmdline.txt"
        cmdline_raw = b"console=serial0,115200 root=PARTUUID=1234-02 rootwait quiet\n"
        cmdline.write_bytes(cmdline_raw)
        kernel = work / "kernel8.img"
        kernel_payload = bytearray(160)
        kernel_payload[0x38:0x3C] = b"ARM\x64"
        kernel_payload += b"Linux version " + KERNEL.encode("ascii") + b"\0"
        kernel_raw = gzip.compress(bytes(kernel_payload), mtime=0)
        kernel.write_bytes(kernel_raw)

        out_a = work / "stage-a"
        out_b = work / "stage-b"
        run(stage_command(config, cmdline, image, manifest, kernel, out_a), env)
        run(stage_command(config, cmdline, image, manifest, kernel, out_b), env)
        files_a = directory_bytes(out_a)
        files_b = directory_bytes(out_b)
        assert files_a == files_b
        assert set(files_a) == {
            "tryboot.txt",
            "cmdline-hidloom-e1.txt",
            "initramfs8-hidloom-e1",
            "kernel8-hidloom-e1.img",
            "early-image.accepted.json",
            "tryboot-placement.json",
        }
        assert files_a["tryboot.txt"].startswith(config_raw)
        assert files_a["tryboot.txt"].endswith(
            b"[all]\nauto_initramfs=0\nkernel=kernel8-hidloom-e1.img\n"
            b"cmdline=cmdline-hidloom-e1.txt\n"
            b"initramfs initramfs8-hidloom-e1 followkernel\n"
        )
        assert files_a["cmdline-hidloom-e1.txt"] == (
            cmdline_raw[:-1] + b" hidloom.early=e1 panic=10\n"
        )
        assert files_a["initramfs8-hidloom-e1"] == image.read_bytes()
        assert files_a["kernel8-hidloom-e1.img"] == kernel_raw
        assert files_a["early-image.accepted.json"] == manifest.read_bytes()
        assert config.read_bytes() == config_raw
        assert cmdline.read_bytes() == cmdline_raw
        assert stat.S_IMODE(out_a.stat().st_mode) == 0o755
        assert all(stat.S_IMODE(item.stat().st_mode) == 0o644 for item in out_a.iterdir())
        assert not list(work.glob(".stage-a.tmp-*"))
        assert not list(work.glob(".stage-b.tmp-*"))
        verify_result = run(
            [sys.executable, str(E2_TOOL), "verify", "--directory", str(out_a)], env
        )
        assert json.loads(verify_result.stdout)["status"] == "pass"

        placement = json.loads(files_a["tryboot-placement.json"])
        assert placement["schema"] == "hidloom.rpi-os-early-tryboot-placement.v1"
        assert placement["kernel"] == {
            "release": KERNEL,
            "compression": "gzip",
            "payload_format": "arm64-image",
            "input": {
                "path": "kernel8.img",
                "role": "kernel_input",
                "sha256": sha256(kernel_raw),
                "size": len(kernel_raw),
            },
            "staged": {
                "path": "kernel8-hidloom-e1.img",
                "role": "alternate_kernel",
                "sha256": sha256(kernel_raw),
                "size": len(kernel_raw),
            },
        }
        assert placement["activation"]["default_boot_modified"] is False
        assert placement["activation"]["cmdline_tokens_added"] == [
            "hidloom.early=e1",
            "panic=10",
        ]
        assert placement["activation"]["panic_seconds"] == 10
        records = {item["path"]: item for item in placement["files"]}
        for name, data in files_a.items():
            if name == "tryboot-placement.json":
                continue
            assert records[name]["size"] == len(data)
            assert records[name]["sha256"] == sha256(data)
        generated_lines = files_a["tryboot.txt"][len(config_raw) :].splitlines()
        assert generated_lines
        assert max(map(len, generated_lines)) <= 98

        raw_kernel = work / "kernel8-raw.img"
        raw_kernel.write_bytes(kernel_payload)
        raw_output = work / "stage-raw"
        run(stage_command(config, cmdline, image, manifest, raw_kernel, raw_output), env)
        raw_placement = json.loads((raw_output / "tryboot-placement.json").read_text())
        assert raw_placement["kernel"]["compression"] == "none"
        assert raw_placement["kernel"]["payload_format"] == "arm64-image"
        run(
            [sys.executable, str(E2_TOOL), "verify", "--directory", str(raw_output)], env
        )

        run(
            stage_command(
                config, cmdline, image, manifest, kernel, work / "unsafe",
                kernel_name="../kernel8.img",
            ),
            env,
            expect_ok=False,
        )

        for default_kernel_name in (
            "kernel.img",
            "kernel7.img",
            "kernel7l.img",
            "kernel8.img",
        ):
            run(
                stage_command(
                    config,
                    cmdline,
                    image,
                    manifest,
                    kernel,
                    work / f"default-{default_kernel_name}",
                    kernel_name=default_kernel_name,
                ),
                env,
                expect_ok=False,
            )

        run(
            stage_command(
                config,
                cmdline,
                image,
                manifest,
                kernel,
                work / "long-config-line",
                kernel_name="k" * 90 + ".img",
            ),
            env,
            expect_ok=False,
        )

        renamed_config = work / "renamed-config.txt"
        renamed_config.write_bytes(config_raw)
        run(
            stage_command(
                renamed_config, cmdline, image, manifest, kernel, work / "renamed-config"
            ),
            env,
            expect_ok=False,
        )
        renamed_cmdline = work / "renamed-cmdline.txt"
        renamed_cmdline.write_bytes(cmdline_raw)
        run(
            stage_command(
                config, renamed_cmdline, image, manifest, kernel, work / "renamed-cmdline"
            ),
            env,
            expect_ok=False,
        )

        early_config, early_cmdline = write_boot_inputs(
            work / "existing-early-inputs",
            config_raw,
            cmdline_raw[:-1] + b" hidloom.early=e0\n",
        )
        run(
            stage_command(
                early_config, early_cmdline, image, manifest, kernel, work / "existing-early"
            ),
            env,
            expect_ok=False,
        )

        panic_config, panic_cmdline = write_boot_inputs(
            work / "existing-panic-inputs",
            config_raw,
            cmdline_raw[:-1] + b" panic=5\n",
        )
        run(
            stage_command(
                panic_config, panic_cmdline, image, manifest, kernel, work / "existing-panic"
            ),
            env,
            expect_ok=False,
        )

        multiline_config, multiline_cmdline = write_boot_inputs(
            work / "multiline-inputs", config_raw, b"root=/dev/a\nquiet\n"
        )
        run(
            stage_command(
                multiline_config,
                multiline_cmdline,
                image,
                manifest,
                kernel,
                work / "multiline",
            ),
            env,
            expect_ok=False,
        )

        conflict_config, conflict_cmdline = write_boot_inputs(
            work / "config-conflict-inputs", config_raw + b"kernel=other.img\n", cmdline_raw
        )
        run(
            stage_command(
                conflict_config,
                conflict_cmdline,
                image,
                manifest,
                kernel,
                work / "config-conflict",
            ),
            env,
            expect_ok=False,
        )

        include_config, include_cmdline = write_boot_inputs(
            work / "config-include-inputs", config_raw + b"include extra.txt\n", cmdline_raw
        )
        run(
            stage_command(
                include_config,
                include_cmdline,
                image,
                manifest,
                kernel,
                work / "config-include",
            ),
            env,
            expect_ok=False,
        )

        no_adopt_manifest = work / "early-image-no-adopt.json"
        no_adopt = json.loads(manifest.read_text(encoding="utf-8"))
        del no_adopt["adopt"]
        no_adopt_manifest.write_text(json.dumps(no_adopt), encoding="utf-8")
        run(
            stage_command(
                config,
                cmdline,
                image,
                no_adopt_manifest,
                kernel,
                work / "missing-adopt",
            ),
            env,
            expect_ok=False,
        )

        tampered_dir = work / "tampered"
        tampered_dir.mkdir()
        tampered_image = tampered_dir / image.name
        tampered = bytearray(image.read_bytes())
        tampered[-1] ^= 1
        tampered_image.write_bytes(tampered)
        run(
            stage_command(config, cmdline, tampered_image, manifest, kernel, work / "tampered-image"),
            env,
            expect_ok=False,
        )

        tampered_manifest = work / "tampered-manifest.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["output"]["sha256"] = "0" * 64
        tampered_manifest.write_text(json.dumps(payload), encoding="utf-8")
        run(
            stage_command(config, cmdline, image, tampered_manifest, kernel, work / "tampered-manifest"),
            env,
            expect_ok=False,
        )

        unlinked_kernel = work / "kernel8-unlinked.img"
        unlinked_payload = bytearray(128)
        unlinked_payload[0x38:0x3C] = b"ARM\x64"
        unlinked_payload += b"Linux version unrelated-release\0"
        unlinked_kernel.write_bytes(gzip.compress(bytes(unlinked_payload), mtime=0))
        run(
            stage_command(
                config,
                cmdline,
                image,
                manifest,
                unlinked_kernel,
                work / "unlinked-kernel",
            ),
            env,
            expect_ok=False,
        )

        unknown_kernel = work / "kernel8-unknown.img"
        unknown_kernel.write_bytes(b"not a known kernel format " + KERNEL.encode())
        run(
            stage_command(
                config,
                cmdline,
                image,
                manifest,
                unknown_kernel,
                work / "unknown-kernel",
            ),
            env,
            expect_ok=False,
        )

        invalid_gzip_kernel = work / "kernel8-invalid-gzip.img"
        invalid_gzip_kernel.write_bytes(b"\x1f\x8btruncated")
        run(
            stage_command(
                config,
                cmdline,
                image,
                manifest,
                invalid_gzip_kernel,
                work / "invalid-gzip-kernel",
            ),
            env,
            expect_ok=False,
        )

        for boot_root in (Path("/boot"), Path("/boot/firmware")):
            boot_output = boot_root / f"hidloom-e2-refuse-{os.getpid()}"
            assert not boot_output.exists()
            run(
                stage_command(config, cmdline, image, manifest, kernel, boot_output),
                env,
                expect_ok=False,
            )
            assert not boot_output.exists()

        before_existing_retry = directory_bytes(out_a)
        run(
            stage_command(config, cmdline, image, manifest, kernel, out_a),
            env,
            expect_ok=False,
        )
        assert directory_bytes(out_a) == before_existing_retry

        verify_tampered = work / "verify-tampered"
        shutil.copytree(out_a, verify_tampered)
        altered_cmdline = bytearray((verify_tampered / "cmdline-hidloom-e1.txt").read_bytes())
        altered_cmdline[0] ^= 1
        (verify_tampered / "cmdline-hidloom-e1.txt").write_bytes(altered_cmdline)
        run(
            [sys.executable, str(E2_TOOL), "verify", "--directory", str(verify_tampered)],
            env,
            expect_ok=False,
        )

        verify_bad_mode = work / "verify-bad-mode"
        shutil.copytree(out_a, verify_bad_mode)
        (verify_bad_mode / "tryboot.txt").chmod(0o600)
        run(
            [sys.executable, str(E2_TOOL), "verify", "--directory", str(verify_bad_mode)],
            env,
            expect_ok=False,
        )

        toctou_inputs = work / "toctou-inputs"
        toctou_inputs.mkdir()
        toctou_config = toctou_inputs / "config.txt"
        toctou_cmdline = toctou_inputs / "cmdline.txt"
        toctou_image = toctou_inputs / image.name
        toctou_manifest = toctou_inputs / "early-image.json"
        toctou_kernel = toctou_inputs / "kernel8.img"
        toctou_values = {
            toctou_config: config_raw,
            toctou_cmdline: cmdline_raw,
            toctou_image: image.read_bytes(),
            toctou_manifest: manifest.read_bytes(),
            toctou_kernel: kernel_raw,
        }
        for path, data in toctou_values.items():
            path.write_bytes(data)
        toctou_env = env.copy()
        toctou_env["HIDLOOM_TEST_DELETE_STAGE_INPUTS"] = os.pathsep.join(
            str(path) for path in toctou_values
        )
        toctou_output = work / "toctou-output"
        run(
            stage_command(
                toctou_config,
                toctou_cmdline,
                toctou_image,
                toctou_manifest,
                toctou_kernel,
                toctou_output,
            ),
            toctou_env,
        )
        assert all(not path.exists() for path in toctou_values)
        assert (toctou_output / image.name).read_bytes() == toctou_values[toctou_image]
        assert (toctou_output / "kernel8-hidloom-e1.img").read_bytes() == kernel_raw
        run(
            [sys.executable, str(E2_TOOL), "verify", "--directory", str(toctou_output)], env
        )
        assert not list(work.glob(".toctou-output.tmp-*"))

    print("ok: Raspberry Pi OS E2 host-only tryboot staging tool")


if __name__ == "__main__":
    main()
