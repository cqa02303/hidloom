#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/rpi_os_early_boot_control.py"
SPEC = importlib.util.spec_from_file_location("rpi_os_early_boot_control", TOOL)
assert SPEC and SPEC.loader
control = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = control
SPEC.loader.exec_module(control)


SOURCE = "3e7ab2b101fc5f7d102a640ae2b74c60c0146426"
RELEASE = "6.18.34+rpt-rpi-v8"
MODEL = "Raspberry Pi Zero 2 W Rev 1.0"


def write(path: Path, data: bytes) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {
        "path": path.name,
        "role": "fixture",
        "size": len(data),
        "sha256": control.sha256_file(path),
    }


def fixture(root: Path) -> control.Paths:
    artifact = root / "artifact"
    boot = root / "boot"
    accepted = root / "accepted-live"
    state = root / "state"
    backup = root / "backup"
    model_path = root / "model"
    release_path = root / "release"
    model_path.write_bytes((MODEL + "\x00").encode())
    release_path.write_text(RELEASE + "\n", encoding="utf-8")

    normal_data = {
        "config": ("config.txt", b"normal-config\n", "normal_config"),
        "cmdline": ("cmdline.txt", b"root=fixture\n", "normal_cmdline"),
        "kernel": ("kernel8.img", b"normal-kernel", "normal_kernel"),
        "initramfs": ("initramfs8", b"normal-initramfs", "normal_initramfs"),
    }
    normal = {}
    for key, (name, data, role) in normal_data.items():
        record = write(boot / name, data)
        record["role"] = role
        normal[key] = record

    boot_payload = {
        "tryboot.txt": (b"enabled-config\n", "tryboot_config"),
        "cmdline-hidloom-e1.txt": (b"root=fixture hidloom.early=e1\n", "alternate_cmdline"),
        "kernel8-hidloom-e3.img": (b"alternate-kernel", "alternate_kernel"),
        "hidloom-e3.img": (b"alternate-initramfs", "alternate_initramfs"),
    }
    boot_records = []
    for name, (data, role) in boot_payload.items():
        record = write(artifact / "boot" / name, data)
        record["role"] = role
        boot_records.append(record)
    accepted_record = write(artifact / "accepted" / control.ACCEPTED_NAME, b'{"schema":"accepted"}\n')
    accepted_record["role"] = "accepted_e1_manifest"
    receipt = {
        "schema": control.RECEIPT_SCHEMA,
        "status": "installed-disabled",
        "source": SOURCE,
        "kernel_release": RELEASE,
        "model": MODEL,
        "placement_sha256": "a" * 64,
        "normal_boot_inputs": normal,
        "installed": {
            "boot_files": sorted(boot_records, key=lambda item: item["path"]),
            "accepted_manifest": accepted_record,
        },
        "activation": {
            "default_boot_modified": False,
            "one_shot_requested": False,
            "reboot_requested": False,
            "tryboot_published_last": True,
        },
    }
    (artifact / "receipt.json").write_bytes(control.canonical_bytes(receipt))
    control.build_manifest(artifact, artifact / control.MANIFEST_NAME)
    return control.Paths(artifact, boot, accepted, state, backup, model_path, release_path)


def main() -> None:
    old = os.environ.get("HIDLOOM_EARLY_BOOT_TEST_ROOT")
    os.environ["HIDLOOM_EARLY_BOOT_TEST_ROOT"] = "1"
    try:
        with tempfile.TemporaryDirectory() as directory:
            paths = fixture(Path(directory))
            verified = control.command_verify(paths, live=True)
            assert verified["live_verified"] is True
            assert control.command_status(paths)["mode"] == "disabled"

            try:
                control.command_enable(paths, "0" * 40)
            except control.ControlError as exc:
                assert "confirm-source" in str(exc)
            else:
                raise AssertionError("wrong source confirmation was accepted")

            enabled = control.command_enable(paths, SOURCE)
            assert enabled["mode"] == "enabled"
            assert (paths.boot_root / "config.txt").read_bytes() == b"enabled-config\n"
            state = control.load_state(paths)
            assert state and all(state["created"].values())

            disabled = control.command_disable(paths, "test")
            assert disabled["mode"] == "disabled"
            assert disabled["restored"] is True
            assert (paths.boot_root / "config.txt").read_bytes() == b"normal-config\n"

            one_shot = control.command_try_once(paths, SOURCE, False)
            assert one_shot["one_shot_requested"] is True
            assert one_shot["mode"] == "disabled"

            control.command_enable(paths, SOURCE)
            assert control.command_status(paths)["one_shot_requested"] is False
            guard = control.command_kernel_guard(paths, "different-kernel")
            assert guard["action"] == "disabled"
            assert control.command_status(paths)["mode"] == "disabled"

            rollback = control.command_rollback(paths)
            assert rollback["mode"] == "disabled"
            assert len(rollback["removed"]) == 5
            assert (paths.boot_root / "config.txt").read_bytes() == b"normal-config\n"

        with tempfile.TemporaryDirectory() as directory:
            paths = fixture(Path(directory))
            control.command_enable(paths, SOURCE)
            (paths.boot_root / "config.txt").write_text("drift\n", encoding="utf-8")
            try:
                control.command_disable(paths, "test-drift")
            except control.ControlError as exc:
                assert "neither pinned enabled" in str(exc)
            else:
                raise AssertionError("unknown config drift was overwritten")

        with tempfile.TemporaryDirectory() as directory:
            paths = fixture(Path(directory))
            manifest = control.load_manifest(paths)
            target = paths.artifact_root / "boot" / manifest["boot_files"][0]["path"]
            target.write_bytes(b"tampered")
            try:
                control.command_verify(paths, live=False)
            except control.ControlError as exc:
                assert "differs from the pinned artifact" in str(exc)
            else:
                raise AssertionError("tampered artifact was accepted")

        with tempfile.TemporaryDirectory() as directory:
            paths = fixture(Path(directory))
            original_disk_usage = control.shutil.disk_usage
            control.shutil.disk_usage = lambda _path: type("Usage", (), {"free": 0})()
            try:
                control.command_enable(paths, SOURCE)
            except control.ControlError as exc:
                assert "insufficient free space" in str(exc)
                assert not (paths.boot_root / "tryboot.txt").exists()
                assert not control.state_path(paths).exists()
            else:
                raise AssertionError("insufficient free space was accepted")
            finally:
                control.shutil.disk_usage = original_disk_usage

        with tempfile.TemporaryDirectory() as directory:
            paths = fixture(Path(directory))
            (paths.boot_root / "config.txt").write_text("fresh-drift\n", encoding="utf-8")
            try:
                control.command_enable(paths, SOURCE)
            except control.ControlError as exc:
                assert "normal config" in str(exc)
                assert not (paths.boot_root / "tryboot.txt").exists()
                assert not control.state_path(paths).exists()
            else:
                raise AssertionError("fresh config drift was accepted")

        with tempfile.TemporaryDirectory() as directory:
            paths = fixture(Path(directory))
            manifest = control.load_manifest(paths)
            for record in manifest["boot_files"]:
                source = paths.artifact_root / "boot" / record["path"]
                (paths.boot_root / record["path"]).write_bytes(source.read_bytes())
            accepted = manifest["accepted_manifest"]
            paths.accepted_root.mkdir(parents=True)
            (paths.accepted_root / accepted["path"]).write_bytes(
                (paths.artifact_root / "accepted" / accepted["path"]).read_bytes()
            )
            original_disk_usage = control.shutil.disk_usage
            control.shutil.disk_usage = lambda _path: type("Usage", (), {"free": 0})()
            try:
                control.command_enable(paths, SOURCE)
            except control.ControlError as exc:
                assert "insufficient free space" in str(exc)
                assert not control.state_path(paths).exists()
            else:
                raise AssertionError("preexisting payload bypassed the boot reserve")
            finally:
                control.shutil.disk_usage = original_disk_usage
    finally:
        if old is None:
            os.environ.pop("HIDLOOM_EARLY_BOOT_TEST_ROOT", None)
        else:
            os.environ["HIDLOOM_EARLY_BOOT_TEST_ROOT"] = old
    print("ok: Raspberry Pi OS early boot package controller")


if __name__ == "__main__":
    main()
