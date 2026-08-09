#!/usr/bin/env python3
"""Focused regression tests for disabled E2 tryboot placement."""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
SCRIPT = ROOT / "script"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(SCRIPT))

import rpi_os_early_tryboot_place as place  # noqa: E402
import test_rpi_os_early_tryboot_tool as fixture  # noqa: E402


TOOL = TOOLS / "rpi_os_early_tryboot_place.py"
MODEL = "Raspberry Pi Zero 2 W Rev 1.0"
NORMAL_INITRAMFS = "base-initramfs8"


def run(
    command: list[str],
    env: dict[str, str],
    *,
    expect_ok: bool = True,
) -> subprocess.CompletedProcess[str]:
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
        assert "error:" in result.stderr, (command, result.stdout, result.stderr)
    return result


def directory_bytes(path: Path) -> dict[str, bytes]:
    return {
        item.name: item.read_bytes()
        for item in sorted(path.iterdir())
        if item.is_file()
    }


def make_stage_template(work: Path, env: dict[str, str]) -> tuple[Path, Path]:
    source = work / "source"
    source.mkdir(mode=0o755)
    image, manifest = fixture.build_e1_fixture(source, env)
    config = source / "config.txt"
    config.write_bytes(
        b"# normal Raspberry Pi OS boot\n"
        b"[all]\n"
        b"auto_initramfs=1\n"
        b"arm_64bit=1\n"
        b"dtoverlay=dwc2,dr_mode=peripheral\n"
    )
    cmdline = source / "cmdline.txt"
    cmdline.write_bytes(
        b"console=serial0,115200 root=PARTUUID=1234-02 rootwait quiet\n"
    )
    payload = bytearray(160)
    payload[0x38:0x3C] = b"ARM\x64"
    payload += b"Linux version " + fixture.KERNEL.encode("ascii") + b"\0"
    kernel = source / "kernel8.img"
    kernel.write_bytes(gzip.compress(bytes(payload), mtime=0))
    for path in (image, manifest, source / NORMAL_INITRAMFS, config, cmdline, kernel):
        path.chmod(0o644)
    stage = work / "stage-template"
    fixture.run(
        fixture.stage_command(config, cmdline, image, manifest, kernel, stage), env
    )
    normal = work / "normal-template"
    normal.mkdir(mode=0o755)
    shutil.copy2(config, normal / config.name)
    shutil.copy2(cmdline, normal / cmdline.name)
    shutil.copy2(kernel, normal / kernel.name)
    shutil.copy2(source / NORMAL_INITRAMFS, normal / NORMAL_INITRAMFS)
    return stage, normal


def make_case(work: Path, name: str, stage_template: Path, normal: Path) -> dict[str, Any]:
    case = work / name
    case.mkdir(mode=0o755)
    stage = case / "stage"
    boot = case / "boot"
    shutil.copytree(stage_template, stage)
    shutil.copytree(normal, boot)
    rootfs = case / "rootfs"
    rootfs.mkdir(mode=0o755)
    accepted = rootfs / "early-boot"
    backups = case / "backups"
    backups.mkdir(mode=0o755)
    backup = backups / "before-e2"
    live = case / "live"
    live.mkdir(mode=0o755)
    for path in (case, stage, boot, rootfs, backups, live):
        assert stat.S_IMODE(path.stat().st_mode) == 0o755
    model = live / "model"
    model.write_bytes(MODEL.encode() + b"\0")
    model.chmod(0o444)
    release = live / "osrelease"
    release.write_text(fixture.KERNEL + "\n", encoding="utf-8")
    release.chmod(0o444)
    return {
        "case": case,
        "stage": stage,
        "boot": boot,
        "accepted": accepted,
        "backup": backup,
        "model": model,
        "release": release,
        "placement_sha256": place.sha256_bytes(
            (stage / "tryboot-placement.json").read_bytes()
        ),
    }


def options(case: dict[str, Any]) -> list[str]:
    return [
        "--stage-dir",
        str(case["stage"]),
        "--boot-root",
        str(case["boot"]),
        "--accepted-root",
        str(case["accepted"]),
        "--backup-dir",
        str(case["backup"]),
        "--normal-initramfs-name",
        NORMAL_INITRAMFS,
        "--model-path",
        str(case["model"]),
        "--expected-model",
        MODEL,
        "--kernel-release-path",
        str(case["release"]),
        "--expected-kernel-release",
        fixture.KERNEL,
        "--expected-placement-sha256",
        case["placement_sha256"],
        "--expected-owner-uid",
        str(os.getuid()),
        "--minimum-free-bytes",
        "0",
    ]


def command(action: str, case: dict[str, Any]) -> list[str]:
    return [sys.executable, str(TOOL), action, *options(case)]


def normal_snapshot(case: dict[str, Any]) -> dict[str, bytes]:
    return {
        name: (case["boot"] / name).read_bytes()
        for name in ("config.txt", "cmdline.txt", "kernel8.img", NORMAL_INITRAMFS)
    }


def assert_no_install_outputs(case: dict[str, Any]) -> None:
    placement = json.loads(
        (case["stage"] / "tryboot-placement.json").read_text(encoding="utf-8")
    )
    names = {
        record["path"]
        for record in placement["files"]
        if record["path"] != "early-image.accepted.json"
    }
    assert all(not (case["boot"] / name).exists() for name in names)
    assert not case["accepted"].exists()
    assert not case["backup"].exists()
    assert not list(case["boot"].glob(".hidloom-e2-place-*"))


def main() -> None:
    assert TOOL.is_file()
    assert os.access(TOOL, os.X_OK)
    assert shutil.which("zstd")
    with tempfile.TemporaryDirectory(prefix="hidloom-e2-place-test-") as directory:
        work = Path(directory)
        fake_bin = work / "bin"
        fake_bin.mkdir(mode=0o755)
        fixture.write_fake_modinfo(fake_bin)
        env = os.environ.copy()
        env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]
        stage_template, normal = make_stage_template(work, env)

        # procfs reports these immutable pseudo-files with st_size == 0 even
        # though a read returns content.  This is the real-device condition
        # that the placement preflight must not treat as an empty file.
        proc_release = Path("/proc/sys/kernel/osrelease")
        proc_ostype = Path("/proc/sys/kernel/ostype")
        assert proc_release.stat().st_size == 0
        assert proc_ostype.stat().st_size == 0
        proc_release_raw = place.read_bounded_pseudo_file(
            proc_release,
            "test live kernel release",
            proc_release.stat().st_uid,
        )
        assert place.normalize_text_file(
            proc_release_raw, "test live kernel release"
        ) == os.uname().release
        assert place.normalize_text_file(
            place.read_bounded_pseudo_file(
                proc_ostype,
                "test immutable model-like pseudo-file",
                proc_ostype.stat().st_uid,
            ),
            "test immutable model-like pseudo-file",
        ) == "Linux"
        try:
            place.read_bounded_pseudo_file(
                proc_release,
                "bounded live kernel release",
                proc_release.stat().st_uid,
                max_bytes=1,
            )
        except place.PlacementError as exc:
            assert "safety bound" in str(exc)
        else:
            raise AssertionError("unbounded procfs read unexpectedly passed")

        success = make_case(work, "success", stage_template, normal)
        original_normal = normal_snapshot(success)

        # Device placement is deliberately bounded: host deep verification is
        # anchored by its placement digest, and no stage file is materialized
        # through Path.read_bytes or expanded again on the target.  Both the
        # successful and rejected preflight paths must close retained FDs.
        streaming = make_case(work, "streaming", stage_template, normal)
        streaming_args = place.parser().parse_args(
            ["preflight", *options(streaming)]
        )
        original_deep_verify = place.tryboot.verify_stage_directory
        original_read_bytes = Path.read_bytes
        fd_count_before = len(list(Path("/proc/self/fd").iterdir()))

        def reject_deep_verify(_directory: Path) -> dict[str, Any]:
            raise AssertionError("device placement invoked host deep verification")

        def reject_path_read_bytes(_path: Path) -> bytes:
            raise AssertionError("device placement materialized a file with Path.read_bytes")

        place.tryboot.verify_stage_directory = reject_deep_verify
        Path.read_bytes = reject_path_read_bytes
        try:
            streaming_result = place.preflight(streaming_args)
            assert streaming_result["verification"] == (
                "host-deep-verified-digest+device-streaming"
            )
        finally:
            Path.read_bytes = original_read_bytes
            place.tryboot.verify_stage_directory = original_deep_verify
        assert len(list(Path("/proc/self/fd").iterdir())) == fd_count_before
        streaming_args.expected_placement_sha256 = "0" * 64
        try:
            place.preflight(streaming_args)
        except place.PlacementError as exc:
            assert "host deep-verification digest" in str(exc)
        else:
            raise AssertionError("incorrect host placement digest unexpectedly passed")
        assert len(list(Path("/proc/self/fd").iterdir())) == fd_count_before
        assert_no_install_outputs(streaming)

        preflight = run(command("preflight", success), env)
        preflight_result = json.loads(preflight.stdout)
        assert preflight_result["status"] == "pass"
        assert preflight_result["state"] == "placement-ready-disabled"
        assert preflight_result["default_boot_modified"] is False
        assert preflight_result["one_shot_requested"] is False
        assert normal_snapshot(success) == original_normal
        assert_no_install_outputs(success)

        wrong_pin = command("preflight", success)
        wrong_pin[wrong_pin.index("--expected-placement-sha256") + 1] = "0" * 64
        run(wrong_pin, env, expect_ok=False)
        assert_no_install_outputs(success)

        installed = run(command("install-disabled", success), env)
        installed_result = json.loads(installed.stdout)
        assert installed_result["status"] == "pass"
        assert installed_result["state"] == "installed-disabled"
        assert installed_result["default_boot_modified"] is False
        assert installed_result["one_shot_requested"] is False
        assert normal_snapshot(success) == original_normal

        placement = json.loads(
            (success["stage"] / "tryboot-placement.json").read_text(encoding="utf-8")
        )
        boot_records = {
            record["path"]: record
            for record in placement["files"]
            if record["path"] != "early-image.accepted.json"
        }
        for name in boot_records:
            assert (success["boot"] / name).read_bytes() == (
                success["stage"] / name
            ).read_bytes()
        assert (success["accepted"] / "early-image.accepted.json").read_bytes() == (
            success["stage"] / "early-image.accepted.json"
        ).read_bytes()
        receipt = json.loads(
            (success["accepted"] / "tryboot-install.json").read_text(encoding="utf-8")
        )
        assert receipt["schema"] == place.SCHEMA
        assert receipt["status"] == "installed-disabled"
        assert receipt["activation"] == {
            "default_boot_modified": False,
            "one_shot_requested": False,
            "reboot_requested": False,
            "tryboot_published_last": True,
        }
        assert set(directory_bytes(success["backup"])) == {
            "config.txt",
            "cmdline.txt",
            "kernel8.img",
            NORMAL_INITRAMFS,
            "normal-boot-backup.json",
        }
        for name, data in original_normal.items():
            assert (success["backup"] / name).read_bytes() == data
        assert stat.S_IMODE((success["accepted"] / "tryboot-install.json").stat().st_mode) == 0o600
        assert all(
            stat.S_IMODE((success["backup"] / name).stat().st_mode) == 0o600
            for name in directory_bytes(success["backup"])
        )
        run(command("verify-installed", success), env)

        # A boot VFAT mounted with fmask=0022 presents files as 0755.  This is
        # accepted as long as ownership, immutability, and hashes remain exact.
        for name in boot_records:
            (success["boot"] / name).chmod(0o755)
        run(command("verify-installed", success), env)

        installed_tree = directory_bytes(success["boot"])
        run(command("install-disabled", success), env, expect_ok=False)
        assert directory_bytes(success["boot"]) == installed_tree

        cmdline = success["boot"] / "cmdline.txt"
        cmdline.write_bytes(original_normal["cmdline.txt"] + b"changed")
        run(command("verify-installed", success), env, expect_ok=False)
        cmdline.write_bytes(original_normal["cmdline.txt"])
        run(command("verify-installed", success), env)

        alternate = next(name for name in boot_records if name.endswith(".img"))
        alternate_path = success["boot"] / alternate
        alternate_original = alternate_path.read_bytes()
        alternate_path.write_bytes(alternate_original + b"changed")
        run(command("verify-installed", success), env, expect_ok=False)
        alternate_path.write_bytes(alternate_original)
        alternate_path.chmod(0o755)
        run(command("verify-installed", success), env)

        forbidden = make_case(work, "forbidden", stage_template, normal)
        (forbidden["boot"] / "Autoboot.TXT").write_text("[tryboot]\n", encoding="utf-8")
        run(command("preflight", forbidden), env, expect_ok=False)
        assert_no_install_outputs(forbidden)

        collision = make_case(work, "collision", stage_template, normal)
        collision_name = next(
            record["path"]
            for record in placement["files"]
            if record["path"] not in {"tryboot.txt", "early-image.accepted.json"}
        )
        (collision["boot"] / collision_name.swapcase()).write_bytes(b"collision")
        run(command("preflight", collision), env, expect_ok=False)
        assert not collision["accepted"].exists()
        assert not collision["backup"].exists()

        mismatched = make_case(work, "mismatched", stage_template, normal)
        bad_model = command("preflight", mismatched)
        bad_model[bad_model.index("--expected-model") + 1] = "Raspberry Pi 5 Model B Rev 1.0"
        run(bad_model, env, expect_ok=False)
        bad_release = command("preflight", mismatched)
        bad_release[bad_release.index("--expected-kernel-release") + 1] = "other-release"
        run(bad_release, env, expect_ok=False)
        bad_owner = command("preflight", mismatched)
        bad_owner[bad_owner.index("--expected-owner-uid") + 1] = str(os.getuid() + 1)
        run(bad_owner, env, expect_ok=False)
        no_space = command("preflight", mismatched)
        no_space[no_space.index("--minimum-free-bytes") + 1] = str(2**63 - 1)
        run(no_space, env, expect_ok=False)
        assert_no_install_outputs(mismatched)

        insecure = make_case(work, "insecure", stage_template, normal)
        (insecure["stage"] / "tryboot.txt").chmod(0o664)
        run(command("preflight", insecure), env, expect_ok=False)
        assert_no_install_outputs(insecure)

        changed_default = make_case(work, "changed-default", stage_template, normal)
        (changed_default["boot"] / "config.txt").write_bytes(b"changed\n")
        run(command("preflight", changed_default), env, expect_ok=False)
        assert_no_install_outputs(changed_default)

        changed_initramfs = make_case(work, "changed-initramfs", stage_template, normal)
        (changed_initramfs["boot"] / NORMAL_INITRAMFS).write_bytes(b"other initramfs\n")
        run(command("preflight", changed_initramfs), env, expect_ok=False)
        assert_no_install_outputs(changed_initramfs)

        # The accepted E1 contract pins the live normal initramfs basename in
        # addition to its bytes.  A byte-identical copy under the actual live
        # name must not let a manifest built from a differently named input
        # reach placement.
        wrong_initramfs_name = make_case(
            work, "wrong-initramfs-name", stage_template, normal
        )
        live_initramfs_name = "initramfs8"
        accepted_base = wrong_initramfs_name["boot"] / NORMAL_INITRAMFS
        live_initramfs = wrong_initramfs_name["boot"] / live_initramfs_name
        shutil.copy2(accepted_base, live_initramfs)
        assert live_initramfs.stat().st_size == accepted_base.stat().st_size
        assert place.sha256_bytes(live_initramfs.read_bytes()) == place.sha256_bytes(
            accepted_base.read_bytes()
        )
        basename_mismatch = command("preflight", wrong_initramfs_name)
        basename_mismatch[
            basename_mismatch.index("--normal-initramfs-name") + 1
        ] = live_initramfs_name
        rejected = run(basename_mismatch, env, expect_ok=False)
        assert (
            "normal initramfs name differs from the accepted E1 base name"
            in rejected.stderr
        )
        assert_no_install_outputs(wrong_initramfs_name)

        # Inject a failure after backups, alternate boot files, and rootfs
        # receipts have been created but before tryboot.txt publication.  The
        # helper may remove only its tracked new files; defaults stay exact.
        rollback = make_case(work, "rollback", stage_template, normal)
        rollback_normal = normal_snapshot(rollback)
        args = place.parser().parse_args(["install-disabled", *options(rollback)])
        original_assert = place.assert_normal_unchanged
        calls = 0

        def fail_before_tryboot(context: place.PlacementContext) -> None:
            nonlocal calls
            calls += 1
            original_assert(context)
            if calls == 3:
                raise place.PlacementError("injected failure before tryboot publication")

        place.assert_normal_unchanged = fail_before_tryboot
        original_path = os.environ.get("PATH")
        os.environ["PATH"] = env["PATH"]
        try:
            try:
                place.install_disabled(args)
            except place.PlacementError as exc:
                assert "rolled back" in str(exc)
            else:
                raise AssertionError("injected placement failure unexpectedly passed")
        finally:
            place.assert_normal_unchanged = original_assert
            if original_path is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = original_path
        assert calls == 3
        assert normal_snapshot(rollback) == rollback_normal
        assert_no_install_outputs(rollback)

    print("ok: Raspberry Pi OS E2 disabled tryboot placement tool")


if __name__ == "__main__":
    main()
