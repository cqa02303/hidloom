#!/usr/bin/env python3
"""Record and re-verify package and Buildroot builds from a HIDloom public export."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any


TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
sys.dont_write_bytecode = True

from public_export import validate_public_documentation_audit  # noqa: E402
from public_export_manifest import verify as verify_export_manifest  # noqa: E402


SCHEMA = "hidloom.public-build-provenance.v2"
PACKAGE_MODES = {"package", "all"}
BUILDROOT_MODES = {"buildroot-configure", "buildroot-image", "all"}
IMAGE_MODES = {"buildroot-image", "all"}
M6_SYMBOLS = (
    "BR2_PACKAGE_HIDLOOM_MATRIXD=y",
    "BR2_PACKAGE_PYTHON_LUMA_OLED=y",
    "BR2_PACKAGE_SUDO=y",
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact(path: Path, role: str) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"missing build artifact: {path}")
    return {
        "role": role,
        "name": path.name,
        "size": path.stat().st_size,
        "sha256": sha256(path),
    }


def run(command: list[str], *, cwd: Path | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def one(paths: list[Path], description: str) -> Path:
    if len(paths) != 1:
        raise SystemExit(f"expected exactly one {description}, found {len(paths)}")
    return paths[0]


def verify_sidecar(path: Path) -> Path:
    sidecar = path.with_name(path.name + ".sha256")
    if not sidecar.is_file():
        raise SystemExit(f"checksum sidecar is missing: {sidecar}")
    fields = sidecar.read_text(encoding="utf-8").strip().split()
    if len(fields) != 2 or fields[1].lstrip("*") != path.name:
        raise SystemExit(f"invalid checksum sidecar: {sidecar}")
    if fields[0] != sha256(path):
        raise SystemExit(f"checksum mismatch: {path}")
    return sidecar


def deb_field(path: Path, field: str) -> str:
    return run(["dpkg-deb", "--field", str(path), field])


def deb_manifest(path: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="hidloom-provenance-deb-") as temporary:
        destination = Path(temporary)
        run(["dpkg-deb", "--extract", str(path), str(destination)])
        manifest = destination / "var/lib/hidloom/package-manifest.json"
        if not manifest.is_file():
            raise SystemExit(f"package manifest is missing from {path}")
        return load_json(manifest)


def bundle_manifest(path: Path) -> dict[str, Any]:
    content = run(["tar", "--zstd", "-xOf", str(path), "./build/package-manifest.json"])
    return json.loads(content)


def collect_source(root: Path) -> dict[str, Any]:
    report_path = root / "PUBLIC_EXPORT_REPORT.json"
    reference_path = root / "PUBLIC_REFERENCE_AUDIT.json"
    documentation_path = root / "PUBLIC_DOCUMENTATION_AUDIT.json"
    if (
        not report_path.is_file()
        or not reference_path.is_file()
        or not documentation_path.is_file()
    ):
        raise SystemExit("public export report/reference/documentation audit is missing")
    report = load_json(report_path)
    references = load_json(reference_path)
    documentation = load_json(documentation_path)
    documentation_issues = validate_public_documentation_audit(
        documentation, root=root
    )
    manifest = verify_export_manifest(root)
    if not manifest["ready"]:
        raise SystemExit("public export manifest is not intact")
    source_provenance = manifest["source_provenance"]
    if not references["ready"] or references["summary"]["blockers"] != 0:
        raise SystemExit("public reference audit is not ready")
    if documentation_issues or not documentation.get("ready"):
        raise SystemExit("public documentation audit is not ready")
    return {
        "source_commit": source_provenance["base_commit"],
        "source_tree": source_provenance["base_tree"],
        "source_snapshot_sha256": source_provenance["selected_snapshot_sha256"],
        "source_revision_count": source_provenance["base_revision_count"],
        "initial_version": report["initial_version"],
        "public_repository": references["public_repository"],
        "export_report": {
            "size": report_path.stat().st_size,
            "sha256": sha256(report_path),
        },
        "export_manifest": manifest["manifest"],
        "listed_files": manifest["listed_files"],
        "reference_audit": {
            "size": reference_path.stat().st_size,
            "sha256": sha256(reference_path),
            "blockers": references["summary"]["blockers"],
        },
        "documentation_audit": {
            "size": documentation_path.stat().st_size,
            "sha256": sha256(documentation_path),
            "omitted_private_links": documentation["summary"]["omitted_private_links"],
            "removed_private_navigation_lines": documentation["summary"][
                "removed_private_navigation_lines"
            ],
            "broken_links": documentation["summary"]["broken_links"],
            "orphaned_documents": documentation["summary"]["orphaned_documents"],
        },
    }


def collect_packages(
    root: Path,
    directory: Path,
    source: dict[str, Any],
    profile_id: str,
) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", profile_id):
        raise SystemExit(f"invalid package profile id: {profile_id!r}")
    profile_definition = root / "config/device-profiles" / f"{profile_id}.json"
    if not profile_definition.is_file():
        raise SystemExit(f"package profile definition is missing: {profile_id}")
    short = source["source_commit"][:12]
    revision = source["source_revision_count"]
    version = f"0.0.{revision}+git{short}"
    bundle = directory / f"hidloom-{short}-aarch64.tar.zst"
    core = one(sorted(directory.glob(f"hidloom-core_{version}_arm64.deb")), "core package")
    profile_package = f"hidloom-profile-{profile_id}"
    profile = one(
        sorted(directory.glob(f"{profile_package}_{version}_arm64.deb")),
        f"{profile_id} profile package",
    )
    bundle_data = bundle_manifest(bundle)
    core_data = deb_manifest(core)
    expected_manifest_sha = source["export_manifest"]["sha256"]
    for name, manifest in (("bundle", bundle_data), ("core", core_data)):
        if manifest.get("source_mode") != "public-export":
            raise SystemExit(f"{name} does not use public-export provenance")
        if manifest.get("git_sha") != short or manifest.get("git_describe") != source["source_commit"]:
            raise SystemExit(f"{name} source commit does not match the public export")
        if manifest.get("git_rev_count") != revision:
            raise SystemExit(f"{name} revision count does not match the public export")
        if manifest.get("public_export_manifest_sha256") != expected_manifest_sha:
            raise SystemExit(f"{name} public export manifest hash mismatch")
    if bundle_data != core_data:
        raise SystemExit("bundle and core package manifests differ")
    metadata = {
        "core": {
            "package": deb_field(core, "Package"),
            "version": deb_field(core, "Version"),
            "architecture": deb_field(core, "Architecture"),
        },
        "profile": {
            "package": deb_field(profile, "Package"),
            "version": deb_field(profile, "Version"),
            "architecture": deb_field(profile, "Architecture"),
            "depends": deb_field(profile, "Depends"),
        },
    }
    if metadata["core"] != {
        "package": "hidloom-core",
        "version": version,
        "architecture": "arm64",
    }:
        raise SystemExit("unexpected core package metadata")
    if metadata["profile"]["package"] != profile_package:
        raise SystemExit("unexpected profile package name")
    if metadata["profile"]["version"] != version or metadata["profile"]["architecture"] != "arm64":
        raise SystemExit("unexpected profile package version or architecture")
    if f"hidloom-core (= {version})" not in metadata["profile"]["depends"]:
        raise SystemExit("profile package does not depend on the exact core version")
    paths = (bundle, core, profile)
    sidecars = [verify_sidecar(path) for path in paths]
    artifacts = [
        artifact(bundle, "release-bundle"),
        artifact(core, "raspberry-pi-os-core-package"),
        artifact(profile, "raspberry-pi-os-device-profile-package"),
    ] + [artifact(path, "sha256-sidecar") for path in sidecars]
    return {
        "ready": True,
        "profile_id": profile_id,
        "version": version,
        "source_mode": bundle_data["source_mode"],
        "package_manifest": bundle_data,
        "metadata": metadata,
        "artifacts": sorted(artifacts, key=lambda item: item["name"]),
    }


def git_value(repository: Path, *arguments: str) -> str:
    return run(["git", "-C", str(repository), *arguments])


def tree_digest(root: Path) -> dict[str, Any]:
    entries = []
    for path in sorted(item for item in root.rglob("*") if item.is_file() or item.is_symlink()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            content = path.readlink().as_posix().encode()
            kind = "symlink"
        else:
            content = path.read_bytes()
            kind = "file"
        entries.append(
            {
                "path": relative,
                "kind": kind,
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    encoded = json.dumps(entries, ensure_ascii=False, separators=(",", ":")).encode()
    return {"files": len(entries), "sha256": hashlib.sha256(encoded).hexdigest()}


def collect_buildroot(
    root: Path,
    source_directory: Path,
    output: Path,
    *,
    image: bool,
) -> dict[str, Any]:
    source_lock = load_json(root / "config/buildroot-source.json")
    commit = git_value(source_directory, "rev-parse", "HEAD")
    origin = git_value(source_directory, "remote", "get-url", "origin")
    dirty = git_value(source_directory, "status", "--porcelain", "--untracked-files=no")
    if commit != source_lock["commit"] or origin != source_lock["repository"] or dirty:
        raise SystemExit("Buildroot checkout does not match the pinned clean source")
    config = output / ".config"
    if not config.is_file():
        raise SystemExit(f"Buildroot output config is missing: {config}")
    config_text = config.read_text(encoding="utf-8")
    missing_symbols = [symbol for symbol in M6_SYMBOLS if symbol not in config_text]
    if missing_symbols:
        raise SystemExit("Buildroot M6 config is missing symbols: " + ", ".join(missing_symbols))
    external = str((root / "build/buildroot/hidloom-external").resolve())
    if external not in config_text:
        raise SystemExit("Buildroot output is not configured from this public source tree")
    payload: dict[str, Any] = {
        "ready": True,
        "mode": "image" if image else "configure",
        "source": {
            "repository": source_lock["repository"],
            "commit": commit,
            "clean": True,
        },
        "configuration": {
            "name": ".config",
            "size": config.stat().st_size,
            "sha256": sha256(config),
            "defconfig_sha256": sha256(
                root / "build/buildroot/hidloom-external/configs/hidloom_m6_defconfig"
            ),
            "required_symbols": list(M6_SYMBOLS),
            "external_source_match": True,
        },
        "verifiers": {"configure": True},
    }
    if image:
        verify_output = json.loads(
            run(["python3", str(root / "tools/buildroot_m6_verify.py"), "--output", str(output)])
        )
        run(["python3", str(root / "tools/buildroot_m6_import_smoke.py"), "--output", str(output)])
        run(["python3", str(root / "tools/buildroot_m6_runtime_smoke.py"), "--output", str(output)])
        runtime_root = output / "target/usr/share/hidloom"
        payload["image"] = artifact(output / "images/sdcard.img", "buildroot-m6-raw-image")
        payload["runtime_payload"] = tree_digest(runtime_root)
        payload["verification"] = {
            "schema": verify_output["schema"],
            "image_sha256": verify_output["sha256"],
            "required_files": verify_output["required_files"],
            "sudoers_mode": verify_output["sudoers_mode"],
            "boot_policy": verify_output["boot_policy"],
        }
        payload["verifiers"].update(
            {"artifact": True, "arm_python_import": True, "arm_runtime": True}
        )
    return payload


def collect(
    source_root: Path,
    mode: str,
    package_directory: Path | None,
    buildroot_source: Path | None,
    buildroot_output: Path | None,
    profile_id: str,
) -> dict[str, Any]:
    source = collect_source(source_root)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "ready": True,
        "mode": mode,
        "source": source,
        "packages": None,
        "buildroot": None,
    }
    if mode in PACKAGE_MODES:
        if package_directory is None:
            raise SystemExit("package mode requires --package-dir")
        payload["packages"] = collect_packages(
            source_root,
            package_directory,
            source,
            profile_id,
        )
    if mode in BUILDROOT_MODES:
        if buildroot_source is None or buildroot_output is None:
            raise SystemExit("Buildroot mode requires --buildroot-source and --buildroot-output")
        payload["buildroot"] = collect_buildroot(
            source_root,
            buildroot_source,
            buildroot_output,
            image=mode in IMAGE_MODES,
        )
    return payload


def add_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--package-dir", type=Path)
    parser.add_argument("--profile", default="keyboard-ver1")
    parser.add_argument("--buildroot-source", type=Path)
    parser.add_argument("--buildroot-output", type=Path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect_parser = subparsers.add_parser("collect")
    add_inputs(collect_parser)
    collect_parser.add_argument(
        "--mode",
        required=True,
        choices=("package", "buildroot-configure", "buildroot-image", "all"),
    )
    collect_parser.add_argument("--output", type=Path, required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("report", type=Path)
    add_inputs(verify_parser)
    args = parser.parse_args()
    if args.command == "verify":
        expected = load_json(args.report.resolve())
        if expected.get("schema") != SCHEMA:
            raise SystemExit("unsupported public build provenance schema")
        actual = collect(
            args.source.resolve(),
            str(expected["mode"]),
            args.package_dir.resolve() if args.package_dir else None,
            args.buildroot_source.resolve() if args.buildroot_source else None,
            args.buildroot_output.resolve() if args.buildroot_output else None,
            args.profile,
        )
        if actual != expected:
            raise SystemExit("public build provenance does not match current source/artifacts")
        print(f"ok: verified public build provenance ({expected['mode']})")
        return
    payload = collect(
        args.source.resolve(),
        args.mode,
        args.package_dir.resolve() if args.package_dir else None,
        args.buildroot_source.resolve() if args.buildroot_source else None,
        args.buildroot_output.resolve() if args.buildroot_output else None,
        args.profile,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
