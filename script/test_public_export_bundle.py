#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BINARIES = (
    "build/rpi-rust/aarch64-unknown-linux-musl/bin/hidloom-hidd",
    "build/rpi-rust/aarch64-unknown-linux-musl/bin/hidloom-uidd",
    "build/rpi-rust/aarch64-unknown-linux-musl/bin/hidloom-outputd",
    "build/rpi-rust/aarch64-unknown-linux-musl/bin/hidloom-logicd-core",
    "build/rpi-matrixd/aarch64-static/bin/matrixd",
    "build/rpi-usb-gadget-fast/aarch64-static/bin/hidloom-usb-gadget-fast",
    "build/rpi-hidloom-send/aarch64-static/bin/hidloom-key",
    "build/rpi-hidloom-send/aarch64-static/bin/hidloom-keytext",
    "build/rpi-hidloom-send/aarch64-static/bin/hidloom-oled",
    "build/rpi-hidloom-send/aarch64-static/bin/hidloom-notify",
    "build/rpi-hidloom-send/aarch64-static/bin/hidloom-ctrl",
)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        export = workspace / "export"
        packages = workspace / "packages"
        unpacked = workspace / "unpacked"
        subprocess.run(
            ["python3", str(ROOT / "tools/public_export.py"), str(export), "--draft"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        report = json.loads((export / "PUBLIC_EXPORT_REPORT.json").read_text(encoding="utf-8"))
        subprocess.run(["git", "init", "-q"], cwd=export, check=True)
        subprocess.run(["git", "config", "user.name", "HIDloom Test"], cwd=export, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@localhost"], cwd=export, check=True
        )
        subprocess.run(["git", "add", "-f", "."], cwd=export, check=True)
        subprocess.run(["git", "commit", "-qm", "public export fixture"], cwd=export, check=True)
        assert subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=export, text=True
        ).strip() != report["source_provenance"]["base_commit"]
        for relative in BINARIES:
            binary = export / relative
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            binary.chmod(0o755)
        unlisted = export / "build/unlisted-build-output.bin"
        unlisted.write_bytes(b"must not enter the package source payload")
        environment = os.environ.copy()
        environment.update({"MATRIX_CC": "true", "HIDLOOM_SEND_CC": "true"})
        subprocess.run(
            [
                str(export / "tools/package/build_release_bundle.sh"),
                "--no-build",
                "--out-dir",
                str(packages),
            ],
            cwd=export,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        archives = list(packages.glob("*.tar.zst"))
        assert len(archives) == 1, archives
        unpacked.mkdir()
        subprocess.run(
            ["tar", "--zstd", "-xf", str(archives[0]), "-C", str(unpacked)],
            check=True,
        )
        manifest = json.loads((unpacked / "build/package-manifest.json").read_text())
        assert manifest["source_mode"] == "public-export"
        source_commit = report["source_provenance"]["base_commit"]
        assert manifest["git_sha"] == source_commit[:12]
        assert manifest["git_describe"] == source_commit
        assert len(manifest["public_export_manifest_sha256"]) == 64
        assert not (unpacked / "build/unlisted-build-output.bin").exists()

        core_result = subprocess.run(
            [
                str(export / "tools/package/build_deb_package.sh"),
                "--bundle",
                str(archives[0]),
                "--out-dir",
                str(packages),
                "--package-id",
                "hidloom-core",
            ],
            cwd=export,
            check=False,
            capture_output=True,
            text=True,
        )
        assert core_result.returncode == 0, core_result.stderr
        profile_result = subprocess.run(
            [
                str(export / "tools/package/build_device_profile_deb.sh"),
                "--bundle",
                str(archives[0]),
                "--out-dir",
                str(packages),
                "--profile",
                "keyboard-ver1",
            ],
            cwd=export,
            check=False,
            capture_output=True,
            text=True,
        )
        assert profile_result.returncode == 0, profile_result.stderr
        core_packages = list(packages.glob("hidloom-core_*_arm64.deb"))
        profile_packages = list(packages.glob("hidloom-profile-keyboard-ver1_*_arm64.deb"))
        assert len(core_packages) == 1, core_packages
        assert len(profile_packages) == 1, profile_packages
        core_info = subprocess.check_output(["dpkg-deb", "--field", str(core_packages[0])], text=True)
        profile_info = subprocess.check_output(
            ["dpkg-deb", "--field", str(profile_packages[0])], text=True
        )
        assert "Package: hidloom-core" in core_info
        assert "Architecture: arm64" in core_info
        assert "Package: hidloom-profile-keyboard-ver1" in profile_info
        assert "Depends: hidloom-core (= " in profile_info
        subprocess.run(
            ["sh", "-c", "sha256sum -c ./*.sha256"],
            cwd=packages,
            check=True,
            capture_output=True,
            text=True,
        )
        provenance = workspace / "PUBLIC_BUILD_PROVENANCE.json"
        collect = subprocess.run(
            [
                "python3",
                str(export / "tools/public_build_provenance.py"),
                "collect",
                "--source",
                str(export),
                "--mode",
                "package",
                "--package-dir",
                str(packages),
                "--output",
                str(provenance),
            ],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert collect.returncode == 0, collect.stdout + collect.stderr
        evidence = json.loads(provenance.read_text(encoding="utf-8"))
        assert evidence["ready"] is True
        assert evidence["source"]["source_commit"] == source_commit
        assert evidence["source"]["source_tree"] == report["source_provenance"]["base_tree"]
        assert evidence["source"]["source_snapshot_sha256"] == report[
            "source_provenance"
        ]["selected_snapshot_sha256"]
        assert evidence["source"]["documentation_audit"]["broken_links"] == 0
        assert evidence["source"]["documentation_audit"]["orphaned_documents"] == 0
        if (ROOT / "docs/CURRENT_STATUS.md").is_file():
            assert evidence["source"]["documentation_audit"]["removed_private_navigation_lines"] > 0
        else:
            assert evidence["source"]["documentation_audit"]["removed_private_navigation_lines"] == 0
        assert evidence["packages"]["source_mode"] == "public-export"
        assert evidence["packages"]["profile_id"] == "keyboard-ver1"
        assert len(evidence["packages"]["artifacts"]) == 6
        subprocess.run(
            [
                "python3",
                str(export / "tools/public_build_provenance.py"),
                "verify",
                str(provenance),
                "--source",
                str(export),
                "--package-dir",
                str(packages),
            ],
            cwd=export,
            check=True,
            capture_output=True,
            text=True,
        )

        touch_result = subprocess.run(
            [
                str(export / "tools/package/build_device_profile_deb.sh"),
                "--bundle",
                str(archives[0]),
                "--out-dir",
                str(packages),
                "--profile",
                "touch-waveshare-8.8",
            ],
            cwd=export,
            check=False,
            capture_output=True,
            text=True,
        )
        assert touch_result.returncode == 0, touch_result.stderr
        touch_provenance = workspace / "PUBLIC_TOUCH_BUILD_PROVENANCE.json"
        subprocess.run(
            [
                "python3",
                str(export / "tools/public_build_provenance.py"),
                "collect",
                "--source",
                str(export),
                "--mode",
                "package",
                "--package-dir",
                str(packages),
                "--profile",
                "touch-waveshare-8.8",
                "--output",
                str(touch_provenance),
            ],
            cwd=export,
            check=True,
            capture_output=True,
            text=True,
        )
        touch_evidence = json.loads(touch_provenance.read_text(encoding="utf-8"))
        assert touch_evidence["packages"]["profile_id"] == "touch-waveshare-8.8"
        assert touch_evidence["packages"]["metadata"]["profile"]["package"] == (
            "hidloom-profile-touch-waveshare-8.8"
        )
        subprocess.run(
            [
                "python3",
                str(export / "tools/public_build_provenance.py"),
                "verify",
                str(touch_provenance),
                "--source",
                str(export),
                "--package-dir",
                str(packages),
                "--profile",
                "touch-waveshare-8.8",
            ],
            cwd=export,
            check=True,
            capture_output=True,
            text=True,
        )

    print("ok: public clone package build is manifest-bounded and provenance-verified")


if __name__ == "__main__":
    main()
