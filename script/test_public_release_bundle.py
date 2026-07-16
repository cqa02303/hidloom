#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "script"))

from test_buildroot_compliance_bundle import make_compliance_fixture  # noqa: E402


def make_package(path: Path, package: str, version: str, depends: str | None = None) -> None:
    root = path.parent / f"root-{package}"
    control = root / "DEBIAN" / "control"
    control.parent.mkdir(parents=True)
    lines = [
        f"Package: {package}",
        f"Version: {version}",
        "Architecture: arm64",
        "Maintainer: HIDloom Test <test@localhost>",
        "Description: HIDloom release bundle fixture",
    ]
    if depends:
        lines.insert(4, f"Depends: {depends}")
    control.write_text("\n".join(lines) + "\n", encoding="utf-8")
    subprocess.run(["dpkg-deb", "--build", str(root), str(path)], check=True, capture_output=True)


def write_export_json(export: Path, relative: str, payload: dict[str, object]) -> None:
    content = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    (export / relative).write_bytes(content)
    manifest_path = export / "PUBLIC_EXPORT_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(item for item in manifest["files"] if item["path"] == relative)
    entry["size"] = len(content)
    entry["sha256"] = hashlib.sha256(content).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        export = workspace / "export"
        packages = workspace / "packages"
        release = workspace / "release"
        release_again = workspace / "release-again"
        subprocess.run(
            ["python3", str(ROOT / "tools/public_export.py"), str(export), "--draft"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        (export / "build" / "unlisted-build-output.bin").write_bytes(b"must not enter source archive")
        packages.mkdir()
        report = json.loads((export / "PUBLIC_EXPORT_REPORT.json").read_text(encoding="utf-8"))
        source_commit = report["source_provenance"]["base_commit"]
        package_version = f"0.0.1+git{source_commit[:12]}"
        core = packages / f"hidloom-core_{package_version}_arm64.deb"
        profile = packages / f"hidloom-profile-keyboard-ver1_{package_version}_arm64.deb"
        make_package(core, "hidloom-core", package_version)
        make_package(
            profile,
            "hidloom-profile-keyboard-ver1",
            package_version,
            f"hidloom-core (= {package_version})",
        )
        image = workspace / "sdcard.img"
        image.write_bytes(b"HIDloom M6 image fixture\n" * 32)
        compliance = make_compliance_fixture(workspace / "compliance", export)
        compliance_result = json.loads(
            subprocess.check_output(
                [
                    "python3",
                    str(export / "tools" / "buildroot_compliance_bundle.py"),
                    "verify",
                    str(compliance),
                    "--json",
                ],
                cwd=export,
                text=True,
            )
        )
        buildroot_source_path = export / "config" / "buildroot-source.json"
        buildroot_source = json.loads(buildroot_source_path.read_text(encoding="utf-8"))
        buildroot_source["commit"] = compliance_result["buildroot_commit"]
        write_export_json(export, "config/buildroot-source.json", buildroot_source)
        toolchain_path = export / "config/buildroot-toolchain-evidence.json"
        toolchain = json.loads(toolchain_path.read_text(encoding="utf-8"))
        toolchain["version"] = compliance_result["bootlin_version"]
        write_export_json(export, "config/buildroot-toolchain-evidence.json", toolchain)
        legal_path = export / "docs/ops/buildroot-m6-legal-summary.json"
        legal = json.loads(legal_path.read_text(encoding="utf-8"))
        legal["buildroot_source"]["commit"] = compliance_result["buildroot_commit"]
        legal["toolchain_evidence"]["version"] = compliance_result["bootlin_version"]
        write_export_json(export, "docs/ops/buildroot-m6-legal-summary.json", legal)

        command = [
            "python3",
            str(export / "tools/public_release_bundle.py"),
            "--source",
            str(export),
            "--image",
            str(image),
            "--allow-unverified-image",
            "--core-package",
            str(core),
            "--profile-package",
            str(profile),
            "--compliance-bundle",
            str(compliance),
            "--output",
            str(release),
            "--version",
            "0.1.0-test",
        ]
        created = subprocess.run(command, cwd=export, capture_output=True, text=True)
        assert created.returncode == 0, created.stdout + created.stderr
        manifest = json.loads((release / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
        assert manifest["schema"] == "hidloom.public-release-bundle.v2"
        assert manifest["version"] == "0.1.0-test"
        assert manifest["hardware_smoke"]["status"] == "pending"
        assert manifest["hardware_smoke"]["device"] == "keyboard-ver1"
        assert manifest["network_boundary"] == {"offline": True, "wifi": False, "httpd": False}
        assert manifest["buildroot"]["verification"] == "fixture-unverified"
        assert manifest["buildroot"]["compliance"]["schema"] == (
            "hidloom.buildroot-compliance-bundle.v1"
        )
        assert manifest["buildroot"]["compliance"]["binary_release_ready"] is True
        assert manifest["buildroot"]["compliance"]["resolved_release_blockers"] == [
            "bootlin-toolchain-compliance-not-bundled",
            "buildroot-source-not-bundled",
        ]
        assert {item["role"] for item in manifest["assets"]} >= {
            "corresponding-source",
            "buildroot-m6-raw-image",
            "buildroot-m6-zstd-image",
            "raspberry-pi-os-core-package",
            "raspberry-pi-os-keyboard-profile-package",
            "buildroot-compliance-source",
            "compliance",
        }
        notes = (release / "RELEASE_NOTES.md").read_text(encoding="utf-8")
        for phrase in (
            "Choose an Installation Method",
            "Raspberry Pi OS package",
            "Buildroot M6 image",
            "same apt transaction",
            "sha256sum -c SHA256SUMS",
            f"sudo apt-get install -y ./{core.name} ./{profile.name}",
            "sudo hidloom-profile keyboard-ver1 --apply --backup --restart",
        ):
            assert phrase in notes, phrase
        source_archive = next(release.glob("*-source.tar.zst"))
        archive_files = subprocess.check_output(
            ["tar", "--zstd", "-tf", str(source_archive)], text=True
        ).splitlines()
        assert any(name.endswith("/tools/public_release_bundle.py") for name in archive_files)
        assert not any("unlisted-build-output.bin" in name for name in archive_files)
        subprocess.run(
            ["python3", str(export / "tools/public_release_bundle.py"), "--verify", str(release)],
            cwd=export,
            check=True,
            capture_output=True,
            text=True,
        )
        failed = subprocess.run(
            [
                "python3",
                str(export / "tools/public_release_bundle.py"),
                "--verify",
                str(release),
                "--require-hardware-pass",
            ],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert failed.returncode != 0
        assert "hardware smoke is not recorded as pass" in failed.stderr

        mismatched_toolchain = dict(toolchain)
        mismatched_toolchain["version"] = "mismatched-toolchain"
        write_export_json(
            export,
            "config/buildroot-toolchain-evidence.json",
            mismatched_toolchain,
        )
        mismatched_command = list(command)
        mismatched_command[mismatched_command.index(str(release))] = str(
            workspace / "mismatched-toolchain"
        )
        mismatched = subprocess.run(
            mismatched_command,
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert mismatched.returncode != 0
        assert "compliance toolchain does not match" in mismatched.stderr
        write_export_json(export, "config/buildroot-toolchain-evidence.json", toolchain)

        invalid_pass = list(command)
        invalid_pass.extend(["--hardware-smoke-status", "pass"])
        invalid_pass[invalid_pass.index(str(release))] = str(workspace / "invalid-pass")
        invalid = subprocess.run(
            invalid_pass,
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert invalid.returncode != 0
        assert "hardware pass requires a positive usable-keyboard measurement" in invalid.stderr

        repeat_command = list(command)
        repeat_command[repeat_command.index(str(release))] = str(release_again)
        subprocess.run(repeat_command, cwd=export, check=True, capture_output=True, text=True)
        for pattern in ("*-source.tar.zst", "*-buildroot-m6.img.zst"):
            assert next(release.glob(pattern)).read_bytes() == next(release_again.glob(pattern)).read_bytes()

        with (release / "RELEASE_NOTES.md").open("a", encoding="utf-8") as stream:
            stream.write("tampered\n")
        tampered = subprocess.run(
            ["python3", str(export / "tools/public_release_bundle.py"), "--verify", str(release)],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert tampered.returncode != 0
        assert "checksum mismatch" in tampered.stderr

    print("ok: public release candidate bundle and hardware gate")


if __name__ == "__main__":
    main()
