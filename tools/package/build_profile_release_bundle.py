#!/usr/bin/env python3
"""Build and verify a public Raspberry Pi OS profile package release directory."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from public_release_bundle import (  # noqa: E402
    REQUIRED_COMPLIANCE,
    asset,
    deterministic_tar,
    load_json,
    package_field,
    safe_version,
    sha256,
    validate_export_manifest,
)


SCHEMA = "hidloom.profile-package-release.v1"


def safe_profile(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
        raise SystemExit(f"invalid profile id: {value!r}")
    return value


def extract_json(package: Path, relative: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="hidloom-profile-release-") as temporary:
        destination = Path(temporary)
        subprocess.run(
            ["dpkg-deb", "--extract", str(package), str(destination)],
            check=True,
            capture_output=True,
            text=True,
        )
        path = destination / relative
        if not path.is_file():
            raise SystemExit(f"package metadata is missing: {package.name}:{relative}")
        return load_json(path)


def validate_packages(
    source: Path,
    core: Path,
    profile_package: Path,
    profile_id: str,
    source_commit: str,
    revision_count: int,
) -> dict[str, Any]:
    expected_profile_package = f"hidloom-profile-{profile_id}"
    core_version = package_field(core, "Version")
    profile_version = package_field(profile_package, "Version")
    fields = {
        "core": {
            "package": package_field(core, "Package"),
            "version": core_version,
            "architecture": package_field(core, "Architecture"),
        },
        "profile": {
            "package": package_field(profile_package, "Package"),
            "version": profile_version,
            "architecture": package_field(profile_package, "Architecture"),
            "depends": package_field(profile_package, "Depends"),
        },
    }
    if fields["core"] != {
        "package": "hidloom-core",
        "version": core_version,
        "architecture": "arm64",
    }:
        raise SystemExit("unexpected core package metadata")
    if fields["profile"]["package"] != expected_profile_package:
        raise SystemExit("unexpected device profile package name")
    if profile_version != core_version:
        raise SystemExit("core and profile package versions differ")
    if fields["profile"]["architecture"] != "arm64":
        raise SystemExit("device profile package architecture must be arm64")
    if f"hidloom-core (= {core_version})" not in fields["profile"]["depends"]:
        raise SystemExit("device profile package lacks an exact core dependency")
    expected_version = f"0.0.{revision_count}+git{source_commit[:12]}"
    if core_version != expected_version:
        raise SystemExit(
            f"package version does not match public source: {core_version} != {expected_version}"
        )

    package_manifest = extract_json(core, "var/lib/hidloom/package-manifest.json")
    expected_manifest = {
        "source_mode": "public-export",
        "git_sha": source_commit[:12],
        "git_describe": source_commit,
        "git_rev_count": revision_count,
        "public_export_manifest_sha256": sha256(source / "PUBLIC_EXPORT_MANIFEST.json"),
        "dirty_worktree_ignored": False,
    }
    for name, expected in expected_manifest.items():
        if package_manifest.get(name) != expected:
            raise SystemExit(f"core package provenance mismatch: {name}")

    installed_profile = extract_json(
        profile_package,
        f"usr/share/hidloom/profiles/{profile_id}/profile.json",
    )
    if installed_profile.get("id") != profile_id:
        raise SystemExit("device profile package contains a different profile id")
    return {"version": core_version, "metadata": fields, "manifest": package_manifest}


def publication_status(
    source: Path,
    build_provenance: Path | None,
    profile_id: str,
    source_commit: str,
    package_version: str,
) -> dict[str, Any]:
    blockers: list[str] = []
    identity = load_json(source / "config/public-usb-identity.json")
    assignment = identity.get("assignment", {})
    formal = identity.get("profiles", {}).get(identity.get("public_release_profile"), {})
    if assignment.get("status") != "assigned" or not formal.get("public_release_allowed"):
        blockers.append("public-usb-identity-not-assigned")

    provenance_asset = None
    if build_provenance is None or not build_provenance.is_file():
        blockers.append("public-build-provenance-missing")
    else:
        provenance = load_json(build_provenance)
        packages = provenance.get("packages") or {}
        if (
            provenance.get("schema") != "hidloom.public-build-provenance.v2"
            or not provenance.get("ready")
            or packages.get("profile_id") != profile_id
            or packages.get("version") != package_version
            or (provenance.get("source") or {}).get("source_commit") != source_commit
        ):
            raise SystemExit("public build provenance does not match the package profile")
        provenance_asset = {
            "path": "PUBLIC_BUILD_PROVENANCE.json",
            "size": build_provenance.stat().st_size,
            "sha256": sha256(build_provenance),
        }
    return {
        "ready": not blockers,
        "blockers": blockers,
        "usb_assignment_status": assignment.get("status"),
        "build_provenance": provenance_asset,
    }


def write_notes(path: Path, manifest: dict[str, Any]) -> None:
    profile = manifest["profile"]
    packages = manifest["packages"]
    publication = manifest["publication"]
    status = "ready" if publication["ready"] else "blocked: " + ", ".join(publication["blockers"])
    path.write_text(
        "\n".join(
            [
                f"# HIDloom {profile['label']} Package",
                "",
                f"- Target profile: `{profile['id']}`",
                f"- Raspberry Pi OS package version: `{packages['version']}`",
                f"- Source commit: `{manifest['source']['commit']}`",
                f"- Publication gate: `{status}`",
                "",
                "## Download",
                "",
                f"- `{packages['core']['path']}`",
                f"- `{packages['profile']['path']}`",
                f"- `{manifest['source']['archive']}`",
                "- `SHA256SUMS`",
                "- `QUICKSTART.md`",
                "",
                "Keep the two `.deb` files at exactly the same version. Verify every downloaded file before installation:",
                "",
                "```sh",
                "sha256sum -c SHA256SUMS",
                "```",
                "",
                "Install the core and profile packages in the same apt transaction, then apply the profile:",
                "",
                "```sh",
                f"sudo apt-get install -y ./{packages['core']['path']} ./{packages['profile']['path']}",
                f"sudo hidloom-profile {profile['id']} --apply --backup --restart",
                "```",
                "",
                "See `QUICKSTART.md` for fresh Raspberry Pi OS preparation, kiosk autostart, health checks, and rollback.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def build(args: argparse.Namespace) -> None:
    source = args.source.resolve()
    output = args.output.resolve()
    core = args.core_package.resolve()
    profile_package = args.profile_package.resolve()
    guide = args.guide.resolve()
    profile_id = safe_profile(args.profile)
    for path in (core, profile_package, guide):
        if not path.is_file():
            raise SystemExit(f"release input is missing: {path}")
    for name in REQUIRED_COMPLIANCE:
        if not (source / name).is_file():
            raise SystemExit(f"public export is missing {name}")

    export_paths = validate_export_manifest(source)
    try:
        guide_relative = guide.relative_to(source).as_posix()
    except ValueError as error:
        raise SystemExit("quickstart guide must be inside the public source tree") from error
    if guide_relative not in export_paths:
        raise SystemExit("quickstart guide is not listed by the public export manifest")
    report = load_json(source / "PUBLIC_EXPORT_REPORT.json")
    provenance = report["source_provenance"]
    source_commit = str(provenance["base_commit"])
    revision_count = int(provenance["base_revision_count"])
    profile_definition = load_json(source / f"config/device-profiles/{profile_id}.json")
    if profile_definition.get("id") != profile_id:
        raise SystemExit("public source profile definition does not match --profile")
    package_data = validate_packages(
        source,
        core,
        profile_package,
        profile_id,
        source_commit,
        revision_count,
    )
    version = safe_version(args.version or package_data["version"])
    if args.hardware_smoke_status == "pass" and (
        not args.device or args.touch_ready_seconds is None or args.touch_ready_seconds <= 0
    ):
        raise SystemExit("hardware pass requires a device and positive touch-ready measurement")

    build_provenance = args.build_provenance.resolve() if args.build_provenance else None
    publication = publication_status(
        source,
        build_provenance,
        profile_id,
        source_commit,
        package_data["version"],
    )
    if output.exists():
        if any(output.iterdir()) and not args.force:
            raise SystemExit(f"release output is not empty: {output}; pass --force to replace it")
        shutil.rmtree(output)
    output.mkdir(parents=True)

    source_archive = output / f"hidloom-{version}-source.tar.zst"
    deterministic_tar(source, source_archive, f"hidloom-{version}-source", export_paths)
    copied_core = output / core.name
    copied_profile = output / profile_package.name
    shutil.copy2(core, copied_core)
    shutil.copy2(profile_package, copied_profile)
    shutil.copy2(guide, output / "QUICKSTART.md")

    assets = [
        asset(source_archive, "corresponding-source"),
        asset(copied_core, "raspberry-pi-os-core-package"),
        asset(copied_profile, "raspberry-pi-os-device-profile-package"),
        asset(output / "QUICKSTART.md", "quickstart"),
    ]
    if build_provenance and build_provenance.is_file():
        copied_provenance = output / "PUBLIC_BUILD_PROVENANCE.json"
        shutil.copy2(build_provenance, copied_provenance)
        assets.append(asset(copied_provenance, "public-build-provenance"))
    for name in REQUIRED_COMPLIANCE:
        destination = output / name
        shutil.copy2(source / name, destination)
        assets.append(asset(destination, "compliance"))

    manifest = {
        "schema": SCHEMA,
        "release_version": version,
        "source": {
            "commit": source_commit,
            "tree": provenance["base_tree"],
            "revision_count": revision_count,
            "snapshot_sha256": provenance["selected_snapshot_sha256"],
            "archive": source_archive.name,
        },
        "profile": {
            "id": profile_id,
            "label": profile_definition.get("label", profile_id),
            "kind": profile_definition.get("kind"),
        },
        "packages": {
            "version": package_data["version"],
            "core": {"path": copied_core.name, **package_data["metadata"]["core"]},
            "profile": {"path": copied_profile.name, **package_data["metadata"]["profile"]},
        },
        "hardware_smoke": {
            "status": args.hardware_smoke_status,
            "device": args.device,
            "touch_ready_seconds": args.touch_ready_seconds,
        },
        "publication": publication,
        "assets": sorted(assets, key=lambda item: item["path"]),
    }
    (output / "PACKAGE_RELEASE_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_notes(output / "RELEASE_NOTES.md", manifest)
    checksum_paths = sorted(path for path in output.iterdir() if path.is_file())
    (output / "SHA256SUMS").write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in checksum_paths),
        encoding="utf-8",
    )
    verify(output, require_publication_ready=False, require_hardware_pass=False)
    print(f"created profile package release: {output}")


def verify(directory: Path, require_publication_ready: bool, require_hardware_pass: bool) -> None:
    directory = directory.resolve()
    manifest = load_json(directory / "PACKAGE_RELEASE_MANIFEST.json")
    if manifest.get("schema") != SCHEMA:
        raise SystemExit("unsupported profile package release schema")
    if require_publication_ready and not manifest["publication"]["ready"]:
        raise SystemExit(
            "profile package release is not publishable: "
            + ", ".join(manifest["publication"]["blockers"])
        )
    smoke = manifest["hardware_smoke"]
    if require_hardware_pass and (
        smoke.get("status") != "pass"
        or not smoke.get("device")
        or not isinstance(smoke.get("touch_ready_seconds"), (int, float))
        or smoke["touch_ready_seconds"] <= 0
    ):
        raise SystemExit("touch-panel hardware smoke is not recorded as pass")

    roles = {item["role"] for item in manifest["assets"]}
    required_roles = {
        "corresponding-source",
        "raspberry-pi-os-core-package",
        "raspberry-pi-os-device-profile-package",
        "quickstart",
        "compliance",
    }
    if not required_roles <= roles:
        raise SystemExit("profile release manifest is missing required asset roles")
    asset_names: set[str] = set()
    for item in manifest["assets"]:
        name = str(item["path"])
        if Path(name).name != name or name in asset_names:
            raise SystemExit(f"unsafe or duplicate release asset path: {name}")
        asset_names.add(name)
        path = directory / name
        if not path.is_file() or path.stat().st_size != item["size"] or sha256(path) != item["sha256"]:
            raise SystemExit(f"profile release asset mismatch: {name}")

    packages = manifest["packages"]
    core = directory / packages["core"]["path"]
    profile_package = directory / packages["profile"]["path"]
    if package_field(core, "Package") != "hidloom-core":
        raise SystemExit("release core package metadata mismatch")
    if package_field(profile_package, "Package") != f"hidloom-profile-{manifest['profile']['id']}":
        raise SystemExit("release profile package metadata mismatch")
    if package_field(core, "Version") != packages["version"] or package_field(
        profile_package, "Version"
    ) != packages["version"]:
        raise SystemExit("release package version mismatch")

    checksum = directory / "SHA256SUMS"
    entries: dict[str, str] = {}
    for line in checksum.read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        if Path(name).name != name or name in entries:
            raise SystemExit(f"unsafe or duplicate checksum entry: {name}")
        entries[name] = digest
        if not (directory / name).is_file() or sha256(directory / name) != digest:
            raise SystemExit(f"checksum mismatch: {name}")
    expected = {path.name for path in directory.iterdir() if path.is_file()} - {"SHA256SUMS"}
    if set(entries) != expected:
        raise SystemExit("SHA256SUMS does not cover the complete profile release directory")

    source_archive = directory / manifest["source"]["archive"]
    subprocess.run(
        ["zstd", "--test", "--no-progress", str(source_archive)],
        check=True,
        capture_output=True,
        text=True,
    )
    notes = (directory / "RELEASE_NOTES.md").read_text(encoding="utf-8")
    for phrase in (
        "same apt transaction",
        "sha256sum -c SHA256SUMS",
        f"hidloom-profile {manifest['profile']['id']} --apply --backup --restart",
        "QUICKSTART.md",
    ):
        if phrase not in notes:
            raise SystemExit(f"release notes missing required guidance: {phrase}")
    print(f"ok: profile package release {manifest['release_version']} ({manifest['profile']['id']})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--source", type=Path, required=True)
    build_parser.add_argument("--core-package", type=Path, required=True)
    build_parser.add_argument("--profile-package", type=Path, required=True)
    build_parser.add_argument("--profile", required=True)
    build_parser.add_argument("--guide", type=Path, required=True)
    build_parser.add_argument("--build-provenance", type=Path)
    build_parser.add_argument("--output", type=Path, required=True)
    build_parser.add_argument("--version")
    build_parser.add_argument(
        "--hardware-smoke-status",
        choices=("pending", "pass", "fail"),
        default="pending",
    )
    build_parser.add_argument("--device")
    build_parser.add_argument("--touch-ready-seconds", type=float)
    build_parser.add_argument("--force", action="store_true")
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("directory", type=Path)
    verify_parser.add_argument("--require-publication-ready", action="store_true")
    verify_parser.add_argument("--require-hardware-pass", action="store_true")
    args = parser.parse_args()
    if args.command == "verify":
        verify(args.directory, args.require_publication_ready, args.require_hardware_pass)
    else:
        build(args)


if __name__ == "__main__":
    main()
