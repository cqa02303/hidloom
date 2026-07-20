#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
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
    root.chmod(0o755)
    control.parent.chmod(0o755)
    control.chmod(0o644)
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


def refresh_checksum(directory: Path, name: str) -> None:
    checksum = directory / "SHA256SUMS"
    digest = hashlib.sha256((directory / name).read_bytes()).hexdigest()
    lines = checksum.read_text(encoding="utf-8").splitlines()
    checksum.write_text(
        "\n".join(
            f"{digest}  {name}" if line.endswith(f"  {name}") else line for line in lines
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    wrapper = ROOT / "tools/package/build_zero2w_keyboard_release.sh"
    assert wrapper.is_file() and wrapper.stat().st_mode & 0o111
    syntax = subprocess.run(["sh", "-n", str(wrapper)], capture_output=True, text=True)
    assert syntax.returncode == 0, syntax.stderr
    help_result = subprocess.run([str(wrapper), "--help"], capture_output=True, text=True)
    assert help_result.returncode == 0, help_result.stderr
    for phrase in (
        "Raspberry Pi Zero 2 W",
        "--buildroot-output",
        "--provenance",
        "--touch-package-dir",
        "--touch-provenance",
        "--hardware-smoke-status",
        "--touch-hardware-smoke-status",
        "--touch-ready-seconds",
        "never creates tags",
    ):
        assert phrase in help_result.stdout, phrase
    publisher = ROOT / "tools/package/publish_public_release_bundle.py"
    github_verifier = ROOT / "tools/package/verify_github_public_release_bundle.py"
    for helper, phrases in (
        (publisher, ("guarded draft GitHub Release", "--output-plan", "--execute")),
        (github_verifier, ("deeply verify", "--bundle", "--tag")),
    ):
        assert helper.is_file() and helper.stat().st_mode & 0o111
        help_result = subprocess.run([str(helper), "--help"], capture_output=True, text=True)
        assert help_result.returncode == 0, help_result.stderr
        for phrase in phrases:
            assert phrase in help_result.stdout, phrase
    module_spec = importlib.util.spec_from_file_location("publish_public_release_bundle", publisher)
    assert module_spec and module_spec.loader
    publisher_module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(publisher_module)
    publisher_module.shutil.which = lambda command: f"/fixture/{command}"

    def fake_online_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if command[:3] == ["gh", "repo", "view"]:
            output = json.dumps(
                {"nameWithOwner": "cqa02303/hidloom", "visibility": "PUBLIC"}
            )
            return subprocess.CompletedProcess(command, 0, output, "")
        if command[:2] == ["gh", "api"] and "/commits/" in command[2]:
            return subprocess.CompletedProcess(command, 0, "a" * 40 + "\n", "")
        if command[:3] == ["gh", "release", "view"]:
            return subprocess.CompletedProcess(command, 1, "", "not found")
        if command[:2] == ["gh", "api"] and "/git/ref/tags/" in command[2]:
            return subprocess.CompletedProcess(command, 0, "{}\n", "")
        raise AssertionError(command)

    publisher_module.run = fake_online_run
    try:
        publisher_module.online_preflight(
            {
                "repository": "cqa02303/hidloom",
                "source_commit": "a" * 40,
                "tag": "vfixture",
            }
        )
    except SystemExit as error:
        assert str(error) == "Git tag already exists: vfixture"
    else:
        raise AssertionError("existing Git tag must block draft creation")

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        export = workspace / "export"
        packages = workspace / "packages"
        release = workspace / "release"
        release_again = workspace / "release-again"
        release_with_provenance = workspace / "release-with-provenance"
        release_with_touch = workspace / "release-with-touch"
        subprocess.run(
            ["python3", str(ROOT / "tools/public_export.py"), str(export), "--draft"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        (export / "build").mkdir(exist_ok=True)
        (export / "build" / "unlisted-build-output.bin").write_bytes(b"must not enter source archive")
        packages.mkdir()
        report = json.loads((export / "PUBLIC_EXPORT_REPORT.json").read_text(encoding="utf-8"))
        source_commit = report["source_provenance"]["base_commit"]
        package_version = f"0.0.1+git{source_commit[:12]}"
        core = packages / f"hidloom-core_{package_version}_arm64.deb"
        profile = packages / f"hidloom-profile-keyboard-ver1_{package_version}_arm64.deb"
        touch_profile = (
            packages
            / f"hidloom-profile-touch-waveshare-8.8_{package_version}_arm64.deb"
        )
        make_package(core, "hidloom-core", package_version)
        make_package(
            profile,
            "hidloom-profile-keyboard-ver1",
            package_version,
            f"hidloom-core (= {package_version})",
        )
        make_package(
            touch_profile,
            "hidloom-profile-touch-waveshare-8.8",
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
        assert manifest["schema"] == "hidloom.public-release-bundle.v4"
        assert manifest["version"] == "0.1.0-test"
        assert manifest["hardware_smoke"]["status"] == "pending"
        assert manifest["hardware_smoke"]["device"] == "keyboard-ver1"
        assert manifest["touch_hardware_smoke"] is None
        assert manifest["network_boundary"] == {"offline": True, "wifi": False, "httpd": False}
        assert manifest["publication"] == {
            "ready": False,
            "blockers": [
                "public-usb-identity-not-assigned",
                "public-build-provenance-missing",
            ],
            "usb_assignment_status": "candidate-unassigned",
            "build_provenance": None,
            "touch_build_provenance": None,
        }
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
            "quickstart",
            "compliance",
        }
        notes = (release / "RELEASE_NOTES.md").read_text(encoding="utf-8")
        for phrase in (
            "Choose an Installation Method",
            "Raspberry Pi OS package",
            "Buildroot M6 image",
            "same apt transaction",
            "sha256sum -c SHA256SUMS",
            "QUICKSTART.md",
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
        assert "keyboard hardware smoke is not recorded as pass" in failed.stderr
        publication_failed = subprocess.run(
            [
                "python3",
                str(export / "tools/public_release_bundle.py"),
                "--verify",
                str(release),
                "--require-publication-ready",
            ],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert publication_failed.returncode != 0
        assert "public-usb-identity-not-assigned" in publication_failed.stderr

        build_provenance = workspace / "PUBLIC_BUILD_PROVENANCE.json"
        build_provenance.write_text(
            json.dumps(
                {
                    "schema": "hidloom.public-build-provenance.v2",
                    "ready": True,
                    "mode": "all",
                    "source": {"source_commit": source_commit},
                    "packages": {
                        "profile_id": "keyboard-ver1",
                        "version": package_version,
                        "artifacts": [
                            {
                                "role": "raspberry-pi-os-core-package",
                                "name": core.name,
                                "size": core.stat().st_size,
                                "sha256": hashlib.sha256(core.read_bytes()).hexdigest(),
                            },
                            {
                                "role": "raspberry-pi-os-device-profile-package",
                                "name": profile.name,
                                "size": profile.stat().st_size,
                                "sha256": hashlib.sha256(profile.read_bytes()).hexdigest(),
                            },
                        ],
                    },
                    "buildroot": {
                        "ready": True,
                        "mode": "image",
                        "image": {
                            "size": image.stat().st_size,
                            "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                        },
                    },
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        provenance_command = list(command)
        provenance_command[provenance_command.index(str(release))] = str(
            release_with_provenance
        )
        provenance_command.extend(["--build-provenance", str(build_provenance)])
        provenance_created = subprocess.run(
            provenance_command,
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert provenance_created.returncode == 0, (
            provenance_created.stdout + provenance_created.stderr
        )
        provenance_manifest = json.loads(
            (release_with_provenance / "RELEASE_MANIFEST.json").read_text(encoding="utf-8")
        )
        assert provenance_manifest["publication"]["blockers"] == [
            "public-usb-identity-not-assigned"
        ]
        assert provenance_manifest["publication"]["build_provenance"]["path"] == (
            "PUBLIC_BUILD_PROVENANCE.json"
        )
        assert "public-build-provenance" in {
            item["role"] for item in provenance_manifest["assets"]
        }

        touch_build_provenance = workspace / "PUBLIC_BUILD_PROVENANCE_TOUCH.json"
        touch_build_provenance.write_text(
            json.dumps(
                {
                    "schema": "hidloom.public-build-provenance.v2",
                    "ready": True,
                    "mode": "package",
                    "source": {"source_commit": source_commit},
                    "packages": {
                        "profile_id": "touch-waveshare-8.8",
                        "version": package_version,
                        "artifacts": [
                            {
                                "role": "raspberry-pi-os-device-profile-package",
                                "name": touch_profile.name,
                                "size": touch_profile.stat().st_size,
                                "sha256": hashlib.sha256(touch_profile.read_bytes()).hexdigest(),
                            }
                        ],
                    },
                    "buildroot": None,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        touch_command = list(provenance_command)
        touch_command[touch_command.index(str(release_with_provenance))] = str(
            release_with_touch
        )
        touch_command.extend(
            [
                "--touch-profile-package",
                str(touch_profile),
                "--touch-build-provenance",
                str(touch_build_provenance),
                "--hardware-smoke-status",
                "pass",
                "--usable-keyboard-seconds",
                "6.0",
            ]
        )
        touch_created = subprocess.run(
            touch_command,
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert touch_created.returncode == 0, touch_created.stdout + touch_created.stderr
        touch_manifest = json.loads(
            (release_with_touch / "RELEASE_MANIFEST.json").read_text(encoding="utf-8")
        )
        assert touch_manifest["packages"]["touch_profile"] == "touch-waveshare-8.8"
        assert touch_manifest["hardware_smoke"]["status"] == "pass"
        assert touch_manifest["touch_hardware_smoke"] == {
            "status": "pending",
            "device": "touch-waveshare-8.8",
            "touch_ready_seconds": None,
        }
        assert touch_manifest["publication"]["blockers"] == [
            "public-usb-identity-not-assigned"
        ]
        touch_roles = {item["role"] for item in touch_manifest["assets"]}
        assert "raspberry-pi-os-touch-profile-package" in touch_roles
        assert "touch-public-build-provenance" in touch_roles
        touch_notes = (release_with_touch / "RELEASE_NOTES.md").read_text(encoding="utf-8")
        assert "touch-waveshare-8.8 --apply --backup --restart" in touch_notes
        assert "Touch hardware smoke: `pending`" in touch_notes
        touch_hardware_failed = subprocess.run(
            [
                "python3",
                str(export / "tools/public_release_bundle.py"),
                "--verify",
                str(release_with_touch),
                "--require-hardware-pass",
            ],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert touch_hardware_failed.returncode != 0
        assert "touch hardware smoke is not recorded as pass" in touch_hardware_failed.stderr

        local_verified = subprocess.run(
            [
                str(export / "tools/package/verify_github_public_release_bundle.py"),
                "--bundle",
                str(release_with_touch),
            ],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert local_verified.returncode == 0, local_verified.stdout + local_verified.stderr
        local_result = json.loads(local_verified.stdout)
        assert local_result["asset_count"] == len(list(release_with_touch.iterdir()))
        assert local_result["hardware_smoke"]["status"] == "pass"
        assert local_result["touch_hardware_smoke"] == {
            "status": "pending",
            "device": "touch-waveshare-8.8",
            "touch_ready_seconds": None,
        }

        publish_plan = workspace / "PUBLIC_RELEASE_PUBLISH_PLAN.json"
        planned = subprocess.run(
            [
                str(export / "tools/package/publish_public_release_bundle.py"),
                "--bundle",
                str(release_with_touch),
                "--output-plan",
                str(publish_plan),
            ],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert planned.returncode == 0, planned.stdout + planned.stderr
        plan = json.loads(publish_plan.read_text(encoding="utf-8"))
        assert not plan["ready"]
        assert "publication:public-usb-identity-not-assigned" in plan["blockers"]
        assert "hardware-smoke-not-passed" not in plan["blockers"]
        assert "touch-hardware-smoke-not-passed" in plan["blockers"]
        assert "dry-run only" in planned.stdout
        blocked_execute = subprocess.run(
            [
                str(export / "tools/package/publish_public_release_bundle.py"),
                "--bundle",
                str(release_with_touch),
                "--execute",
                "--confirm",
                plan["confirmation"],
            ],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert blocked_execute.returncode != 0
        assert "release blockers remain" in blocked_execute.stderr

        publishable = workspace / "publishable-release"
        shutil.copytree(release_with_touch, publishable)
        publishable_manifest_path = publishable / "RELEASE_MANIFEST.json"
        publishable_manifest = json.loads(publishable_manifest_path.read_text(encoding="utf-8"))
        publishable_manifest["publication"]["ready"] = True
        publishable_manifest["publication"]["blockers"] = []
        publishable_manifest["hardware_smoke"] = {
            "status": "pass",
            "device": "keyboard-ver1-fixture",
            "usable_keyboard_seconds": 6.0,
        }
        publishable_manifest["touch_hardware_smoke"] = {
            "status": "pass",
            "device": "touch-waveshare-8.8-fixture",
            "touch_ready_seconds": 77.0,
        }
        publishable_manifest_path.write_text(
            json.dumps(publishable_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        refresh_checksum(publishable, "RELEASE_MANIFEST.json")
        fake_bin = workspace / "fake-bin"
        fake_bin.mkdir()
        fake_gh = fake_bin / "gh"
        fake_gh.write_text(
            """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shutil
import sys

arguments = sys.argv[1:]
source = Path(os.environ["HIDLOOM_FAKE_RELEASE_DIR"])
if arguments[:2] == ["release", "view"]:
    print(json.dumps({
        "assets": [{"name": path.name} for path in sorted(source.iterdir()) if path.is_file()],
        "isDraft": True,
        "isPrerelease": True,
        "tagName": arguments[2],
        "targetCommitish": "fixture",
    }))
elif arguments[:2] == ["release", "download"]:
    destination = Path(arguments[arguments.index("--dir") + 1])
    destination.mkdir(parents=True, exist_ok=True)
    for path in source.iterdir():
        if path.is_file():
            shutil.copy2(path, destination / path.name)
else:
    raise SystemExit(f"unsupported fake gh command: {arguments}")
""",
            encoding="utf-8",
        )
        fake_gh.chmod(0o755)
        downloaded = workspace / "downloaded-release"
        environment = dict(os.environ)
        environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
        environment["HIDLOOM_FAKE_RELEASE_DIR"] = str(publishable)
        remote_verified = subprocess.run(
            [
                str(export / "tools/package/verify_github_public_release_bundle.py"),
                "--tag",
                "vfixture",
                "--repository",
                "cqa02303/hidloom",
                "--dir",
                str(downloaded),
            ],
            cwd=export,
            env=environment,
            capture_output=True,
            text=True,
        )
        assert remote_verified.returncode == 0, remote_verified.stdout + remote_verified.stderr
        remote_result = json.loads(remote_verified.stdout)
        assert remote_result["repository"] == "cqa02303/hidloom"
        assert remote_result["tag"] == "vfixture"
        assert remote_result["asset_count"] == len(list(publishable.iterdir()))
        assert remote_result["hardware_smoke"]["status"] == "pass"
        assert remote_result["touch_hardware_smoke"]["status"] == "pass"

        mismatched_provenance = json.loads(build_provenance.read_text(encoding="utf-8"))
        mismatched_provenance["buildroot"]["image"]["sha256"] = "0" * 64
        build_provenance.write_text(
            json.dumps(mismatched_provenance, indent=2) + "\n",
            encoding="utf-8",
        )
        mismatched_provenance_command = list(provenance_command)
        mismatched_provenance_command[
            mismatched_provenance_command.index(str(release_with_provenance))
        ] = str(workspace / "mismatched-provenance")
        mismatched_provenance_result = subprocess.run(
            mismatched_provenance_command,
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert mismatched_provenance_result.returncode != 0
        assert "does not match the keyboard/M6 artifacts" in mismatched_provenance_result.stderr

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

        invalid_touch_pass = list(touch_command)
        invalid_touch_pass.extend(["--touch-hardware-smoke-status", "pass"])
        invalid_touch_pass[invalid_touch_pass.index(str(release_with_touch))] = str(
            workspace / "invalid-touch-pass"
        )
        invalid_touch = subprocess.run(
            invalid_touch_pass,
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert invalid_touch.returncode != 0
        assert "touch hardware pass requires a positive touch-ready measurement" in (
            invalid_touch.stderr
        )

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
