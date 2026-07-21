#!/usr/bin/env python3
"""Download and deeply verify a HIDloom public GitHub Release bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SAFE_NAME = re.compile(r"^[A-Za-z0-9._+~-]+$")
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
    root_name = archive_root(source_archive)
    with tempfile.TemporaryDirectory(prefix="hidloom-release-source-") as temporary:
        extracted = Path(temporary)
        unpacked = run(["tar", "--zstd", "-xf", str(source_archive), "-C", str(extracted)])
        if unpacked.returncode != 0:
            raise SystemExit(unpacked.stderr.strip() or "cannot extract corresponding source")
        verifier = extracted / root_name / "tools" / "public_release_bundle.py"
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
        "asset_count": len(names) + 1,
        "publication_ready": manifest["publication"]["ready"],
        "release_channel": manifest["release_channels"],
        "hardware_smoke": manifest["hardware_smoke"],
        "touch_hardware_smoke": manifest.get("touch_hardware_smoke"),
    }


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
    args = parser.parse_args()

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
        result["directory"] = str(directory)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        if cleanup:
            shutil.rmtree(cleanup, ignore_errors=True)


if __name__ == "__main__":
    main()
