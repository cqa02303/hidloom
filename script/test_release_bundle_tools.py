#!/usr/bin/env python3
"""Regression checks for cross-build host release bundle tooling."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "tools" / "package"
BUILD = PACKAGE_DIR / "build_release_bundle.sh"
BUILD_DEB = PACKAGE_DIR / "build_deb_package.sh"
BUILD_PROFILE_DEB = PACKAGE_DIR / "build_device_profile_deb.sh"
DEPLOY_DEB = PACKAGE_DIR / "deploy_deb_package.sh"
VERIFY_DEB = PACKAGE_DIR / "deploy_deb_verify.sh"
SWITCH_DEB_UNITS = PACKAGE_DIR / "switch_deb_systemd_units.sh"
DEPLOY_SWITCH_DEB_UNITS = PACKAGE_DIR / "deploy_deb_unit_switch.sh"
RELEASE_CANDIDATE_CHECK = PACKAGE_DIR / "release_candidate_check.sh"
PUBLISH_GITHUB_PRERELEASE = PACKAGE_DIR / "publish_github_prerelease.sh"
PUBLISH_PUBLIC_RELEASE_BUNDLE = PACKAGE_DIR / "publish_public_release_bundle.py"
VERIFY_GITHUB_RELEASE_ASSETS = PACKAGE_DIR / "verify_github_release_assets.sh"
VERIFY_GITHUB_PUBLIC_RELEASE_BUNDLE = PACKAGE_DIR / "verify_github_public_release_bundle.py"
CHECK_GITHUB_RELEASE_STABLE_READY = PACKAGE_DIR / "check_github_release_stable_ready.sh"
INSTALL_GITHUB_RELEASE_DEB = PACKAGE_DIR / "install_github_release_deb.sh"
DEPLOY_GITHUB_RELEASE_DEB = PACKAGE_DIR / "deploy_github_release_deb.sh"
APPLY = PACKAGE_DIR / "apply_release_bundle.sh"
DEPLOY = PACKAGE_DIR / "deploy_release_bundle.sh"
ROLLBACK = PACKAGE_DIR / "rollback_release_bundle.sh"
DEPLOY_ROLLBACK = PACKAGE_DIR / "deploy_release_rollback.sh"


def run_command(
    command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def write_executable(path: Path, magic: bytes = b"\x7fELFtest\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(magic)
    path.chmod(0o755)


def make_deb(path: Path, package: str, version: str, *, depends: str | None = None) -> None:
    root = path.parent / f"root-{package}"
    control = root / "DEBIAN" / "control"
    payload = root / "usr" / "share" / package / "fixture.txt"
    control.parent.mkdir(parents=True)
    payload.parent.mkdir(parents=True)
    fields = [
        f"Package: {package}",
        f"Version: {version}",
        "Section: utils",
        "Priority: optional",
        "Architecture: arm64",
        "Maintainer: HIDloom contributors",
        "Description: HIDloom release helper fixture",
    ]
    if depends:
        fields.insert(5, f"Depends: {depends}")
    control.write_text("\n".join(fields) + "\n", encoding="utf-8")
    payload.write_text("fixture\n", encoding="utf-8")
    for directory in (item for item in root.rglob("*") if item.is_dir()):
        directory.chmod(0o755)
    root.chmod(0o755)
    control.chmod(0o644)
    payload.chmod(0o644)
    built = run_command(["dpkg-deb", "--build", str(root), str(path)])
    assert built.returncode == 0, built.stdout + built.stderr


def main() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "build/*-release-publish-plan.json" in gitignore
    assert "build/*-release-verification.json" in gitignore

    for script in (
        BUILD,
        BUILD_DEB,
        BUILD_PROFILE_DEB,
        DEPLOY_DEB,
        VERIFY_DEB,
        SWITCH_DEB_UNITS,
        DEPLOY_SWITCH_DEB_UNITS,
        RELEASE_CANDIDATE_CHECK,
        PUBLISH_GITHUB_PRERELEASE,
        VERIFY_GITHUB_RELEASE_ASSETS,
        CHECK_GITHUB_RELEASE_STABLE_READY,
        INSTALL_GITHUB_RELEASE_DEB,
        DEPLOY_GITHUB_RELEASE_DEB,
        APPLY,
        DEPLOY,
        ROLLBACK,
        DEPLOY_ROLLBACK,
    ):
        assert script.exists(), script
        syntax = run_command(["sh", "-n", str(script)])
        assert syntax.returncode == 0, syntax.stderr
        help_result = run_command([str(script), "--help"])
        assert help_result.returncode == 0
        assert "usage:" in help_result.stdout

    for script in (PUBLISH_PUBLIC_RELEASE_BUNDLE, VERIFY_GITHUB_PUBLIC_RELEASE_BUNDLE):
        assert script.exists(), script
        compile(script.read_text(encoding="utf-8"), str(script), "exec")
        help_result = run_command([str(script), "--help"])
        assert help_result.returncode == 0, help_result.stderr
        assert "usage:" in help_result.stdout

    make_dry = run_command(
        [
            "make",
            "-n",
            "package",
            "deb-package",
            "core-deb-package",
            "profile-deb-package",
            "touch-waveshare-profile-deb",
            "keyboard-ver1-profile-deb",
            "keyboard-ver0-profile-deb",
            "release-candidate-check",
            "release-prerelease-plan",
            "release-prerelease-publish",
            "release-download-verify",
            "release-stable-check",
            "release-deb-download",
            "release-deb-dry-run",
            "release-deb-install",
            "release-deb-deploy-dry-run",
            "release-deb-deploy",
            "deb-package-dry-run-01",
            "deb-package-dry-run-02",
            "deb-package-install-01",
            "deb-package-install-02",
            "deb-unit-switch-dry-run-01",
            "deb-unit-switch-dry-run-02",
            "deb-unit-switch-01",
            "deb-unit-switch-02",
            "deb-verify-01",
            "deb-verify-02",
            "deb-verify-smoke-01",
            "deb-verify-smoke-02",
            "deb-deploy-01",
            "deb-deploy-02",
            "package-dry-run-02",
            "package-deploy-02",
            "package-opt-dry-run-02",
            "package-opt-deploy-02",
            "package-deb-dry-run-02",
            "package-deb-deploy-02",
            "package-rollback-dry-run-02",
            "package-rollback-02",
        ]
    )
    assert make_dry.returncode == 0, make_dry.stderr
    assert "tools/package/build_release_bundle.sh --allow-dirty" in make_dry.stdout
    assert "tools/package/build_deb_package.sh --build-bundle" in make_dry.stdout
    assert "tools/package/build_deb_package.sh --build-bundle --package-id hidloom-core" in make_dry.stdout
    assert "tools/package/build_device_profile_deb.sh --profile touch-waveshare-8.8" in make_dry.stdout
    assert "tools/package/build_device_profile_deb.sh --profile keyboard-ver1" in make_dry.stdout
    assert "tools/package/build_device_profile_deb.sh --profile keyboard-ver0-prototype" in make_dry.stdout
    assert "tools/package/release_candidate_check.sh" in make_dry.stdout
    assert "tools/package/publish_github_prerelease.sh" in make_dry.stdout
    assert "tools/package/publish_github_prerelease.sh --execute" in make_dry.stdout
    assert "tools/package/verify_github_release_assets.sh --tag" in make_dry.stdout
    assert '--repository "cqa02303/hidloom" --profile "keyboard-ver1"' in make_dry.stdout
    assert "tools/package/check_github_release_stable_ready.sh --tag" in make_dry.stdout
    assert "tools/package/install_github_release_deb.sh --tag" in make_dry.stdout
    assert '--host "pi@<keyboard-ip>" --dry-run' in make_dry.stdout
    assert '--host "pi@<keyboard-ip>" --install' in make_dry.stdout
    assert "tools/package/deploy_github_release_deb.sh --tag" in make_dry.stdout
    assert "tools/package/deploy_deb_package.sh --device 02 --dry-run --apt" in make_dry.stdout
    assert "tools/package/deploy_deb_package.sh --device 01 --dry-run --apt" in make_dry.stdout
    assert "tools/package/deploy_deb_package.sh --device 02 --install --apt" in make_dry.stdout
    assert "tools/package/deploy_deb_package.sh --device 01 --install --apt" in make_dry.stdout
    assert "tools/package/deploy_deb_unit_switch.sh --device 02 --dry-run" in make_dry.stdout
    assert "tools/package/deploy_deb_unit_switch.sh --device 01 --dry-run" in make_dry.stdout
    assert "tools/package/deploy_deb_unit_switch.sh --device 02 --restart" in make_dry.stdout
    assert "tools/package/deploy_deb_unit_switch.sh --device 01 --restart" in make_dry.stdout
    assert "tools/package/deploy_deb_verify.sh --device 02" in make_dry.stdout
    assert "tools/package/deploy_deb_verify.sh --device 01" in make_dry.stdout
    assert "tools/package/deploy_deb_verify.sh --device 02 --smoke" in make_dry.stdout
    assert "tools/package/deploy_deb_verify.sh --device 01 --smoke" in make_dry.stdout
    assert make_dry.stdout.count("tools/package/build_deb_package.sh --build-bundle") >= 1
    assert "tools/package/deploy_release_bundle.sh --device 02 --dry-run" in make_dry.stdout
    assert "tools/package/deploy_release_bundle.sh --device 02 --restart" in make_dry.stdout
    assert "tools/package/deploy_release_bundle.sh --device 02 --opt-release --dry-run" in make_dry.stdout
    assert "tools/package/deploy_release_bundle.sh --device 02 --opt-release --restart" in make_dry.stdout
    assert "tools/package/deploy_release_bundle.sh --device 02 --deb-layout --dry-run" in make_dry.stdout
    assert "tools/package/deploy_release_bundle.sh --device 02 --deb-layout --restart" in make_dry.stdout
    assert "tools/package/deploy_release_rollback.sh --device 02 --previous --dry-run" in make_dry.stdout
    assert "tools/package/deploy_release_rollback.sh --device 02 --previous --restart" in make_dry.stdout

    make_remote_dry = run_command(
        [
            "make",
            "-n",
            "release-deb-dry-run",
            "release-deb-install",
            "release-deb-deploy-dry-run",
            "release-deb-deploy",
            "RELEASE_TAG=v0.0.1746+git74f764e",
            "RELEASE_DEB_REMOTE=pi@<keyboard-ip>",
        ]
    )
    assert make_remote_dry.returncode == 0, make_remote_dry.stderr
    assert '--host "pi@<keyboard-ip>" --dry-run' in make_remote_dry.stdout
    assert '--host "pi@<keyboard-ip>" --install' in make_remote_dry.stdout
    assert "tools/package/install_github_release_deb.sh --tag" in make_remote_dry.stdout
    assert "tools/package/deploy_github_release_deb.sh --tag" in make_remote_dry.stdout

    readme = (PACKAGE_DIR / "README.md").read_text(encoding="utf-8")
    ops_runbook = (ROOT / "docs" / "ops" / "release-packaging-runbook.md").read_text(
        encoding="utf-8"
    )
    assert "matrixd" in readme
    assert "aarch64-linux-gnu-gcc -static" in readme
    assert "make package-deploy-02" in readme
    assert "bin/hidloom-notify" in readme
    assert "tools/hidloom_send" in readme
    assert "make package-opt-deploy-02" in readme
    assert "make package-deb-deploy-02" in readme
    assert "make deb-package" in readme
    assert "make deb-package-dry-run-02" in readme
    assert "make deb-package-install-02" in readme
    assert "make deb-unit-switch-dry-run-02" in readme
    assert "make deb-unit-switch-02" in readme
    assert "make deb-verify-smoke-02" in readme
    assert "make deb-deploy-02" in readme
    assert "make deb-deploy-01" in readme
    assert "GitHub Releases Distribution" in readme
    assert "gh release create --prerelease" in readme
    assert "candidate gate" in readme
    assert "make release-candidate-check" in readme
    assert "make release-prerelease-plan" in readme
    assert "make release-prerelease-publish" in readme
    assert "make release-download-verify" in readme
    assert "make release-stable-check" in readme
    assert "make release-deb-download" in readme
    assert "make release-deb-dry-run" in readme
    assert "make release-deb-install" in readme
    assert "make release-deb-deploy-dry-run" in readme
    assert "make release-deb-deploy" in readme
    assert "RELEASE_DEB_REMOTE=pi@192.168.0.x" in readme
    assert "publish_github_prerelease.sh" in readme
    assert "publish_public_release_bundle.py" in readme
    assert "verify_github_release_assets.sh" in readme
    assert "verify_github_public_release_bundle.py" in readme
    assert "check_github_release_stable_ready.sh" in readme
    assert "install_github_release_deb.sh" in readme
    assert "deploy_github_release_deb.sh" in readme
    assert "release note draft" in readme
    assert "clean git worktree" in readme
    assert "dpkg-deb --contents" in readme
    assert "/usr/share/man" in readme
    assert "portable sha256" in readme
    assert "dpkg --dry-run -i" in readme
    assert "shadowed-by-etc" in readme
    assert "missing-package-unit" in readme
    assert "/etc/systemd/system" in readme
    assert "/lib/systemd/system" in readme
    assert "make package-rollback-02" in readme
    assert "/usr/lib/hidloom" in readme
    assert "/mnt/p3/keymap.json" in readme
    assert "mutable state" in readme
    assert "release-packaging-runbook.md" in readme
    assert "make deb-deploy-01" in ops_runbook
    assert "make deb-deploy-02" in ops_runbook
    assert "dirty_worktree_ignored=true" in ops_runbook
    assert "shadowed-by-etc" in ops_runbook
    assert "missing-package-unit" in ops_runbook
    assert "/mnt/p3/keymap.json" in ops_runbook
    assert "systemctl show -p FragmentPath" in ops_runbook
    assert "Script 責務" in ops_runbook
    assert "Path 契約" in ops_runbook
    assert "/usr/share/man" in ops_runbook
    assert "GitHub Releases で配布する時の考え方" in ops_runbook
    assert "Release candidate gate" in ops_runbook
    assert "GitHub prerelease / stable release の流れ" in ops_runbook
    assert "make release-candidate-check" in ops_runbook
    assert "make release-prerelease-plan" in ops_runbook
    assert "make release-prerelease-publish" in ops_runbook
    assert "make release-download-verify" in ops_runbook
    assert "make release-stable-check" in ops_runbook
    assert "GitHub Release から別環境へ install する手順" in ops_runbook
    assert "make release-deb-download" in ops_runbook
    assert "make release-deb-dry-run" in ops_runbook
    assert "make release-deb-install" in ops_runbook
    assert "make release-deb-deploy-dry-run" in ops_runbook
    assert "make release-deb-deploy" in ops_runbook
    assert "RELEASE_DEB_REMOTE=pi@192.168.0.x" in ops_runbook
    assert "tools/package/install_github_release_deb.sh" in ops_runbook
    assert "tools/package/deploy_github_release_deb.sh" in ops_runbook
    assert "build/packages/release-note-v<version>.md" in ops_runbook
    assert "publish_github_prerelease.sh --tag TAG --execute" in ops_runbook
    assert "publish_public_release_bundle.py" in ops_runbook
    assert "verify_github_public_release_bundle.py" in ops_runbook
    assert "gh release create --prerelease" in ops_runbook
    assert "--prerelease" in ops_runbook
    assert "limited stable" in ops_runbook
    assert "gh release edit <tag> --prerelease=false" in ops_runbook
    assert "release note" in ops_runbook
    assert "portable sha256" in ops_runbook
    assert "配布する binary artifact" in ops_runbook
    assert "GitHub Releases に添付" in ops_runbook
    assert "Preflight と失敗時の分岐" in ops_runbook
    assert "missing-both-units" in ops_runbook
    assert "/usr/lib/systemd/system" in ops_runbook

    rollback_text = ROLLBACK.read_text(encoding="utf-8")
    assert "ACTIVE_ROOT" in rollback_text
    assert "ACTIVE_RELEASE" in rollback_text
    assert 'sed -n \'s|^ExecStart=' in rollback_text

    deploy_deb_text = DEPLOY_DEB.read_text(encoding="utf-8")
    assert "--install" in deploy_deb_text
    assert "sudo dpkg -i" in deploy_deb_text
    assert "dpkg --compare-versions" in deploy_deb_text
    assert "systemd unit shadow check" in deploy_deb_text
    assert "shadowed-by-etc" in deploy_deb_text
    assert "FragmentPath" in deploy_deb_text

    candidate_text = RELEASE_CANDIDATE_CHECK.read_text(encoding="utf-8")
    assert "usr/share/man/man1/hidloom-key" in candidate_text
    assert "usr/share/man/man8/logicd" in candidate_text
    assert "release candidate check requires a clean git worktree" in candidate_text
    assert "script/test_validation_suite.py" in candidate_text
    assert "make -C \"$REPO_ROOT\" deb-package" in candidate_text
    assert "make -C \"$REPO_ROOT\" core-deb-package" in candidate_text
    assert "make -C \"$REPO_ROOT\" DEVICE_PROFILE=\"$SPLIT_PROFILE\" profile-deb-package" in candidate_text
    assert "dpkg-deb --contents" in candidate_text
    assert "sha256sum -c" in candidate_text
    assert "--split-profile" in candidate_text
    assert "hidloom-core (= $core_version)" in candidate_text
    assert "core package does not replace legacy hidloom" in candidate_text
    assert "core package does not conflict with legacy hidloom" in candidate_text
    assert "exact version dependency: passed" in candidate_text
    assert "package manifest reports dirty_worktree_ignored" in candidate_text
    assert "package version does not match manifest git sha" in candidate_text
    assert "package dependency missing" in candidate_text
    assert "python3-luma.oled" in candidate_text
    assert "/home/pi/hidloom" in candidate_text
    assert "release-note-v$version.md" in candidate_text
    assert "This is a prerelease candidate" in candidate_text

    publish_text = PUBLISH_GITHUB_PRERELEASE.read_text(encoding="utf-8")
    assert "By default this is a dry-run" in publish_text
    assert "--execute" in publish_text
    assert "dry-run only; pass --execute" in publish_text
    assert "package version does not match current HEAD" in publish_text
    assert "run make release-candidate-check" in publish_text
    assert "release_candidate_check.sh" in publish_text
    assert "--skip-download-verify" in publish_text
    assert "verify_github_release_assets.sh" in publish_text
    assert "gh release create" in publish_text
    assert "--prerelease" in publish_text
    assert "publish requires a clean git worktree" in publish_text

    public_publish_text = PUBLISH_PUBLIC_RELEASE_BUNDLE.read_text(encoding="utf-8")
    assert "guarded draft GitHub Release" in public_publish_text
    assert '"--draft"' in public_publish_text
    assert '"--prerelease"' in public_publish_text
    assert "CREATE DRAFT" in public_publish_text
    assert "origin-is-not-public-repository" in public_publish_text
    assert "Git tag already exists" in public_publish_text
    assert "verify_github_public_release_bundle.py" in public_publish_text

    public_verify_text = VERIFY_GITHUB_PUBLIC_RELEASE_BUNDLE.read_text(encoding="utf-8")
    assert "deeply verify" in public_verify_text
    assert '"gh",\n                "release",\n                "download"' in public_verify_text
    assert "SHA256SUMS" in public_verify_text
    assert "public_release_bundle.py" in public_verify_text
    assert "--require-publication-ready" in public_verify_text
    assert "--require-hardware-pass" in public_verify_text

    verify_github_text = VERIFY_GITHUB_RELEASE_ASSETS.read_text(encoding="utf-8")
    assert "Raspberry Pi OS split package assets" in verify_github_text
    assert "install_github_release_deb.sh" in verify_github_text
    assert "--repository OWNER/REPO" in verify_github_text

    stable_check_text = CHECK_GITHUB_RELEASE_STABLE_READY.read_text(encoding="utf-8")
    assert "Read a GitHub Release note" in stable_check_text
    assert "prerelease flag" in stable_check_text
    assert "--repository OWNER/REPO" in stable_check_text
    assert '--repository "$REPOSITORY" --profile "$PROFILE"' in stable_check_text
    assert "not tested|skipped|known risk|prerelease candidate|No route to host" in stable_check_text
    assert "<keyboard-host> install" in stable_check_text
    assert "failed units" in stable_check_text
    assert "verify_github_release_assets.sh" in stable_check_text

    install_release_text = INSTALL_GITHUB_RELEASE_DEB.read_text(encoding="utf-8")
    assert "Download the HIDloom Raspberry Pi OS package set" in install_release_text
    assert "Without --dry-run or --install" in install_release_text
    assert "gh release download" in install_release_text
    assert "SHA256SUMS" in install_release_text
    assert "sha256 file is not portable" in install_release_text
    assert "hidloom-core (= $CORE_VERSION)" in install_release_text
    assert "core/profile package version mismatch" in install_release_text
    assert "sudo dpkg --dry-run -i" in install_release_text
    assert "sudo dpkg -i" in install_release_text
    assert "sudo apt-get -s install" in install_release_text
    assert "sudo apt-get install -y" in install_release_text
    assert "package ownership preflight:" in install_release_text
    assert "package ownership collision:" in install_release_text
    assert "/lib/systemd/system/btd.service" in install_release_text
    assert "/usr/share/hidloom/profiles/$PROFILE/profile.json" in install_release_text
    assert "sudo hidloom-profile '$PROFILE' --apply --backup --restart" in install_release_text
    assert "--apt" in install_release_text
    assert "remote install requires --device or --host" in install_release_text

    deploy_deb_text = DEPLOY_DEB.read_text(encoding="utf-8")
    assert "sudo apt-get -s install" in deploy_deb_text
    assert "sudo apt-get install -y" in deploy_deb_text
    assert "--apt" in deploy_deb_text

    deploy_release_text = DEPLOY_GITHUB_RELEASE_DEB.read_text(encoding="utf-8")
    assert "Download and verify a GitHub Release split package set" in deploy_release_text
    assert "requires exactly one of --dry-run or --install" in deploy_release_text
    assert "install_github_release_deb.sh" in deploy_release_text
    assert "--dry-run --apt" in deploy_release_text
    assert "--install --apt" in deploy_release_text
    assert "deploy_deb_unit_switch.sh" in deploy_release_text
    assert "deploy_deb_verify.sh" in deploy_release_text
    assert "--no-smoke" in deploy_release_text
    assert "release deb deploy dry-run complete" in deploy_release_text
    assert "release deb deploy complete" in deploy_release_text

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        assets = tmp / "assets"
        fake_bin = tmp / "bin"
        assets.mkdir()
        fake_bin.mkdir()
        version = "0.1.0+gitfixture"
        core_name = f"hidloom-core_{version}_arm64.deb"
        profile_name = f"hidloom-profile-keyboard-ver1_{version}_arm64.deb"
        make_deb(assets / core_name, "hidloom-core", version)
        make_deb(
            assets / profile_name,
            "hidloom-profile-keyboard-ver1",
            version,
            depends=f"hidloom-core (= {version})",
        )
        checksums = "".join(
            f"{hashlib.sha256((assets / name).read_bytes()).hexdigest()}  {name}\n"
            for name in (core_name, profile_name)
        )
        (assets / "SHA256SUMS").write_text(checksums, encoding="utf-8")

        fake_gh = fake_bin / "gh"
        fake_gh.write_text(
            """#!/usr/bin/env python3
import os
from pathlib import Path
import shutil
import sys

arguments = sys.argv[1:]
assets = Path(os.environ["FAKE_RELEASE_ASSETS"])
if arguments[:2] == ["release", "view"]:
    for path in sorted(assets.iterdir()):
        print(path.name)
elif arguments[:2] == ["release", "download"]:
    pattern = arguments[arguments.index("--pattern") + 1]
    destination = Path(arguments[arguments.index("--dir") + 1])
    shutil.copy2(assets / pattern, destination / pattern)
else:
    raise SystemExit(f"unexpected gh command: {arguments}")
""",
            encoding="utf-8",
        )
        fake_gh.chmod(0o755)
        for command_name, log_name in (("scp", "FAKE_SCP_LOG"), ("ssh", "FAKE_SSH_LOG")):
            command = fake_bin / command_name
            command.write_text(
                f"#!/bin/sh\nprintf '%s\\n' \"$@\" > \"${{{log_name}}}\"\n",
                encoding="utf-8",
            )
            command.chmod(0o755)

        env = os.environ.copy()
        env["PATH"] = f"{fake_bin}:{env['PATH']}"
        env["FAKE_RELEASE_ASSETS"] = str(assets)
        env["FAKE_SCP_LOG"] = str(tmp / "scp.log")
        env["FAKE_SSH_LOG"] = str(tmp / "ssh.log")

        download = tmp / "download"
        verified = run_command(
            [
                str(INSTALL_GITHUB_RELEASE_DEB),
                "--repository",
                "cqa02303/hidloom",
                "--tag",
                "v0.1.0",
                "--profile",
                "keyboard-ver1",
                "--dir",
                str(download),
            ],
            env=env,
        )
        assert verified.returncode == 0, verified.stdout + verified.stderr
        assert "mode: split" in verified.stdout
        assert f"{core_name}: OK" in verified.stdout
        assert f"{profile_name}: OK" in verified.stdout
        assert (download / core_name).is_file()
        assert (download / profile_name).is_file()

        remote_download = tmp / "remote-download"
        installed = run_command(
            [
                str(INSTALL_GITHUB_RELEASE_DEB),
                "--repository",
                "cqa02303/hidloom",
                "--tag",
                "v0.1.0",
                "--profile",
                "keyboard-ver1",
                "--dir",
                str(remote_download),
                "--host",
                "pi@example.invalid",
                "--install",
                "--apt",
            ],
            env=env,
        )
        assert installed.returncode == 0, installed.stdout + installed.stderr
        scp_log = (tmp / "scp.log").read_text(encoding="utf-8")
        ssh_log = (tmp / "ssh.log").read_text(encoding="utf-8")
        assert core_name in scp_log
        assert profile_name in scp_log
        assert "pi@example.invalid:/tmp/" in scp_log
        assert f"sudo apt-get install -y '/tmp/{core_name}' '/tmp/{profile_name}'" in ssh_log
        assert "sudo hidloom-profile 'keyboard-ver1' --apply --backup --restart" in ssh_log

    switch_text = SWITCH_DEB_UNITS.read_text(encoding="utf-8")
    assert "will-backup-remove" in switch_text
    assert "missing-package-unit" in switch_text
    assert "restarted package-managed services" in switch_text
    assert "/var/backups/hidloom/systemd-pre-deb" in switch_text
    assert "rollback: copy" in switch_text

    verify_text = VERIFY_DEB.read_text(encoding="utf-8")
    assert "--profile PROFILE" in verify_text
    assert "--connect-timeout SEC" in verify_text
    assert "ServerAliveCountMax=3" in verify_text
    assert "dpkg-query -W -f=" in verify_text
    assert "hidloom-core" in verify_text
    assert "hidloom-profile-$PROFILE" in verify_text
    assert "split package version mismatch" in verify_text
    assert "dirty_worktree_ignored" in verify_text
    assert "/tmp/matrix_tap_events.sock" in verify_text
    assert "NRestarts" in verify_text
    assert "logicd_core_native_owner_live_smoke.py --apply --json" in verify_text
    assert "/usr/bin/hidloom-ctrl output auto" in verify_text

    deploy_release_text = DEPLOY_GITHUB_RELEASE_DEB.read_text(encoding="utf-8")
    assert 'deploy_deb_verify.sh" $REMOTE_ARG --profile "$PROFILE"' in deploy_release_text

    build_text = BUILD.read_text(encoding="utf-8")
    assert 'sha256sum "$(basename "$ARCHIVE")"' in build_text
    assert 'sha256sum "$ARCHIVE" > "$ARCHIVE.sha256"' not in build_text

    build_deb_text = BUILD_DEB.read_text(encoding="utf-8")
    assert 'sha256sum "$(basename "$DEB_PATH")"' in build_deb_text
    assert 'sha256sum "$DEB_PATH" > "$DEB_PATH.sha256"' not in build_deb_text
    for dependency in (
        "python3-aiohttp",
        "python3-dbus-next",
        "python3-luma.oled",
        "python3-pil",
        "i2c-tools",
        "openssl",
        "rfkill",
        "socat",
    ):
        assert dependency in build_deb_text
        assert dependency in readme
        assert dependency in ops_runbook
    assert "rpi_ws281x" in readme
    assert "rpi_ws281x" in ops_runbook
    assert "apt-get -s install" in readme
    assert "apt-get install" in readme
    assert "apt-get -s install" in ops_runbook
    assert "apt-get install" in ops_runbook
    assert "dpkg --compare-versions" in ops_runbook
    assert "--allow-downgrades" in ops_runbook
    assert 'HIDLOOM_RUNTIME_DIR="\\${HIDLOOM_RUNTIME_DIR:-/mnt/p3}"' in build_deb_text
    assert 'install -d -m 0755 "\\$HIDLOOM_RUNTIME_DIR" "\\$HIDLOOM_RUNTIME_DIR/script"' in build_deb_text
    assert 'config/default/script' in build_deb_text
    assert 'script/migrate_runtime_scripts.py' in build_deb_text
    assert 'config/default/script-migrations.json' in build_deb_text
    assert '--runtime-dir "\\$HIDLOOM_RUNTIME_DIR/script"' in build_deb_text

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        root = tmp / "root"
        manifest = {
            "schema": "hidloom.release-bundle.v1",
            "package": "fixture",
            "git_sha": "fixture",
            "git_rev_count": 42,
            "binaries": [
                "bin/hidloom-hidd",
                "bin/hidloom-uidd",
                "bin/hidloom-outputd",
                "bin/hidloom-logicd-core",
                "bin/hidloom-key",
                "bin/hidloom-keytext",
                "bin/hidloom-oled",
                "bin/hidloom-notify",
                "bin/hidloom-ctrl",
                "daemon/matrixd/matrixd",
            ],
        }
        (root / "build").mkdir(parents=True)
        (root / "build" / "package-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        migration_helper = root / "script" / "migrate_runtime_scripts.py"
        migration_helper.parent.mkdir(parents=True)
        migration_helper.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        migration_helper.chmod(0o755)
        migration_manifest = root / "config" / "default" / "script-migrations.json"
        migration_manifest.parent.mkdir(parents=True)
        migration_manifest.write_text(
            '{"schema":"hidloom.runtime-script-migrations.v1","scripts":{}}\n',
            encoding="utf-8",
        )
        for section, name in (
            ("man1", "hidloom-key.1"),
            ("man1", "hidloom-ctrl.1"),
            ("man5", "hidloom-keymap.5"),
            ("man8", "logicd.8"),
            ("man8", "matrixd.8"),
            ("man8", "hidloom-logicd-core.8"),
        ):
            man = root / "docs" / "man" / section / name
            man.parent.mkdir(parents=True, exist_ok=True)
            man.write_text(
                '.TH TEST 1 "@HIDLOOM_VERSION@" "hidloom" "Test"\n'
                ".SH NAME\n"
                f"{name} - fixture manual page\n"
                ".SH SEE ALSO\n"
                "https://github.com/cqa02303/hidloom/tree/@HIDLOOM_GIT_SHA@/docs\n",
                encoding="utf-8",
            )
        for rel in manifest["binaries"]:
            write_executable(root / rel)
        bundle = tmp / "fixture.tar.zst"
        tar = run_command(["tar", "-C", str(root), "--zstd", "-cf", str(bundle), "."], cwd=tmp)
        assert tar.returncode == 0, tar.stderr
        repo = tmp / "repo"
        repo.mkdir()
        dry = run_command([str(APPLY), str(bundle), "--repo-dir", str(repo), "--dry-run"])
        assert dry.returncode == 0, dry.stdout + dry.stderr
        assert "dry-run: would apply bundle" in dry.stdout
        assert "hidloom.release-bundle.v1" in dry.stdout
        opt_dry = run_command([str(APPLY), str(bundle), "--opt-release", "--dry-run"])
        assert opt_dry.returncode == 0, opt_dry.stdout + opt_dry.stderr
        assert "dry-run: would install bundle" in opt_dry.stdout
        assert "/opt/hidloom/current" in opt_dry.stdout
        deb_dry = run_command([str(APPLY), str(bundle), "--deb-layout", "--dry-run"])
        assert deb_dry.returncode == 0, deb_dry.stdout + deb_dry.stderr
        assert "dry-run: would install bundle to /usr/lib/hidloom" in deb_dry.stdout
        assert "dry-run: would write native input path systemd units" in deb_dry.stdout
        release = tmp / "releases" / "fixture"
        release.mkdir(parents=True)
        for rel in manifest["binaries"]:
            write_executable(release / rel)
        for unit in (
            "hidloom-hidd.service",
            "hidloom-uidd.service",
            "hidloom-outputd.service",
            "hidloom-logicd-core.service",
            "matrixd.service",
            "logicd-companion.service",
            "httpd.service",
            "i2cd.service",
        ):
            unit_path = release / "system" / "systemd" / unit
            unit_path.parent.mkdir(parents=True, exist_ok=True)
            unit_path.write_text(
                "[Service]\nExecStart=@HIDLOOM_REPO_ROOT@/bin/hidloom-hidd\n",
                encoding="utf-8",
            )
        rollback_dry = run_command(
            [
                str(ROLLBACK),
                "--release-dir",
                str(release),
                "--releases-dir",
                str(tmp / "releases"),
                "--current-link",
                str(tmp / "current"),
                "--dry-run",
            ]
        )
        assert rollback_dry.returncode == 0, rollback_dry.stdout + rollback_dry.stderr
        assert "dry-run: would point" in rollback_dry.stdout
        assert "target release:" in rollback_dry.stdout

        for unit in (
            "hidloom-hidd.service",
            "hidloom-uidd.service",
            "hidloom-outputd.service",
            "hidloom-logicd-core.service",
            "matrixd.service",
            "logicd-companion.service",
            "httpd.service",
            "i2cd.service",
        ):
            unit_path = root / "system" / "systemd" / unit
            unit_path.parent.mkdir(parents=True, exist_ok=True)
            unit_path.write_text(
                "[Service]\nExecStart=@HIDLOOM_REPO_ROOT@/bin/hidloom-hidd\n",
                encoding="utf-8",
            )
        rebuild = run_command(["tar", "-C", str(root), "--zstd", "-cf", str(bundle), "."], cwd=tmp)
        assert rebuild.returncode == 0, rebuild.stderr
        out_dir = tmp / "out"
        deb = run_command(
            [
                str(BUILD_DEB),
                "--bundle",
                str(bundle),
                "--out-dir",
                str(out_dir),
                "--work-root",
                str(tmp / "deb-work"),
            ]
        )
        assert deb.returncode == 0, deb.stdout + deb.stderr
        deb_path = out_dir / "hidloom_0.0.42+gitfixture_arm64.deb"
        assert deb_path.exists(), deb.stdout
        info = run_command(["dpkg-deb", "--info", str(deb_path)])
        assert info.returncode == 0, info.stderr
        assert "Package: hidloom" in info.stdout
        assert "Version: 0.0.42+gitfixture" in info.stdout
        assert "Depends: python3, systemd, python3-aiohttp, python3-dbus-next, python3-luma.oled, python3-pil, i2c-tools, openssl, rfkill, socat" in info.stdout
        assert "Conflicts: hidloom" not in info.stdout
        assert "Replaces: hidloom" not in info.stdout
        control_dir = tmp / "deb-control"
        extract_control = run_command(["dpkg-deb", "-e", str(deb_path), str(control_dir)])
        assert extract_control.returncode == 0, extract_control.stderr
        postinst = (control_dir / "postinst").read_text(encoding="utf-8")
        assert 'HIDLOOM_RUNTIME_DIR="${HIDLOOM_RUNTIME_DIR:-/mnt/p3}"' in postinst
        assert 'install -d -m 0755 "$HIDLOOM_RUNTIME_DIR" "$HIDLOOM_RUNTIME_DIR/script"' in postinst
        assert 'config/default/script' in postinst
        assert 'script/migrate_runtime_scripts.py' in postinst
        assert 'config/default/script-migrations.json' in postinst
        assert '--runtime-dir "$HIDLOOM_RUNTIME_DIR/script"' in postinst
        contents = run_command(["dpkg-deb", "--contents", str(deb_path)])
        assert contents.returncode == 0, contents.stderr
        assert "./usr/lib/hidloom/bin/hidloom-hidd" in contents.stdout
        assert "./usr/lib/hidloom/bin/hidloom-key" in contents.stdout
        assert "./usr/lib/hidloom/bin/hidloom-keytext" in contents.stdout
        assert "./usr/lib/hidloom/bin/hidloom-oled" in contents.stdout
        assert "./usr/lib/hidloom/bin/hidloom-notify" in contents.stdout
        assert "./usr/lib/hidloom/bin/hidloom-ctrl" in contents.stdout
        assert "./usr/bin/hidloom-key -> /usr/lib/hidloom/bin/hidloom-key" in contents.stdout
        assert "./usr/bin/hidloom-keytext -> /usr/lib/hidloom/bin/hidloom-keytext" in contents.stdout
        assert "./usr/bin/hidloom-oled -> /usr/lib/hidloom/bin/hidloom-oled" in contents.stdout
        assert "./usr/bin/hidloom-notify -> /usr/lib/hidloom/bin/hidloom-notify" in contents.stdout
        assert "./usr/bin/hidloom-ctrl -> /usr/lib/hidloom/bin/hidloom-ctrl" in contents.stdout
        assert "./lib/systemd/system/hidloom-hidd.service" in contents.stdout
        assert "./lib/systemd/system/httpd.service" in contents.stdout
        assert "./lib/systemd/system/i2cd.service" in contents.stdout
        assert "./var/lib/hidloom/package-manifest.json" in contents.stdout
        assert "./usr/lib/hidloom/script/migrate_runtime_scripts.py" in contents.stdout
        assert "./usr/lib/hidloom/config/default/script-migrations.json" in contents.stdout
        assert "./usr/share/man/man1/hidloom-key.1.gz" in contents.stdout
        assert "./usr/share/man/man8/logicd.8.gz" in contents.stdout
        assert "/mnt/p3" not in contents.stdout
        assert "drwx------" not in contents.stdout
        assert "-rwx------" not in contents.stdout
        assert "-rw-------" not in contents.stdout
        unpack = tmp / "deb-unpack"
        extract = run_command(["dpkg-deb", "-x", str(deb_path), str(unpack)])
        assert extract.returncode == 0, extract.stderr
        for command in ("hidloom-key", "hidloom-keytext", "hidloom-oled", "hidloom-notify", "hidloom-ctrl"):
            command_path = unpack / "usr/bin" / command
            assert command_path.is_symlink(), command
            assert command_path.readlink() == Path(f"/usr/lib/hidloom/bin/{command}"), command
        man_text = run_command(["gzip", "-dc", str(unpack / "usr/share/man/man1/hidloom-key.1.gz")])
        assert man_text.returncode == 0, man_text.stderr
        assert "@HIDLOOM_" not in man_text.stdout
        assert "0.0.42+gitfixture" in man_text.stdout
        assert "tree/fixture/docs" in man_text.stdout

    print("ok: release bundle tools")


if __name__ == "__main__":
    main()
