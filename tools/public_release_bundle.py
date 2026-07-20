#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from public_export_manifest import verify as verify_export_manifest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "hidloom.public-release-bundle.v4"
REQUIRED_COMPLIANCE = (
    "LICENSE",
    "SBOM.cdx.json",
    "THIRD_PARTY_NOTICES.md",
    "PUBLIC_ASSET_PROVENANCE.json",
    "PUBLIC_ASSET_PROVENANCE.md",
    "PUBLIC_DOCUMENTATION_AUDIT.json",
    "PUBLIC_DOCUMENTATION_AUDIT.md",
    "PUBLIC_EXPORT_REPORT.json",
    "PUBLIC_EXPORT_MANIFEST.json",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_version(value: str) -> str:
    if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+~-]*", value):
        raise SystemExit(f"invalid release version: {value!r}")
    return value


def validate_export_manifest(source: Path) -> list[str]:
    verification = verify_export_manifest(source)
    if not verification["ready"]:
        details = verification["mismatches"] + verification["source_provenance_issues"]
        raise SystemExit("public export verification failed: " + ", ".join(details))
    manifest = load_json(source / "PUBLIC_EXPORT_MANIFEST.json")
    paths = ["PUBLIC_EXPORT_MANIFEST.json"]
    for item in manifest["files"]:
        relative = str(item["path"])
        path = source / relative
        if item["kind"] == "symlink":
            if not path.is_symlink():
                raise SystemExit(f"public export symlink is missing: {relative}")
            content = path.readlink().as_posix().encode()
        else:
            if not path.is_file() or path.is_symlink():
                raise SystemExit(f"public export file is missing: {relative}")
            content = path.read_bytes()
        if len(content) != item["size"] or hashlib.sha256(content).hexdigest() != item["sha256"]:
            raise SystemExit(f"public export manifest mismatch: {relative}")
        paths.append(relative)
    return sorted(paths)


def deterministic_tar(source: Path, destination: Path, arcname: str, paths: list[str]) -> None:
    def normalize(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.uid = 0
        info.gid = 0
        info.uname = ""
        info.gname = ""
        info.mtime = 0
        if info.isdir():
            info.mode = 0o755
        elif info.isfile():
            info.mode = 0o755 if info.mode & 0o111 else 0o644
        elif info.issym() or info.islnk():
            info.mode = 0o777
        return info

    with tempfile.TemporaryDirectory() as tmp:
        tar_path = Path(tmp) / "source.tar"
        with tarfile.open(tar_path, "w", format=tarfile.PAX_FORMAT) as archive:
            root = tarfile.TarInfo(arcname)
            root.type = tarfile.DIRTYPE
            root.mode = 0o755
            archive.addfile(normalize(root))
            for relative in paths:
                archive.add(
                    source / relative,
                    arcname=f"{arcname}/{relative}",
                    recursive=False,
                    filter=normalize,
                )
        subprocess.run(
            ["zstd", "-19", "-T0", "--no-progress", "-f", str(tar_path), "-o", str(destination)],
            check=True,
        )


def asset(path: Path, role: str) -> dict[str, Any]:
    return {
        "path": path.name,
        "role": role,
        "size": path.stat().st_size,
        "sha256": sha256(path),
    }


def package_field(path: Path, field: str) -> str:
    return subprocess.check_output(["dpkg-deb", "--field", str(path), field], text=True).strip()


def verify_buildroot_compliance(source: Path, archive: Path) -> dict[str, Any]:
    tool = source / "tools" / "buildroot_compliance_bundle.py"
    if not tool.is_file():
        raise SystemExit(f"Buildroot compliance verifier is missing: {tool}")
    completed = subprocess.run(
        ["python3", str(tool), "verify", str(archive), "--json"],
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise SystemExit("Buildroot compliance verifier returned invalid JSON") from error
    if not payload.get("binary_release_ready") or payload.get("profile") != "buildroot-m6":
        raise SystemExit("Buildroot compliance bundle is not M6 binary-release ready")
    return payload


def validate_compliance_source(source: Path, compliance: dict[str, Any]) -> None:
    buildroot_source = load_json(source / "config/buildroot-source.json")
    toolchain = load_json(source / "config/buildroot-toolchain-evidence.json")
    legal_summary = load_json(source / "docs/ops/buildroot-m6-legal-summary.json")
    expected_resolved = sorted(
        str(item.get("id", "")) for item in legal_summary.get("release_blockers", [])
    )
    if compliance.get("buildroot_commit") != buildroot_source.get("commit"):
        raise SystemExit("Buildroot compliance bundle commit does not match the release source")
    if compliance.get("bootlin_version") != toolchain.get("version"):
        raise SystemExit("Buildroot compliance toolchain does not match the release source")
    if compliance.get("resolved_release_blockers") != expected_resolved:
        raise SystemExit("Buildroot compliance bundle resolves a different legal baseline")


def publication_status(
    source: Path,
    build_provenance: Path | None,
    source_commit: str,
    package_version: str,
    core_package: Path,
    profile_package: Path,
    image: Path,
    touch_profile_package: Path | None,
    touch_build_provenance: Path | None,
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
        buildroot = provenance.get("buildroot") or {}
        source_data = provenance.get("source") or {}
        package_artifacts = {
            (item.get("role"), item.get("name")): item
            for item in packages.get("artifacts", [])
            if isinstance(item, dict)
        }
        expected_artifacts = (
            ("raspberry-pi-os-core-package", core_package),
            ("raspberry-pi-os-device-profile-package", profile_package),
        )
        matches = all(
            package_artifacts.get((role, path.name), {}).get("sha256") == sha256(path)
            and package_artifacts.get((role, path.name), {}).get("size") == path.stat().st_size
            for role, path in expected_artifacts
        )
        image_data = buildroot.get("image") or {}
        if (
            provenance.get("schema") != "hidloom.public-build-provenance.v2"
            or not provenance.get("ready")
            or provenance.get("mode") != "all"
            or source_data.get("source_commit") != source_commit
            or packages.get("profile_id") != "keyboard-ver1"
            or packages.get("version") != package_version
            or not matches
            or image_data.get("sha256") != sha256(image)
            or image_data.get("size") != image.stat().st_size
            or buildroot.get("mode") != "image"
            or not buildroot.get("ready")
        ):
            raise SystemExit("public build provenance does not match the keyboard/M6 artifacts")
        provenance_asset = {
            "path": "PUBLIC_BUILD_PROVENANCE.json",
            "size": build_provenance.stat().st_size,
            "sha256": sha256(build_provenance),
        }
    touch_provenance_asset = None
    if touch_profile_package is None:
        if touch_build_provenance is not None:
            raise SystemExit("touch build provenance was provided without a touch profile package")
    elif touch_build_provenance is None or not touch_build_provenance.is_file():
        blockers.append("touch-public-build-provenance-missing")
    else:
        touch_provenance = load_json(touch_build_provenance)
        touch_packages = touch_provenance.get("packages") or {}
        touch_source = touch_provenance.get("source") or {}
        touch_artifacts = {
            (item.get("role"), item.get("name")): item
            for item in touch_packages.get("artifacts", [])
            if isinstance(item, dict)
        }
        touch_expected = (
            ("raspberry-pi-os-device-profile-package", touch_profile_package),
        )
        touch_matches = all(
            touch_artifacts.get((role, path.name), {}).get("sha256") == sha256(path)
            and touch_artifacts.get((role, path.name), {}).get("size") == path.stat().st_size
            for role, path in touch_expected
        )
        if (
            touch_provenance.get("schema") != "hidloom.public-build-provenance.v2"
            or not touch_provenance.get("ready")
            or touch_provenance.get("mode") not in {"package", "all"}
            or touch_source.get("source_commit") != source_commit
            or touch_packages.get("profile_id") != "touch-waveshare-8.8"
            or touch_packages.get("version") != package_version
            or not touch_matches
        ):
            raise SystemExit("touch build provenance does not match the release packages")
        touch_provenance_asset = {
            "path": "PUBLIC_BUILD_PROVENANCE_TOUCH.json",
            "size": touch_build_provenance.stat().st_size,
            "sha256": sha256(touch_build_provenance),
        }
    return {
        "ready": not blockers,
        "blockers": blockers,
        "usb_assignment_status": assignment.get("status"),
        "build_provenance": provenance_asset,
        "touch_build_provenance": touch_provenance_asset,
    }


def write_notes(path: Path, manifest: dict[str, Any]) -> None:
    smoke = manifest["hardware_smoke"]
    seconds = smoke.get("usable_keyboard_seconds")
    timing = "not recorded" if seconds is None else f"{seconds:.3f} seconds"
    touch_smoke = manifest.get("touch_hardware_smoke")
    touch_seconds = touch_smoke.get("touch_ready_seconds") if touch_smoke else None
    touch_timing = "not recorded" if touch_seconds is None else f"{touch_seconds:.3f} seconds"
    core_package = next(
        item["path"] for item in manifest["assets"] if item["role"] == "raspberry-pi-os-core-package"
    )
    profile_package = next(
        item["path"]
        for item in manifest["assets"]
        if item["role"] == "raspberry-pi-os-keyboard-profile-package"
    )
    buildroot_image = next(
        item["path"] for item in manifest["assets"] if item["role"] == "buildroot-m6-zstd-image"
    )
    touch_package = next(
        (
            item["path"]
            for item in manifest["assets"]
            if item["role"] == "raspberry-pi-os-touch-profile-package"
        ),
        None,
    )
    publication = manifest["publication"]
    publication_text = (
        "ready" if publication["ready"] else "blocked: " + ", ".join(publication["blockers"])
    )
    path.write_text(
        "\n".join(
            [
                f"# HIDloom {manifest['version']} Release Candidate",
                "",
                f"- Source commit: `{manifest['source']['commit']}`",
                f"- Buildroot commit: `{manifest['buildroot']['commit']}`",
                f"- Hardware smoke (Raspberry Pi OS package + exact M6 image): "
                f"`{smoke['status']}` on `{smoke['device']}`",
                f"- Buildroot M6 usable keyboard timing: {timing}",
                *(
                    [
                        f"- Touch hardware smoke: `{touch_smoke['status']}` on "
                        f"`{touch_smoke['device']}`",
                        f"- Touch ready timing: {touch_timing}",
                    ]
                    if touch_smoke
                    else []
                ),
                f"- Publication gate: `{publication_text}`",
                "",
                "## Choose an Installation Method",
                "",
                "- Raspberry Pi OS package: use this for normal development, updates, and network management.",
                f"  Install `{core_package}` and `{profile_package}` in the same apt transaction.",
                "- Buildroot M6 image: use this for the fastest offline appliance startup.",
                f"  Write `{buildroot_image}` to a dedicated microSD after decompressing it.",
                *(
                    [
                        "- Raspberry Pi OS touch panel: use this for the Raspberry Pi 4 kiosk.",
                        f"  Install `{core_package}` and `{touch_package}` in the same apt transaction.",
                    ]
                    if touch_package
                    else []
                ),
                "- Verify all downloaded assets with `sha256sum -c SHA256SUMS`.",
                "- See `QUICKSTART.md` for package installation, M6 writing, checks, and rollback.",
                "",
                "```sh",
                f"sudo apt-get install -y ./{core_package} ./{profile_package}",
                "sudo hidloom-profile keyboard-ver1 --apply --backup --restart",
                "```",
                *(
                    [
                        "",
                        "```sh",
                        f"sudo apt-get install -y ./{core_package} ./{touch_package}",
                        "sudo hidloom-profile touch-waveshare-8.8 --apply --backup --restart",
                        "```",
                    ]
                    if touch_package
                    else []
                ),
                "",
                "## Appliance Boundary",
                "",
                "- The Buildroot image is an offline keyboard appliance.",
                "- A verified corresponding-source compliance archive is included.",
                "- Wi-Fi and httpd are not included.",
                "- HDMI maintenance output is fixed at 1920x1080.",
                "- The initial local console credential is `pi` / `pi`; change it before extended use.",
                "- Keep the Raspberry Pi OS microSD as the rollback path.",
                "",
                "## Required Hardware Checks",
                "",
                "USB enumerate, JP/US routing, LT tap/hold, Vial save, OLED, LED, analog stick, "
                "uinput login, shutdown, reboot persistence, and usable-keyboard timing.",
                *(
                    [
                        "Touch display, touch input, kiosk health, USB/Vial, reboot persistence, "
                        "and touch-ready timing.",
                    ]
                    if touch_smoke
                    else []
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )


def build(args: argparse.Namespace) -> None:
    source = args.source.resolve()
    output = args.output.resolve()
    core_package = args.core_package.resolve()
    profile_package = args.profile_package.resolve()
    compliance_bundle = args.compliance_bundle.resolve()
    guide = args.guide.resolve()
    touch_profile_package = (
        args.touch_profile_package.resolve() if args.touch_profile_package else None
    )
    for required in REQUIRED_COMPLIANCE:
        if not (source / required).is_file():
            raise SystemExit(f"public export is missing {required}")
    for required in (core_package, profile_package, guide, touch_profile_package):
        if required is None:
            continue
        if not required.is_file():
            raise SystemExit(f"release input is missing: {required}")
    if not compliance_bundle.is_file():
        raise SystemExit(f"release input is missing: {compliance_bundle}")
    compliance = verify_buildroot_compliance(source, compliance_bundle)
    validate_compliance_source(source, compliance)

    report = load_json(source / "PUBLIC_EXPORT_REPORT.json")
    export_paths = validate_export_manifest(source)
    try:
        guide_relative = guide.relative_to(source).as_posix()
    except ValueError as error:
        raise SystemExit("quickstart guide must be inside the public source tree") from error
    if guide_relative not in export_paths:
        raise SystemExit("quickstart guide is not listed by the public export manifest")
    source_provenance = report["source_provenance"]
    source_commit = str(source_provenance["base_commit"])
    version = safe_version(args.version or f"0.1.0-dev.{source_commit[:12]}")
    if args.hardware_smoke_status == "pass" and (
        args.usable_keyboard_seconds is None or args.usable_keyboard_seconds <= 0
    ):
        raise SystemExit("hardware pass requires a positive usable-keyboard measurement")
    if touch_profile_package is None and (
        args.touch_hardware_smoke_status != "pending" or args.touch_ready_seconds is not None
    ):
        raise SystemExit("touch hardware smoke requires a touch profile package")
    if touch_profile_package is not None and args.touch_hardware_smoke_status == "pass" and (
        args.touch_ready_seconds is None or args.touch_ready_seconds <= 0
    ):
        raise SystemExit("touch hardware pass requires a positive touch-ready measurement")
    buildroot_source = load_json(source / "config" / "buildroot-source.json")
    if package_field(core_package, "Package") != "hidloom-core":
        raise SystemExit(f"unexpected core package: {core_package}")
    if package_field(profile_package, "Package") != "hidloom-profile-keyboard-ver1":
        raise SystemExit(f"unexpected profile package: {profile_package}")
    core_version = package_field(core_package, "Version")
    if package_field(profile_package, "Version") != core_version:
        raise SystemExit("core and profile package versions differ")
    if f"git{source_commit[:12]}" not in core_version:
        raise SystemExit("package version does not match public export source commit")
    if package_field(core_package, "Architecture") != "arm64" or package_field(
        profile_package, "Architecture"
    ) != "arm64":
        raise SystemExit("keyboard packages must use arm64 architecture")
    if f"hidloom-core (= {core_version})" not in package_field(profile_package, "Depends"):
        raise SystemExit("keyboard profile package lacks an exact core dependency")
    if touch_profile_package is not None:
        if package_field(touch_profile_package, "Package") != (
            "hidloom-profile-touch-waveshare-8.8"
        ):
            raise SystemExit("unexpected touch profile package")
        if package_field(touch_profile_package, "Version") != core_version:
            raise SystemExit("core and touch profile package versions differ")
        if package_field(touch_profile_package, "Architecture") != "arm64":
            raise SystemExit("touch profile package must use arm64 architecture")
        if f"hidloom-core (= {core_version})" not in package_field(
            touch_profile_package, "Depends"
        ):
            raise SystemExit("touch profile package lacks an exact core dependency")

    if args.buildroot_output:
        buildroot_output = args.buildroot_output.resolve()
        image = buildroot_output / "images" / "sdcard.img"
        for tool in (
            "buildroot_m6_verify.py",
            "buildroot_m6_import_smoke.py",
            "buildroot_m6_runtime_smoke.py",
        ):
            subprocess.run(
                ["python3", str(source / "tools" / tool), "--output", str(buildroot_output)],
                check=True,
            )
        image_verification = "artifact-import-runtime"
    elif args.image and args.allow_unverified_image:
        image = args.image.resolve()
        image_verification = "fixture-unverified"
    else:
        raise SystemExit("use --buildroot-output for a release image")
    if not image.is_file():
        raise SystemExit(f"release input is missing: {image}")

    build_provenance = args.build_provenance.resolve() if args.build_provenance else None
    touch_build_provenance = (
        args.touch_build_provenance.resolve() if args.touch_build_provenance else None
    )
    publication = publication_status(
        source,
        build_provenance,
        source_commit,
        core_version,
        core_package,
        profile_package,
        image,
        touch_profile_package,
        touch_build_provenance,
    )

    if output.exists():
        if any(output.iterdir()) and not args.force:
            raise SystemExit(f"release output is not empty: {output}; pass --force to replace it")
        shutil.rmtree(output)
    output.mkdir(parents=True)

    prefix = f"hidloom-{version}"
    source_archive = output / f"{prefix}-source.tar.zst"
    deterministic_tar(source, source_archive, f"hidloom-{version}", export_paths)
    raw_image = output / f"{prefix}-buildroot-m6.img"
    shutil.copy2(image, raw_image)
    compressed_image = output / f"{raw_image.name}.zst"
    subprocess.run(
        ["zstd", "-19", "-T0", "--no-progress", "-f", str(raw_image), "-o", str(compressed_image)],
        check=True,
    )
    copied_core = output / core_package.name
    copied_profile = output / profile_package.name
    copied_compliance = output / f"{prefix}-buildroot-compliance.tar.zst"
    shutil.copy2(core_package, copied_core)
    shutil.copy2(profile_package, copied_profile)
    shutil.copy2(compliance_bundle, copied_compliance)
    copied_touch = None
    if touch_profile_package is not None:
        copied_touch = output / touch_profile_package.name
        shutil.copy2(touch_profile_package, copied_touch)
    quickstart = output / "QUICKSTART.md"
    shutil.copy2(guide, quickstart)

    assets = [
        asset(source_archive, "corresponding-source"),
        asset(raw_image, "buildroot-m6-raw-image"),
        asset(compressed_image, "buildroot-m6-zstd-image"),
        asset(copied_core, "raspberry-pi-os-core-package"),
        asset(copied_profile, "raspberry-pi-os-keyboard-profile-package"),
        asset(copied_compliance, "buildroot-compliance-source"),
        asset(quickstart, "quickstart"),
    ]
    if build_provenance and build_provenance.is_file():
        copied_provenance = output / "PUBLIC_BUILD_PROVENANCE.json"
        shutil.copy2(build_provenance, copied_provenance)
        assets.append(asset(copied_provenance, "public-build-provenance"))
    if touch_build_provenance and touch_build_provenance.is_file():
        copied_touch_provenance = output / "PUBLIC_BUILD_PROVENANCE_TOUCH.json"
        shutil.copy2(touch_build_provenance, copied_touch_provenance)
        assets.append(asset(copied_touch_provenance, "touch-public-build-provenance"))
    if copied_touch is not None:
        assets.append(asset(copied_touch, "raspberry-pi-os-touch-profile-package"))
    for name in REQUIRED_COMPLIANCE:
        destination = output / name
        shutil.copy2(source / name, destination)
        assets.append(asset(destination, "compliance"))

    manifest = {
        "schema": SCHEMA,
        "version": version,
        "source": {
            "commit": source_commit,
            "revision_count": source_provenance["base_revision_count"],
            "tree": source_provenance["base_tree"],
            "snapshot_sha256": source_provenance["selected_snapshot_sha256"],
            "export_manifest_sha256": sha256(source / "PUBLIC_EXPORT_MANIFEST.json"),
        },
        "buildroot": {
            "commit": buildroot_source["commit"],
            "boot_policy": "microsd-uart-off-hdmi-1920x1080",
            "verification": image_verification,
            "compliance": {
                "schema": compliance["schema"],
                "binary_release_ready": compliance["binary_release_ready"],
                "resolved_release_blockers": compliance["resolved_release_blockers"],
                "manifest_sha256": compliance["manifest_sha256"],
                "archive_sha256": compliance["archive_sha256"],
                "buildroot_commit": compliance["buildroot_commit"],
                "bootlin_version": compliance["bootlin_version"],
                "summary": compliance["summary"],
            },
        },
        "packages": {
            "version": core_version,
            "profile": "keyboard-ver1",
            "touch_profile": "touch-waveshare-8.8" if copied_touch is not None else None,
        },
        "hardware_smoke": {
            "status": args.hardware_smoke_status,
            "device": args.device,
            "usable_keyboard_seconds": args.usable_keyboard_seconds,
        },
        "touch_hardware_smoke": (
            {
                "status": args.touch_hardware_smoke_status,
                "device": args.touch_device,
                "touch_ready_seconds": args.touch_ready_seconds,
            }
            if copied_touch is not None
            else None
        ),
        "publication": publication,
        "network_boundary": {"offline": True, "wifi": False, "httpd": False},
        "assets": assets,
    }
    manifest_path = output / "RELEASE_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    notes_path = output / "RELEASE_NOTES.md"
    write_notes(notes_path, manifest)

    checksum_paths = sorted(path for path in output.iterdir() if path.is_file())
    checksum = output / "SHA256SUMS"
    checksum.write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in checksum_paths),
        encoding="utf-8",
    )
    verify(
        output,
        require_hardware_pass=False,
        require_publication_ready=False,
    )
    print(f"created public release candidate: {output}")


def verify(
    directory: Path,
    require_hardware_pass: bool,
    require_publication_ready: bool,
) -> None:
    directory = directory.resolve()
    manifest_path = directory / "RELEASE_MANIFEST.json"
    checksum_path = directory / "SHA256SUMS"
    manifest = load_json(manifest_path)
    if manifest.get("schema") != SCHEMA:
        raise SystemExit("unsupported release manifest schema")
    if require_publication_ready and not manifest["publication"]["ready"]:
        raise SystemExit(
            "keyboard/M6 release is not publishable: "
            + ", ".join(manifest["publication"]["blockers"])
        )
    smoke = manifest["hardware_smoke"]
    if smoke.get("status") not in {"pending", "pass", "fail"} or not smoke.get("device"):
        raise SystemExit("keyboard hardware smoke metadata is invalid")
    keyboard_seconds = smoke.get("usable_keyboard_seconds")
    if keyboard_seconds is not None and (
        not isinstance(keyboard_seconds, (int, float)) or keyboard_seconds <= 0
    ):
        raise SystemExit("keyboard hardware timing must be positive")
    if require_hardware_pass:
        if smoke["status"] != "pass":
            raise SystemExit("keyboard hardware smoke is not recorded as pass")
        if keyboard_seconds is None:
            raise SystemExit("keyboard hardware pass lacks a usable-keyboard measurement")
    required_roles = {
        "corresponding-source",
        "buildroot-m6-raw-image",
        "buildroot-m6-zstd-image",
        "raspberry-pi-os-core-package",
        "raspberry-pi-os-keyboard-profile-package",
        "buildroot-compliance-source",
        "quickstart",
        "compliance",
    }
    touch_profile_declared = bool(manifest["packages"].get("touch_profile"))
    touch_smoke = manifest.get("touch_hardware_smoke")
    if touch_profile_declared:
        required_roles.add("raspberry-pi-os-touch-profile-package")
        if not isinstance(touch_smoke, dict):
            raise SystemExit("touch profile release lacks touch hardware smoke metadata")
        if touch_smoke.get("status") not in {"pending", "pass", "fail"} or not touch_smoke.get(
            "device"
        ):
            raise SystemExit("touch hardware smoke metadata is invalid")
        touch_seconds = touch_smoke.get("touch_ready_seconds")
        if touch_seconds is not None and (
            not isinstance(touch_seconds, (int, float)) or touch_seconds <= 0
        ):
            raise SystemExit("touch-ready timing must be positive")
        if require_hardware_pass:
            if touch_smoke["status"] != "pass":
                raise SystemExit("touch hardware smoke is not recorded as pass")
            if touch_seconds is None:
                raise SystemExit("touch hardware pass lacks a touch-ready measurement")
    elif touch_smoke is not None:
        raise SystemExit("release has touch hardware smoke without a touch profile")
    roles = {item["role"] for item in manifest["assets"]}
    if not required_roles <= roles:
        raise SystemExit("release manifest is missing required asset roles")
    compliance_assets = [
        item for item in manifest["assets"] if item["role"] == "buildroot-compliance-source"
    ]
    if len(compliance_assets) != 1:
        raise SystemExit("release manifest must contain exactly one Buildroot compliance bundle")
    asset_names: set[str] = set()
    for item in manifest["assets"]:
        name = str(item["path"])
        if Path(name).name != name or name in asset_names:
            raise SystemExit(f"unsafe or duplicate release asset path: {name}")
        asset_names.add(name)
        path = directory / name
        if not path.is_file() or path.stat().st_size != item["size"] or sha256(path) != item["sha256"]:
            raise SystemExit(f"release asset mismatch: {item['path']}")
    compliance = verify_buildroot_compliance(
        ROOT, directory / str(compliance_assets[0]["path"])
    )
    expected_compliance = manifest["buildroot"].get("compliance", {})
    for field in (
        "schema",
        "binary_release_ready",
        "resolved_release_blockers",
        "manifest_sha256",
        "archive_sha256",
        "buildroot_commit",
        "bootlin_version",
        "summary",
    ):
        if expected_compliance.get(field) != compliance.get(field):
            raise SystemExit(f"release compliance metadata mismatch: {field}")
    checksum_names: set[str] = set()
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        if Path(name).name != name or not (directory / name).is_file():
            raise SystemExit(f"unsafe or missing checksum entry: {name}")
        checksum_names.add(name)
        if sha256(directory / name) != digest:
            raise SystemExit(f"checksum mismatch: {name}")
    expected_names = {path.name for path in directory.iterdir() if path.is_file()} - {"SHA256SUMS"}
    if checksum_names != expected_names:
        raise SystemExit("SHA256SUMS does not cover the complete release directory")
    notes = (directory / "RELEASE_NOTES.md").read_text(encoding="utf-8")
    for phrase in (
        "Raspberry Pi OS package",
        "Buildroot M6 image",
        "same apt transaction",
        "sha256sum -c SHA256SUMS",
        "hidloom-profile keyboard-ver1 --apply --backup --restart",
        "offline keyboard appliance",
        "corresponding-source compliance archive",
        "QUICKSTART.md",
        "Wi-Fi and httpd are not included",
        "`pi` / `pi`",
    ):
        if phrase not in notes:
            raise SystemExit(f"release notes missing boundary: {phrase}")
    touch_assets = [
        item for item in manifest["assets"] if item["role"] == "raspberry-pi-os-touch-profile-package"
    ]
    if touch_profile_declared:
        if len(touch_assets) != 1:
            raise SystemExit("release manifest must contain exactly one touch profile package")
        touch_path = directory / str(touch_assets[0]["path"])
        if package_field(touch_path, "Package") != "hidloom-profile-touch-waveshare-8.8":
            raise SystemExit("release touch profile metadata mismatch")
        if package_field(touch_path, "Version") != manifest["packages"]["version"]:
            raise SystemExit("release touch profile version mismatch")
        if "touch-waveshare-8.8 --apply --backup --restart" not in notes:
            raise SystemExit("release notes missing touch profile guidance")
        for phrase in ("Touch hardware smoke", "Touch ready timing", "touch-ready timing"):
            if phrase not in notes:
                raise SystemExit(f"release notes missing touch hardware boundary: {phrase}")
    elif touch_assets:
        raise SystemExit("release contains an undeclared touch profile package")
    compressed = next(directory.glob("*-buildroot-m6.img.zst"))
    subprocess.run(["zstd", "--test", "--no-progress", str(compressed)], check=True)
    print(f"ok: public release bundle {manifest['version']} ({manifest['hardware_smoke']['status']})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build or verify a HIDloom public release candidate")
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--require-hardware-pass", action="store_true")
    parser.add_argument("--require-publication-ready", action="store_true")
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--image", type=Path)
    parser.add_argument("--buildroot-output", type=Path)
    parser.add_argument("--allow-unverified-image", action="store_true")
    parser.add_argument("--core-package", type=Path)
    parser.add_argument("--profile-package", type=Path)
    parser.add_argument("--touch-profile-package", type=Path)
    parser.add_argument("--compliance-bundle", type=Path)
    parser.add_argument("--build-provenance", type=Path)
    parser.add_argument("--touch-build-provenance", type=Path)
    parser.add_argument("--guide", type=Path, default=ROOT / "INSTALL.md")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--version")
    parser.add_argument(
        "--hardware-smoke-status",
        choices=("pending", "pass", "fail"),
        default="pending",
        help="aggregate Raspberry Pi OS keyboard package and exact M6 image smoke",
    )
    parser.add_argument("--device", default="keyboard-ver1")
    parser.add_argument(
        "--usable-keyboard-seconds",
        type=float,
        help="positive USB-to-usable timing measured from the exact M6 image",
    )
    parser.add_argument(
        "--touch-hardware-smoke-status", choices=("pending", "pass", "fail"), default="pending"
    )
    parser.add_argument("--touch-device", default="touch-waveshare-8.8")
    parser.add_argument("--touch-ready-seconds", type=float)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.verify:
        verify(args.verify, args.require_hardware_pass, args.require_publication_ready)
        return
    for name in ("core_package", "profile_package", "compliance_bundle", "output"):
        if getattr(args, name) is None:
            parser.error(f"--{name.replace('_', '-')} is required when building")
    build(args)


if __name__ == "__main__":
    main()
