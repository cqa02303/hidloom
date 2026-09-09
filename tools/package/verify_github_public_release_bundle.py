#!/usr/bin/env python3
"""Download and deeply verify a HIDloom public GitHub Release bundle."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from public_export_manifest import (  # noqa: E402
    MANIFEST_NAME, REPORT_NAME, HEX40_RE, bind_release_source,
    export_source_identity, safe_relative, verification_issues,
    verify as verify_export, verify_git_commit,
)
SAFE_NAME = re.compile(r"^[A-Za-z0-9._+~-]+$")
SAFE_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
BINARY_RELEASE_CHANNELS = ("internal-rc", "stable-public")


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"invalid JSON file: {path}: {error}") from error
    if not isinstance(payload, dict):
        raise SystemExit(f"JSON root must be an object: {path}")
    return payload


def checksum_names(directory: Path) -> list[str]:
    checksum_path = directory / "SHA256SUMS"
    if not checksum_path.is_file():
        raise SystemExit(f"release bundle lacks SHA256SUMS: {directory}")
    names: list[str] = []
    for line_number, line in enumerate(
        checksum_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._+~-]+)", line)
        if not match:
            raise SystemExit(f"invalid SHA256SUMS entry at line {line_number}")
        expected, name = match.groups()
        if name in names:
            raise SystemExit(f"duplicate SHA256SUMS entry: {name}")
        path = directory / name
        if not path.is_file():
            raise SystemExit(f"missing release asset: {name}")
        if sha256(path) != expected:
            raise SystemExit(f"checksum mismatch: {name}")
        names.append(name)
    local_names = sorted(path.name for path in directory.iterdir() if path.is_file())
    if sorted([*names, "SHA256SUMS"]) != local_names:
        raise SystemExit("downloaded directory contains unlisted or missing release assets")
    return names


def archive_root(archive: Path) -> str:
    listed = run(["tar", "--zstd", "-tf", str(archive)])
    if listed.returncode != 0:
        raise SystemExit(listed.stderr.strip() or f"cannot list source archive: {archive}")
    roots: set[str] = set()
    for raw in listed.stdout.splitlines():
        value = raw.rstrip("/")
        if not value:
            continue
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise SystemExit(f"unsafe source archive member: {raw}")
        roots.add(path.parts[0])
    if len(roots) != 1:
        raise SystemExit("source archive must contain exactly one top-level directory")
    return next(iter(roots))


def extract_verified_source(archive: Path, destination: Path) -> tuple[Path, dict[str, str]]:
    """Extract only the exact manifest's regular files/symlinks, before running code."""
    decompressed = subprocess.run(["zstd", "-d", "-c", str(archive)], capture_output=True)
    if decompressed.returncode:
        raise SystemExit("cannot decompress corresponding source")
    try:
        with tarfile.open(fileobj=io.BytesIO(decompressed.stdout)) as tar:
            members = tar.getmembers()
            names = [item.name.rstrip("/") for item in members]
            if len(names) != len(set(names)):
                raise SystemExit("duplicate corresponding-source archive member")
            for name in names:
                safe_relative(name)
            roots = {PurePosixPath(name).parts[0] for name in names}
            if len(roots) != 1:
                raise SystemExit("source archive must contain exactly one top-level directory")
            root_name = next(iter(roots))
            prefix = root_name + "/"
            files = {item.name[len(prefix):]: item for item in members if not item.isdir() and item.name.startswith(prefix)}
            if len(files) != sum(not item.isdir() for item in members):
                raise SystemExit("source archive has an invalid root entry")
            manifest_entry = files.get(MANIFEST_NAME)
            if manifest_entry is None or not manifest_entry.isfile() or manifest_entry.mode != 0o644:
                raise SystemExit("source archive lacks a regular export manifest")
            manifest_stream = tar.extractfile(manifest_entry)
            assert manifest_stream is not None
            manifest_bytes = manifest_stream.read()
            manifest = json.loads(manifest_bytes)
            listed = manifest["files"]
            paths = [str(item["path"]) for item in listed]
            if (MANIFEST_NAME in paths or REPORT_NAME not in paths or len(paths) != len(set(paths))
                    or set(files) != set(paths) | {MANIFEST_NAME}):
                raise SystemExit("source archive differs from exact export path set")
            expected = {item["path"]: item for item in listed}
            source_root = destination / root_name
            source_root.mkdir()
            for relative, member in files.items():
                safe_relative(relative)
                if any(parent.as_posix() in files for parent in PurePosixPath(relative).parents if parent.as_posix() != "."):
                    raise SystemExit("source archive has a file/symlink ancestor")
                item = expected.get(relative, {"kind": "file", "mode": 0o644})
                kind = "symlink" if member.issym() else "file" if member.isfile() else "unsupported"
                if kind != item["kind"] or member.mode != item["mode"]:
                    raise SystemExit(f"source archive mode/kind mismatch: {relative}")
                path = source_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                if member.issym():
                    safe_relative(member.linkname)
                    path.symlink_to(member.linkname)
                else:
                    content = tar.extractfile(member)
                    assert content is not None
                    path.write_bytes(content.read())
                    path.chmod(member.mode)
    except (tarfile.TarError, ValueError, KeyError, TypeError) as error:
        raise SystemExit(f"invalid corresponding-source archive: {error}") from error
    verified = verify_export(source_root)
    if not verified["ready"]:
        raise SystemExit("corresponding source export failed verification: " + ", ".join(verification_issues(verified)))
    return source_root, export_source_identity(verified)


def deep_verify(
    directory: Path,
    *,
    require_publication_ready: bool,
    require_hardware_pass: bool,
    require_channel_ready: str | None,
) -> dict[str, Any]:
    names = checksum_names(directory)
    manifest = load_json(directory / "RELEASE_MANIFEST.json")
    if manifest.get("schema") != "hidloom.public-release-bundle.v5":
        raise SystemExit("unsupported public release bundle schema")
    source_assets = [
        item
        for item in manifest.get("assets", [])
        if isinstance(item, dict) and item.get("role") == "corresponding-source"
    ]
    if len(source_assets) != 1:
        raise SystemExit("release manifest must contain one corresponding-source asset")
    source_name = str(source_assets[0].get("path", ""))
    if not SAFE_NAME.fullmatch(source_name) or source_name not in names:
        raise SystemExit("unsafe or unlisted corresponding-source asset")
    source_archive = directory / source_name
    source_asset = source_assets[0]
    if source_asset.get("sha256") != sha256(source_archive) or source_asset.get("size") != source_archive.stat().st_size:
        raise SystemExit("corresponding-source asset does not match release manifest")
    with tempfile.TemporaryDirectory(prefix="hidloom-release-source-") as temporary:
        extracted = Path(temporary)
        source_root, source_mapping = extract_verified_source(source_archive, extracted)
        bind_release_source(source_mapping, manifest.get("source") or {})
        verifier = source_root / "tools" / "public_release_bundle.py"
        if not verifier.is_file():
            raise SystemExit("corresponding source lacks public_release_bundle.py")
        command = [sys.executable, str(verifier), "--verify", str(directory)]
        if require_publication_ready:
            command.append("--require-publication-ready")
        if require_hardware_pass:
            command.append("--require-hardware-pass")
        if require_channel_ready is not None:
            command.extend(["--require-channel-ready", require_channel_ready])
        verified = run(command, cwd=verifier.parents[1])
        if verified.returncode != 0:
            raise SystemExit(verified.stderr.strip() or verified.stdout.strip())
    return {
        "schema": "hidloom.github-public-release-verification.v1",
        "version": manifest["version"],
        "source_commit": manifest["source"]["commit"],
        "source_mapping": source_mapping,
        "source_asset": source_asset,
        "public_target_verification": "not-requested",
        "asset_count": len(names) + 1,
        "publication_ready": manifest["publication"]["ready"],
        "release_channel": manifest["release_channels"],
        "hardware_smoke": manifest["hardware_smoke"],
        "touch_hardware_smoke": manifest.get("touch_hardware_smoke"),
    }


def api_json(endpoint: str) -> dict[str, Any]:
    result = run(["gh", "api", endpoint])
    if result.returncode:
        raise SystemExit(result.stderr.strip() or f"GitHub API failed: {endpoint}")
    try:
        payload = json.loads(result.stdout)
    except ValueError as error:
        raise SystemExit("GitHub API returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise SystemExit("GitHub API returned a non-object")
    return payload


def resolve_release_tag(repository: str, tag: str) -> str:
    """Resolve lightweight or annotated tags; targetCommitish is not tag evidence."""
    if not SAFE_REPOSITORY.fullmatch(repository) or not SAFE_NAME.fullmatch(tag):
        raise SystemExit("unsafe release repository/tag")
    payload = api_json(f"repos/{repository}/git/ref/tags/{tag}")
    if payload.get("ref") != f"refs/tags/{tag}":
        raise SystemExit("GitHub returned a different tag ref")
    target = payload.get("object") or {}
    seen: set[str] = set()
    for _ in range(16):
        oid = str(target.get("sha", ""))
        if not HEX40_RE.fullmatch(oid) or oid in seen:
            raise SystemExit("invalid or cyclic Git tag object")
        seen.add(oid)
        if target.get("type") == "commit":
            return oid
        if target.get("type") != "tag":
            raise SystemExit("Git tag does not target a commit")
        annotation = api_json(f"repos/{repository}/git/tags/{oid}")
        if annotation.get("sha") != oid:
            raise SystemExit("annotated Git tag object mismatch")
        target = annotation.get("object") or {}
    raise SystemExit("Git tag annotation chain is too deep")


def verify_remote_target(repository: str, tag: str, result: dict[str, Any],
                         expected_target: dict[str, Any] | None = None) -> dict[str, str]:
    commit = resolve_release_tag(repository, tag)
    if expected_target is not None and (expected_target.get("repository") != repository or expected_target.get("commit") != commit):
        raise SystemExit("release tag does not match expected public target")
    with tempfile.TemporaryDirectory(prefix="hidloom-public-tag-") as temporary:
        checkout = Path(temporary)
        for command in (["git", "init", "--quiet", str(checkout)],
                        ["git", "-C", str(checkout), "fetch", "--quiet", "--depth=1",
                         f"https://github.com/{repository}.git", commit]):
            fetched = run(command)
            if fetched.returncode:
                raise SystemExit(fetched.stderr.strip() or "cannot fetch public tag commit")
        mapping = {"repository": repository, **verify_git_commit(checkout, commit)}
    source_mapping = result["source_mapping"]
    if any(mapping.get(key) != value for key, value in source_mapping.items()):
        raise SystemExit("public tag tree differs from corresponding source")
    if expected_target is not None and mapping != expected_target:
        raise SystemExit("release public target mapping changed")
    if resolve_release_tag(repository, tag) != commit:
        raise SystemExit("release tag moved during verification")
    return mapping


def release_asset_names(tag: str, repository: str) -> tuple[list[str], dict[str, Any]]:
    viewed = run(
        [
            "gh",
            "release",
            "view",
            tag,
            "--repo",
            repository,
            "--json",
            "assets,isDraft,isPrerelease,tagName,targetCommitish",
        ]
    )
    if viewed.returncode != 0:
        raise SystemExit(viewed.stderr.strip() or f"cannot read GitHub Release: {tag}")
    try:
        metadata = json.loads(viewed.stdout)
    except json.JSONDecodeError as error:
        raise SystemExit("gh release view returned invalid JSON") from error
    names = [str(item.get("name", "")) for item in metadata.get("assets", [])]
    if not names or len(names) != len(set(names)) or any(not SAFE_NAME.fullmatch(name) for name in names):
        raise SystemExit("GitHub Release has unsafe, duplicate, or missing asset names")
    return names, metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--bundle", type=Path, help="verify an existing local release directory")
    source.add_argument("--tag", help="download and verify this GitHub Release tag")
    parser.add_argument("--repository", default="cqa02303/hidloom")
    parser.add_argument("--dir", type=Path, help="download directory; must be empty")
    parser.add_argument("--keep", action="store_true", help="keep an automatic download directory")
    parser.add_argument("--require-publication-ready", action="store_true")
    parser.add_argument("--require-hardware-pass", action="store_true")
    parser.add_argument("--require-channel-ready", choices=BINARY_RELEASE_CHANNELS)
    parser.add_argument("--expected-plan", type=Path, help="require exact v3 publication target and asset digests on readback")
    args = parser.parse_args()
    expected_plan = load_json(args.expected_plan) if args.expected_plan else None
    if expected_plan is not None and (
        args.tag is None or expected_plan.get("schema") != "hidloom.public-release-publish-plan.v3"
        or expected_plan.get("repository") != args.repository or expected_plan.get("tag") != args.tag
    ):
        raise SystemExit("expected publication plan must be v3 and match this repository/tag")

    remote_names: list[str] | None = None
    metadata: dict[str, Any] | None = None
    cleanup: Path | None = None
    if args.bundle:
        directory = args.bundle.resolve()
    else:
        if shutil.which("gh") is None:
            raise SystemExit("missing command: gh")
        if "/" not in args.repository:
            raise SystemExit("repository must use OWNER/REPO form")
        remote_names, metadata = release_asset_names(args.tag, args.repository)
        if args.dir:
            directory = args.dir.resolve()
            directory.mkdir(parents=True, exist_ok=True)
            if any(directory.iterdir()):
                raise SystemExit(f"download directory must be empty: {directory}")
        else:
            directory = Path(tempfile.mkdtemp(prefix="hidloom-release-download-"))
            if not args.keep:
                cleanup = directory
        downloaded = run(
            [
                "gh",
                "release",
                "download",
                args.tag,
                "--repo",
                args.repository,
                "--dir",
                str(directory),
            ]
        )
        if downloaded.returncode != 0:
            if cleanup:
                shutil.rmtree(cleanup, ignore_errors=True)
            raise SystemExit(downloaded.stderr.strip() or "GitHub Release download failed")

    try:
        result = deep_verify(
            directory,
            require_publication_ready=args.require_publication_ready or args.tag is not None,
            require_hardware_pass=args.require_hardware_pass or args.tag is not None,
            require_channel_ready=(
                args.require_channel_ready
                or ("stable-public" if args.tag is not None else None)
            ),
        )
        if remote_names is not None:
            local_names = sorted(path.name for path in directory.iterdir() if path.is_file())
            if sorted(remote_names) != local_names:
                raise SystemExit("GitHub Release asset list differs from downloaded files")
            result["repository"] = args.repository
            result["tag"] = args.tag
            result["release"] = metadata
            if metadata is None or metadata.get("tagName") != args.tag:
                raise SystemExit("GitHub Release tag metadata mismatch")
            if expected_plan is not None:
                actual = {name: sha256(directory / name) for name in local_names}
                if expected_plan.get("asset_sha256") != actual:
                    raise SystemExit("release assets differ from expected publication plan")
            result["public_target"] = verify_remote_target(
                args.repository, args.tag, result,
                expected_plan["public_target"] if expected_plan is not None else None,
            )
            result["public_target_verification"] = "passed"
        result["directory"] = str(directory)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        if cleanup:
            shutil.rmtree(cleanup, ignore_errors=True)


if __name__ == "__main__":
    main()
