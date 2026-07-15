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
SCHEMA = "hidloom.public-release-bundle.v2"
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


def write_notes(path: Path, manifest: dict[str, Any]) -> None:
    smoke = manifest["hardware_smoke"]
    seconds = smoke.get("usable_keyboard_seconds")
    timing = "not recorded" if seconds is None else f"{seconds:.3f} seconds"
    path.write_text(
        "\n".join(
            [
                f"# HIDloom {manifest['version']} Release Candidate",
                "",
                f"- Source commit: `{manifest['source']['commit']}`",
                f"- Buildroot commit: `{manifest['buildroot']['commit']}`",
                f"- Hardware smoke: `{smoke['status']}` on `{smoke['device']}`",
                f"- Usable keyboard timing: {timing}",
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
    for required in REQUIRED_COMPLIANCE:
        if not (source / required).is_file():
            raise SystemExit(f"public export is missing {required}")
    for required in (core_package, profile_package):
        if not required.is_file():
            raise SystemExit(f"release input is missing: {required}")
    if not compliance_bundle.is_file():
        raise SystemExit(f"release input is missing: {compliance_bundle}")
    compliance = verify_buildroot_compliance(source, compliance_bundle)
    validate_compliance_source(source, compliance)

    report = load_json(source / "PUBLIC_EXPORT_REPORT.json")
    export_paths = validate_export_manifest(source)
    source_provenance = report["source_provenance"]
    source_commit = str(source_provenance["base_commit"])
    version = safe_version(args.version or f"0.1.0-dev.{source_commit[:12]}")
    if args.hardware_smoke_status == "pass" and (
        args.usable_keyboard_seconds is None or args.usable_keyboard_seconds <= 0
    ):
        raise SystemExit("hardware pass requires a positive usable-keyboard measurement")
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

    assets = [
        asset(source_archive, "corresponding-source"),
        asset(raw_image, "buildroot-m6-raw-image"),
        asset(compressed_image, "buildroot-m6-zstd-image"),
        asset(copied_core, "raspberry-pi-os-core-package"),
        asset(copied_profile, "raspberry-pi-os-keyboard-profile-package"),
        asset(copied_compliance, "buildroot-compliance-source"),
    ]
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
        "packages": {"version": core_version, "profile": "keyboard-ver1"},
        "hardware_smoke": {
            "status": args.hardware_smoke_status,
            "device": args.device,
            "usable_keyboard_seconds": args.usable_keyboard_seconds,
        },
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
    verify(output, require_hardware_pass=False)
    print(f"created public release candidate: {output}")


def verify(directory: Path, require_hardware_pass: bool) -> None:
    directory = directory.resolve()
    manifest_path = directory / "RELEASE_MANIFEST.json"
    checksum_path = directory / "SHA256SUMS"
    manifest = load_json(manifest_path)
    if manifest.get("schema") != SCHEMA:
        raise SystemExit("unsupported release manifest schema")
    smoke = manifest["hardware_smoke"]
    if require_hardware_pass:
        if smoke["status"] != "pass":
            raise SystemExit("hardware smoke is not recorded as pass")
        if not isinstance(smoke.get("usable_keyboard_seconds"), (int, float)) or smoke[
            "usable_keyboard_seconds"
        ] <= 0:
            raise SystemExit("hardware pass lacks a usable-keyboard measurement")
    required_roles = {
        "corresponding-source",
        "buildroot-m6-raw-image",
        "buildroot-m6-zstd-image",
        "raspberry-pi-os-core-package",
        "raspberry-pi-os-keyboard-profile-package",
        "buildroot-compliance-source",
        "compliance",
    }
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
        "offline keyboard appliance",
        "corresponding-source compliance archive",
        "Wi-Fi and httpd are not included",
        "`pi` / `pi`",
    ):
        if phrase not in notes:
            raise SystemExit(f"release notes missing boundary: {phrase}")
    compressed = next(directory.glob("*-buildroot-m6.img.zst"))
    subprocess.run(["zstd", "--test", "--no-progress", str(compressed)], check=True)
    print(f"ok: public release bundle {manifest['version']} ({manifest['hardware_smoke']['status']})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build or verify a HIDloom public release candidate")
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--require-hardware-pass", action="store_true")
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--image", type=Path)
    parser.add_argument("--buildroot-output", type=Path)
    parser.add_argument("--allow-unverified-image", action="store_true")
    parser.add_argument("--core-package", type=Path)
    parser.add_argument("--profile-package", type=Path)
    parser.add_argument("--compliance-bundle", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--version")
    parser.add_argument("--hardware-smoke-status", choices=("pending", "pass", "fail"), default="pending")
    parser.add_argument("--device", default="keyboard-ver1")
    parser.add_argument("--usable-keyboard-seconds", type=float)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.verify:
        verify(args.verify, args.require_hardware_pass)
        return
    for name in ("core_package", "profile_package", "compliance_bundle", "output"):
        if getattr(args, name) is None:
            parser.error(f"--{name.replace('_', '-')} is required when building")
    build(args)


if __name__ == "__main__":
    main()
