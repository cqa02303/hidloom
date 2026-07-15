#!/usr/bin/env python3
"""Lock, build, and verify Buildroot binary-distribution compliance bundles."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

sys.dont_write_bytecode = True

from summarize_buildroot_legal_info import summarize

ROOT = Path(__file__).resolve().parents[1]
LOCK_SCHEMA = "hidloom.bootlin-toolchain-components.v1"
BUNDLE_SCHEMA = "hidloom.buildroot-compliance-bundle.v1"
BUNDLE_ROOT = "hidloom-buildroot-m6-compliance"
KNOWN_RELEASE_BLOCKERS = {
    "buildroot-source-not-bundled",
    "bootlin-toolchain-compliance-not-bundled",
}
REQUIRED_BUNDLE_ROLES = {
    "buildroot-legal-info",
    "hidloom-buildroot-source",
    "bootlin-official-evidence",
    "bootlin-component-source",
    "bootlin-license-text",
    "bootlin-buildroot-source",
    "resolved-legal-summary",
    "compliance-configuration",
}
HEX_SHA256 = re.compile(r"[0-9a-f]{64}")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise SystemExit(f"unsafe relative path: {value!r}")
    return value


def evidence_config(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    if payload.get("schema") != "hidloom.buildroot-toolchain-evidence.v2":
        raise SystemExit(f"unsupported toolchain evidence config: {path}")
    for field in ("package", "version", "archive", "archive_sha256"):
        if not payload.get(field):
            raise SystemExit(f"toolchain evidence is missing {field}: {path}")
    if not HEX_SHA256.fullmatch(str(payload["archive_sha256"])):
        raise SystemExit(f"invalid toolchain archive hash: {path}")
    official = payload.get("official_evidence", {})
    for field in ("readme", "readme_sha256", "summary", "summary_sha256", "sources", "licenses"):
        if not official.get(field):
            raise SystemExit(f"toolchain evidence is missing official_evidence.{field}: {path}")
    builder = payload.get("builder_source", {})
    for field in ("repository", "ref", "commit"):
        if not builder.get(field):
            raise SystemExit(f"toolchain evidence is missing builder_source.{field}: {path}")
    if not re.fullmatch(r"[0-9a-f]{40}", str(builder["commit"])):
        raise SystemExit(f"invalid Bootlin builder commit: {path}")
    return payload


def source_config(path: Path) -> dict[str, str]:
    payload = load_json(path)
    if payload.get("schema") != "hidloom.buildroot-source.v1":
        raise SystemExit(f"unsupported Buildroot source config: {path}")
    repository = str(payload.get("repository", ""))
    commit = str(payload.get("commit", ""))
    if not repository or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise SystemExit(f"invalid Buildroot source config: {path}")
    return {"repository": repository, "commit": commit}


def encoded_path(value: str) -> str:
    return "/".join(quote(part, safe="-._~") for part in PurePosixPath(value).parts)


def official_url(base: str, component: str, relative: str) -> str:
    return f"{base.rstrip('/')}/{encoded_path(component)}/{encoded_path(relative)}"


def license_component_id(component: dict[str, Any]) -> str:
    if component["name"] == "buildroot" and component["source_archive_name"] == "not saved":
        return "buildroot"
    return f"{component['name']}-{component['version']}"


def download(url: str, destination: Path) -> tuple[str, int]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    digest = hashlib.sha256()
    size = 0
    request = Request(url, headers={"User-Agent": "HIDloom compliance evidence/1"})
    try:
        try:
            response = urlopen(request, timeout=180)
        except Exception as error:
            raise SystemExit(f"unable to download compliance evidence: {url}: {error}") from error
        with response, temporary.open("wb") as stream:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                stream.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return digest.hexdigest(), size


def cached_url(cache: Path, url: str, refresh: bool) -> tuple[Path, str, int]:
    destination = cache / "urls" / hashlib.sha256(url.encode()).hexdigest()
    if refresh:
        destination.unlink(missing_ok=True)
    if destination.is_file():
        return destination, sha256(destination), destination.stat().st_size
    digest, size = download(url, destination)
    return destination, digest, size


def pinned_object(
    cache: Path,
    url: str,
    expected_sha256: str,
    expected_size: int | None,
    fetch_missing: bool,
) -> Path:
    if not HEX_SHA256.fullmatch(expected_sha256):
        raise SystemExit(f"invalid pinned object hash for {url}")
    destination = cache / "objects" / expected_sha256
    valid = (
        destination.is_file()
        and sha256(destination) == expected_sha256
        and (expected_size is None or destination.stat().st_size == expected_size)
    )
    if valid:
        return destination
    if destination.exists():
        destination.unlink()
    if not fetch_missing:
        raise SystemExit(f"verified compliance object is missing: {expected_sha256} ({url})")
    digest, size = download(url, destination)
    if digest != expected_sha256 or (expected_size is not None and size != expected_size):
        destination.unlink(missing_ok=True)
        raise SystemExit(f"downloaded compliance object does not match lock: {url}")
    return destination


def merged_summary_rows(content: bytes) -> list[dict[str, Any]]:
    rows = list(csv.DictReader(io.StringIO(content.decode("utf-8"))))
    expected = {
        "PACKAGE",
        "VERSION",
        "LICENSE",
        "LICENSE FILES",
        "SOURCE ARCHIVE",
        "SOURCE SITE",
        "DEPENDENCIES WITH LICENSES",
    }
    if not rows or set(rows[0]) != expected:
        raise SystemExit("unsupported Bootlin summary columns")
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["PACKAGE"], row["VERSION"])
        current = merged.setdefault(
            key,
            {
                "name": row["PACKAGE"],
                "version": row["VERSION"],
                "summary_occurrences": 0,
                "licenses": set(),
                "license_file_names": set(),
                "source_archive_name": row["SOURCE ARCHIVE"],
                "source_site": row["SOURCE SITE"],
            },
        )
        if current["source_archive_name"] != row["SOURCE ARCHIVE"]:
            raise SystemExit(f"conflicting source archives in Bootlin summary: {key}")
        current["summary_occurrences"] += 1
        current["licenses"].add(row["LICENSE"])
        current["license_file_names"].update(row["LICENSE FILES"].split())
    return [merged[key] for key in sorted(merged)]


def lock_toolchain(args: argparse.Namespace) -> None:
    config = evidence_config(args.toolchain_evidence.resolve())
    verify_remote_builder_ref(config["builder_source"])
    official = config["official_evidence"]
    cache = args.cache.resolve()
    readme_path, readme_digest, readme_size = cached_url(cache, official["readme"], args.refresh)
    summary_path, summary_digest, summary_size = cached_url(cache, official["summary"], args.refresh)
    if readme_digest != official["readme_sha256"]:
        raise SystemExit("Bootlin README does not match pinned SHA-256")
    if summary_digest != official["summary_sha256"]:
        raise SystemExit("Bootlin summary does not match pinned SHA-256")
    for path, digest in ((readme_path, readme_digest), (summary_path, summary_digest)):
        object_path = cache / "objects" / digest
        object_path.parent.mkdir(parents=True, exist_ok=True)
        if not object_path.exists():
            try:
                os.link(path, object_path)
            except OSError:
                shutil.copy2(path, object_path)
    components = merged_summary_rows(summary_path.read_bytes())
    urls: set[str] = set()
    for component in components:
        component_id = f"{component['name']}-{component['version']}"
        if component["source_archive_name"] != "not saved":
            urls.add(
                official_url(
                    official["sources"], component_id, component["source_archive_name"]
                )
            )
        for name in component["license_file_names"]:
            urls.add(official_url(official["licenses"], license_component_id(component), name))

    def fetch(url: str) -> tuple[str, dict[str, Any]]:
        path, digest, size = cached_url(cache, url, args.refresh)
        object_path = cache / "objects" / digest
        object_path.parent.mkdir(parents=True, exist_ok=True)
        if not object_path.exists():
            try:
                os.link(path, object_path)
            except OSError:
                shutil.copy2(path, object_path)
        return url, {"sha256": digest, "size": size, "url": url}

    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        fetched = dict(executor.map(fetch, sorted(urls)))

    locked_components = []
    for component in components:
        component_id = f"{component['name']}-{component['version']}"
        source = None
        if component["source_archive_name"] != "not saved":
            url = official_url(
                official["sources"], component_id, component["source_archive_name"]
            )
            source = {"name": component["source_archive_name"], **fetched[url]}
        license_files = []
        for name in sorted(component["license_file_names"]):
            url = official_url(official["licenses"], license_component_id(component), name)
            license_files.append({"name": name, **fetched[url]})
        locked_components.append(
            {
                "name": component["name"],
                "version": component["version"],
                "summary_occurrences": component["summary_occurrences"],
                "licenses": sorted(component["licenses"]),
                "source": source,
                "source_site": component["source_site"],
                "license_files": license_files,
            }
        )
    payload = {
        "schema": LOCK_SCHEMA,
        "toolchain": {
            "package": config["package"],
            "version": config["version"],
            "archive": config["archive"],
            "archive_sha256": config["archive_sha256"],
        },
        "official_evidence": {
            "readme": {
                "url": official["readme"],
                "sha256": readme_digest,
                "size": readme_size,
            },
            "summary": {
                "url": official["summary"],
                "sha256": summary_digest,
                "size": summary_size,
            },
        },
        "builder_source": config["builder_source"],
        "components": locked_components,
        "summary": {
            "summary_rows": sum(item["summary_occurrences"] for item in locked_components),
            "components": len(locked_components),
            "source_archives": sum(item["source"] is not None for item in locked_components),
            "license_files": sum(len(item["license_files"]) for item in locked_components),
            "unique_objects": len(
                {
                    artifact["sha256"]
                    for item in locked_components
                    for artifact in ([item["source"]] if item["source"] else [])
                    + item["license_files"]
                }
            ),
        },
    }
    validate_lock(payload, config)
    validate_lock_summary(payload, summary_path.read_bytes(), config)
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output.resolve(), payload)
    print(json.dumps(payload["summary"], sort_keys=True))


def validate_artifact(item: dict[str, Any], label: str) -> None:
    if not item.get("url") or not HEX_SHA256.fullmatch(str(item.get("sha256", ""))):
        raise SystemExit(f"invalid locked artifact: {label}")
    if not isinstance(item.get("size"), int) or item["size"] <= 0:
        raise SystemExit(f"invalid locked artifact size: {label}")


def validate_lock(payload: dict[str, Any], config: dict[str, Any]) -> None:
    if payload.get("schema") != LOCK_SCHEMA:
        raise SystemExit("unsupported Bootlin component lock schema")
    expected_toolchain = {
        "package": config["package"],
        "version": config["version"],
        "archive": config["archive"],
        "archive_sha256": config["archive_sha256"],
    }
    if payload.get("toolchain") != expected_toolchain:
        raise SystemExit("Bootlin component lock does not match the toolchain config")
    if payload.get("builder_source") != config["builder_source"]:
        raise SystemExit("Bootlin component lock builder source mismatch")
    official = payload.get("official_evidence", {})
    for name in ("readme", "summary"):
        validate_artifact(official.get(name, {}), f"official {name}")
        expected = config["official_evidence"]
        if official[name]["url"] != expected[name] or official[name]["sha256"] != expected[
            f"{name}_sha256"
        ]:
            raise SystemExit(f"Bootlin component lock {name} mismatch")
    components = payload.get("components")
    if not isinstance(components, list) or not components:
        raise SystemExit("Bootlin component lock has no components")
    keys = []
    for component in components:
        key = (component.get("name"), component.get("version"))
        keys.append(key)
        if not all(isinstance(value, str) and value for value in key):
            raise SystemExit("Bootlin component lock has an invalid component")
        if component.get("source") is not None:
            validate_artifact(component["source"], f"{key} source")
            if not component["source"]["url"].startswith(
                config["official_evidence"]["sources"]
            ):
                raise SystemExit(f"locked source URL is outside the official base: {key}")
        names = set()
        for license_file in component.get("license_files", []):
            safe_relative(str(license_file.get("name", "")))
            if license_file["name"] in names:
                raise SystemExit(f"duplicate locked license file: {key} {license_file['name']}")
            names.add(license_file["name"])
            validate_artifact(license_file, f"{key} license {license_file['name']}")
            if not license_file["url"].startswith(config["official_evidence"]["licenses"]):
                raise SystemExit(f"locked license URL is outside the official base: {key}")
    if keys != sorted(set(keys)):
        raise SystemExit("Bootlin component lock is unsorted or has duplicate components")
    summary = payload.get("summary", {})
    artifacts = [
        artifact
        for component in components
        for artifact in ([component["source"]] if component["source"] else [])
        + component["license_files"]
    ]
    expected_summary = {
        "summary_rows": sum(item["summary_occurrences"] for item in components),
        "components": len(components),
        "source_archives": sum(item["source"] is not None for item in components),
        "license_files": sum(len(item["license_files"]) for item in components),
        "unique_objects": len({item["sha256"] for item in artifacts}),
    }
    if summary != expected_summary:
        raise SystemExit("Bootlin component lock summary is stale")


def validate_lock_summary(
    payload: dict[str, Any], summary_content: bytes, config: dict[str, Any]
) -> None:
    expected = merged_summary_rows(summary_content)
    actual = {(item["name"], item["version"]): item for item in payload["components"]}
    if set(actual) != {(item["name"], item["version"]) for item in expected}:
        raise SystemExit("Bootlin component lock does not match official summary components")
    official = config["official_evidence"]
    for item in expected:
        key = (item["name"], item["version"])
        locked = actual[key]
        expected_source = None
        component_id = f"{item['name']}-{item['version']}"
        if item["source_archive_name"] != "not saved":
            expected_source = {
                "name": item["source_archive_name"],
                "url": official_url(
                    official["sources"], component_id, item["source_archive_name"]
                ),
            }
        actual_source = locked["source"]
        if expected_source is None:
            if actual_source is not None:
                raise SystemExit(f"unexpected locked source for Bootlin component: {key}")
        elif actual_source is None or any(
            actual_source.get(field) != value for field, value in expected_source.items()
        ):
            raise SystemExit(f"locked source does not match Bootlin summary: {key}")
        expected_licenses = {
            name: official_url(official["licenses"], license_component_id(item), name)
            for name in item["license_file_names"]
        }
        actual_licenses = {entry["name"]: entry["url"] for entry in locked["license_files"]}
        if actual_licenses != expected_licenses:
            raise SystemExit(f"locked licenses do not match Bootlin summary: {key}")
        if (
            locked["licenses"] != sorted(item["licenses"])
            or locked["source_site"] != item["source_site"]
            or locked["summary_occurrences"] != item["summary_occurrences"]
        ):
            raise SystemExit(f"locked metadata does not match Bootlin summary: {key}")


def run_git(*arguments: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(
        ["git", *arguments], cwd=cwd, text=True, stderr=subprocess.STDOUT
    ).strip()


def verify_remote_builder_ref(builder: dict[str, str]) -> None:
    output = run_git(
        "ls-remote",
        builder["repository"],
        builder["ref"],
        f"{builder['ref']}^{{}}",
    )
    commits = {line.split()[0] for line in output.splitlines() if line.strip()}
    if builder["commit"] not in commits:
        raise SystemExit(
            f"Bootlin builder ref does not resolve to pinned commit: {builder['ref']}"
        )


def prepare_checkout(
    destination: Path,
    repository: str,
    commit: str,
    fetch_missing: bool,
) -> None:
    if not (destination / ".git").is_dir():
        if not fetch_missing:
            raise SystemExit(f"source checkout is missing: {destination}")
        if destination.exists() and any(destination.iterdir()):
            raise SystemExit(f"refusing to replace non-empty source checkout: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.mkdir(exist_ok=True)
        subprocess.run(["git", "init", "-q", str(destination)], check=True)
        subprocess.run(
            ["git", "-C", str(destination), "remote", "add", "origin", repository], check=True
        )
        subprocess.run(
            ["git", "-C", str(destination), "fetch", "--depth", "1", "origin", commit],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(destination), "checkout", "-q", "--detach", "FETCH_HEAD"],
            check=True,
        )
    actual = run_git("rev-parse", "HEAD", cwd=destination)
    if actual != commit:
        raise SystemExit(f"source checkout revision mismatch: expected {commit}, got {actual}")
    if run_git("status", "--porcelain", "--untracked-files=no", cwd=destination):
        raise SystemExit(f"source checkout has tracked changes: {destination}")
    origin = run_git("remote", "get-url", "origin", cwd=destination)
    if origin != repository:
        raise SystemExit(f"source checkout origin mismatch: expected {repository}, got {origin}")


def git_source_archive(repository: Path, commit: str, prefix: str, destination: Path) -> None:
    with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".tar") as tar_stream:
        subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "archive",
                "--format=tar",
                f"--prefix={prefix}/",
                commit,
            ],
            stdout=tar_stream,
            check=True,
        )
        tar_stream.flush()
        tar_stream.seek(0)
        with destination.open("wb") as output, gzip.GzipFile(
            filename="", mode="wb", fileobj=output, mtime=0
        ) as compressed:
            shutil.copyfileobj(tar_stream, compressed, 1024 * 1024)


def checksum_entries(path: Path) -> dict[str, str]:
    entries = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as error:
            raise SystemExit(f"invalid checksum line in {path}: {line!r}") from error
        safe_relative(relative)
        if not HEX_SHA256.fullmatch(digest) or relative in entries:
            raise SystemExit(f"invalid checksum entry in {path}: {line!r}")
        entries[relative] = digest
    return entries


def verify_legal_info(legal_info: Path) -> dict[str, str]:
    required = ("README", "manifest.csv", "host-manifest.csv", "buildroot.config", "legal-info.sha256")
    missing = [name for name in required if not (legal_info / name).is_file()]
    if missing:
        raise SystemExit(f"Buildroot legal-info is incomplete: {missing}")
    entries = checksum_entries(legal_info / "legal-info.sha256")
    actual = set()
    for path in sorted(legal_info.rglob("*")):
        if path.is_symlink():
            raise SystemExit(f"Buildroot legal-info contains a symlink: {path}")
        if not path.is_file() or path.relative_to(legal_info).as_posix() in {
            "legal-info.sha256",
            "hidloom-summary.json",
        }:
            continue
        relative = path.relative_to(legal_info).as_posix()
        actual.add(relative)
        if entries.get(relative) != sha256(path):
            raise SystemExit(f"Buildroot legal-info checksum mismatch: {relative}")
    if set(entries) != actual:
        raise SystemExit("Buildroot legal-info checksum manifest does not cover every payload file")
    return entries


def link_or_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def copy_tree_files(source: Path, destination: Path) -> list[Path]:
    copied = []
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise SystemExit(f"source tree contains a symlink: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        target = destination / relative
        link_or_copy(path, target)
        copied.append(target)
    return copied


def object_path(digest: str) -> str:
    return f"bootlin/objects/sha256/{digest}"


def bundle_component_records(lock: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for component in lock["components"]:
        item = {
            "name": component["name"],
            "version": component["version"],
            "licenses": component["licenses"],
            "source_site": component["source_site"],
            "summary_occurrences": component["summary_occurrences"],
            "source": None,
            "license_files": [],
        }
        if component["source"]:
            artifact = component["source"]
            item["source"] = {**artifact, "object": object_path(artifact["sha256"])}
        item["license_files"] = [
            {**license_file, "object": object_path(license_file["sha256"])}
            for license_file in component["license_files"]
        ]
        records.append(item)
    return records


def readme_text(manifest: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# HIDloom Buildroot M6 Compliance Bundle",
            "",
            "This archive accompanies the Buildroot M6 binary image.",
            "It contains Buildroot legal-info, the exact HIDloom Buildroot source,",
            "Bootlin's official toolchain evidence, component sources and license texts,",
            "and the exact Bootlin Buildroot toolchain-builder source.",
            "",
            "Component files are content-addressed under `bootlin/objects/sha256/`.",
            "Use `COMPLIANCE_MANIFEST.json` to map each package and original filename",
            "to its object. Verify every file with `SHA256SUMS` before use.",
            "",
            f"- HIDloom Buildroot commit: `{manifest['buildroot_source']['commit']}`",
            f"- Bootlin builder commit: `{manifest['bootlin']['builder_source']['commit']}`",
            f"- Bootlin components: {manifest['summary']['bootlin_components']}",
            f"- Buildroot target packages: {manifest['summary']['target_packages']}",
            "- Binary release compliance: ready",
            "",
        ]
    )


def normalized_tar(source: Path, destination: Path) -> None:
    def normalize(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.uid = 0
        info.gid = 0
        info.uname = ""
        info.gname = ""
        info.mtime = 0
        info.mode = 0o755 if info.isdir() else 0o644
        return info

    with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".tar") as tar_stream:
        with tarfile.open(fileobj=tar_stream, mode="w", format=tarfile.PAX_FORMAT) as archive:
            root = tarfile.TarInfo(BUNDLE_ROOT)
            root.type = tarfile.DIRTYPE
            archive.addfile(normalize(root))
            for path in sorted(source.rglob("*")):
                relative = path.relative_to(source).as_posix()
                archive.add(
                    path,
                    arcname=f"{BUNDLE_ROOT}/{relative}",
                    recursive=False,
                    filter=normalize,
                )
        tar_stream.flush()
        subprocess.run(
            [
                "zstd",
                "-19",
                "-T0",
                "--no-progress",
                "-f",
                tar_stream.name,
                "-o",
                str(destination),
            ],
            check=True,
        )


def build_bundle(args: argparse.Namespace) -> None:
    legal_info = args.legal_info.resolve()
    output = args.output.resolve()
    config_path = args.toolchain_evidence.resolve()
    source_config_path = args.buildroot_source.resolve()
    config = evidence_config(config_path)
    source = source_config(source_config_path)
    lock = load_json(args.component_lock.resolve())
    validate_lock(lock, config)
    verify_legal_info(legal_info)
    if output.exists() and not args.force:
        raise SystemExit(f"compliance archive already exists: {output}; pass --force to replace it")
    output.parent.mkdir(parents=True, exist_ok=True)

    prepare_checkout(
        args.buildroot.resolve(), source["repository"], source["commit"], args.fetch_missing
    )
    builder = config["builder_source"]
    prepare_checkout(
        args.bootlin_buildroot.resolve(),
        builder["repository"],
        builder["commit"],
        args.fetch_missing,
    )
    buildroot_component = next(
        (item for item in lock["components"] if item["name"] == "buildroot"), None
    )
    if not buildroot_component or not buildroot_component["version"].endswith(builder["commit"][:10]):
        raise SystemExit("Bootlin builder commit does not match the official component summary")

    artifacts = [lock["official_evidence"]["readme"], lock["official_evidence"]["summary"]]
    for component in lock["components"]:
        if component["source"]:
            artifacts.append(component["source"])
        artifacts.extend(component["license_files"])
    unique_artifacts = {item["sha256"]: item for item in artifacts}

    def resolve(item: dict[str, Any]) -> tuple[str, Path]:
        return (
            item["sha256"],
            pinned_object(
                args.cache.resolve(),
                item["url"],
                item["sha256"],
                item["size"],
                args.fetch_missing,
            ),
        )

    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        objects = dict(executor.map(resolve, unique_artifacts.values()))
    validate_lock_summary(
        lock,
        objects[lock["official_evidence"]["summary"]["sha256"]].read_bytes(),
        config,
    )

    legal_summary = summarize(legal_info, source_config_path, config_path)
    if not legal_summary["source_audit_ready"]:
        raise SystemExit("Buildroot legal-info source audit is not ready")
    blocker_ids = {item["id"] for item in legal_summary["release_blockers"]}
    unknown = blocker_ids - KNOWN_RELEASE_BLOCKERS
    if unknown:
        raise SystemExit(f"Buildroot legal-info has unresolved blockers: {sorted(unknown)}")

    with tempfile.TemporaryDirectory(prefix="hidloom-compliance-", dir=output.parent) as temporary:
        stage = Path(temporary) / "stage"
        stage.mkdir()
        roles: dict[str, set[str]] = {}

        for path in copy_tree_files(legal_info, stage / "legal-info"):
            roles[path.relative_to(stage).as_posix()] = {"buildroot-legal-info"}

        sources = stage / "sources"
        sources.mkdir()
        buildroot_archive = sources / f"hidloom-buildroot-{source['commit']}.tar.gz"
        git_source_archive(
            args.buildroot.resolve(), source["commit"], f"buildroot-{source['commit']}", buildroot_archive
        )
        roles[buildroot_archive.relative_to(stage).as_posix()] = {"hidloom-buildroot-source"}
        builder_archive = sources / f"bootlin-buildroot-toolchains-{builder['commit']}.tar.gz"
        git_source_archive(
            args.bootlin_buildroot.resolve(),
            builder["commit"],
            f"buildroot-toolchains-{builder['commit']}",
            builder_archive,
        )
        roles[builder_archive.relative_to(stage).as_posix()] = {"bootlin-buildroot-source"}

        evidence_dir = stage / "bootlin" / "evidence"
        readme_destination = evidence_dir / "toolchain-readme.txt"
        summary_destination = evidence_dir / "toolchain-summary.csv"
        link_or_copy(objects[lock["official_evidence"]["readme"]["sha256"]], readme_destination)
        link_or_copy(objects[lock["official_evidence"]["summary"]["sha256"]], summary_destination)
        roles[readme_destination.relative_to(stage).as_posix()] = {"bootlin-official-evidence"}
        roles[summary_destination.relative_to(stage).as_posix()] = {"bootlin-official-evidence"}
        for source_path, destination in (
            (config_path, evidence_dir / "toolchain-evidence.json"),
            (args.component_lock.resolve(), evidence_dir / "component-lock.json"),
            (source_config_path, sources / "buildroot-source.json"),
        ):
            shutil.copy2(source_path, destination)
            roles[destination.relative_to(stage).as_posix()] = {"compliance-configuration"}

        component_manifest = bundle_component_records(lock)
        for component in component_manifest:
            if component["source"]:
                roles.setdefault(component["source"]["object"], set()).add(
                    "bootlin-component-source"
                )
            for license_file in component["license_files"]:
                roles.setdefault(license_file["object"], set()).add("bootlin-license-text")

        for digest, source_object in objects.items():
            relative = object_path(digest)
            if relative not in roles:
                continue
            link_or_copy(source_object, stage / relative)

        resolved_summary = dict(legal_summary)
        resolved_summary["buildroot_source"] = {
            **resolved_summary["buildroot_source"],
            "included_in_compliance_bundle": True,
        }
        resolved_summary["toolchain_evidence"] = {
            **resolved_summary["toolchain_evidence"],
            "component_sources_and_licenses_included": True,
        }
        resolved_summary["binary_release_ready"] = True
        resolved_summary["release_blockers"] = []
        resolved_summary_path = stage / "BUILDROOT_LEGAL_SUMMARY.json"
        write_json(resolved_summary_path, resolved_summary)
        roles[resolved_summary_path.relative_to(stage).as_posix()] = {"resolved-legal-summary"}

        manifest = {
            "schema": BUNDLE_SCHEMA,
            "profile": "buildroot-m6",
            "source_audit_ready": True,
            "binary_release_ready": True,
            "release_blockers": [],
            "resolved_release_blockers": sorted(blocker_ids),
            "buildroot_source": {
                **source,
                "archive": buildroot_archive.relative_to(stage).as_posix(),
                "archive_sha256": sha256(buildroot_archive),
            },
            "bootlin": {
                "package": config["package"],
                "version": config["version"],
                "archive": config["archive"],
                "archive_sha256": config["archive_sha256"],
                "official_evidence": {
                    "readme": {
                        **lock["official_evidence"]["readme"],
                        "path": readme_destination.relative_to(stage).as_posix(),
                    },
                    "summary": {
                        **lock["official_evidence"]["summary"],
                        "path": summary_destination.relative_to(stage).as_posix(),
                    },
                },
                "builder_source": {
                    **builder,
                    "archive": builder_archive.relative_to(stage).as_posix(),
                    "archive_sha256": sha256(builder_archive),
                },
                "components": component_manifest,
            },
            "legal_info": {
                "checksum_manifest_sha256": sha256(legal_info / "legal-info.sha256"),
                "inputs": legal_summary["inputs"],
            },
            "summary": {
                "target_packages": legal_summary["summary"]["target_packages"],
                "host_packages": legal_summary["summary"]["host_packages"],
                "bootlin_summary_rows": lock["summary"]["summary_rows"],
                "bootlin_components": lock["summary"]["components"],
                "bootlin_source_archives": lock["summary"]["source_archives"] + 1,
                "bootlin_license_files": lock["summary"]["license_files"],
                "unique_bootlin_objects": len(
                    {
                        artifact["sha256"]
                        for component in component_manifest
                        for artifact in ([component["source"]] if component["source"] else [])
                        + component["license_files"]
                    }
                ),
            },
        }
        readme = stage / "README.md"
        readme.write_text(readme_text(manifest), encoding="utf-8")
        roles[readme.relative_to(stage).as_posix()] = {"documentation"}

        files = []
        for path in sorted(stage.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(stage).as_posix()
            files.append(
                {
                    "path": relative,
                    "roles": sorted(roles.get(relative, {"supporting-evidence"})),
                    "size": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
        manifest["files"] = files
        manifest_path = stage / "COMPLIANCE_MANIFEST.json"
        write_json(manifest_path, manifest)
        checksum_files = sorted(path for path in stage.rglob("*") if path.is_file())
        (stage / "SHA256SUMS").write_text(
            "".join(
                f"{sha256(path)}  {path.relative_to(stage).as_posix()}\n" for path in checksum_files
            ),
            encoding="utf-8",
        )
        output.unlink(missing_ok=True)
        normalized_tar(stage, output)

    result = verify_archive(output)
    print(json.dumps(result, sort_keys=True))


def verify_directory(directory: Path) -> dict[str, Any]:
    manifest_path = directory / "COMPLIANCE_MANIFEST.json"
    checksum_path = directory / "SHA256SUMS"
    if not manifest_path.is_file() or not checksum_path.is_file():
        raise SystemExit("compliance bundle lacks its manifest or checksums")
    manifest = load_json(manifest_path)
    if manifest.get("schema") != BUNDLE_SCHEMA or manifest.get("profile") != "buildroot-m6":
        raise SystemExit("unsupported compliance bundle manifest")
    if not manifest.get("source_audit_ready") or not manifest.get("binary_release_ready"):
        raise SystemExit("compliance bundle is not binary-release ready")
    if manifest.get("release_blockers"):
        raise SystemExit("compliance bundle still has release blockers")
    resolved_release_blockers = manifest.get("resolved_release_blockers")
    if (
        not isinstance(resolved_release_blockers, list)
        or any(not isinstance(item, str) for item in resolved_release_blockers)
        or resolved_release_blockers != sorted(set(resolved_release_blockers))
        or set(resolved_release_blockers) - KNOWN_RELEASE_BLOCKERS
    ):
        raise SystemExit("compliance bundle has invalid resolved release blockers")

    actual_files = set()
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise SystemExit(f"compliance bundle contains a symlink: {path}")
        if path.is_file():
            actual_files.add(path.relative_to(directory).as_posix())
    checksums = checksum_entries(checksum_path)
    expected_checksum_files = actual_files - {"SHA256SUMS"}
    if set(checksums) != expected_checksum_files:
        raise SystemExit("compliance SHA256SUMS does not cover every bundle file")
    for relative, digest in checksums.items():
        if sha256(directory / relative) != digest:
            raise SystemExit(f"compliance checksum mismatch: {relative}")

    listed = {}
    roles = set()
    for item in manifest.get("files", []):
        relative = safe_relative(str(item.get("path", "")))
        if relative in listed:
            raise SystemExit(f"duplicate compliance manifest path: {relative}")
        listed[relative] = item
        roles.update(item.get("roles", []))
        path = directory / relative
        if (
            not path.is_file()
            or path.stat().st_size != item.get("size")
            or sha256(path) != item.get("sha256")
        ):
            raise SystemExit(f"compliance manifest mismatch: {relative}")
    expected_listed = actual_files - {"COMPLIANCE_MANIFEST.json", "SHA256SUMS"}
    if set(listed) != expected_listed:
        raise SystemExit("compliance manifest does not cover every payload file")
    if not REQUIRED_BUNDLE_ROLES <= roles:
        raise SystemExit("compliance bundle is missing required evidence roles")

    verify_legal_info(directory / "legal-info")
    for key in ("buildroot_source",):
        archive = manifest[key]["archive"]
        if sha256(directory / archive) != manifest[key]["archive_sha256"]:
            raise SystemExit(f"compliance source archive mismatch: {archive}")
    builder = manifest["bootlin"]["builder_source"]
    if sha256(directory / builder["archive"]) != builder["archive_sha256"]:
        raise SystemExit("Bootlin builder source archive mismatch")
    for name in ("readme", "summary"):
        item = manifest["bootlin"]["official_evidence"][name]
        if sha256(directory / item["path"]) != item["sha256"]:
            raise SystemExit(f"Bootlin official {name} mismatch")
    for component in manifest["bootlin"]["components"]:
        artifacts = ([component["source"]] if component["source"] else []) + component[
            "license_files"
        ]
        for item in artifacts:
            if sha256(directory / item["object"]) != item["sha256"]:
                raise SystemExit(
                    f"Bootlin component object mismatch: {component['name']} {item['name']}"
                )
    bundled_config = evidence_config(
        directory / "bootlin" / "evidence" / "toolchain-evidence.json"
    )
    bundled_lock = load_json(directory / "bootlin" / "evidence" / "component-lock.json")
    validate_lock(bundled_lock, bundled_config)
    validate_lock_summary(
        bundled_lock,
        (directory / manifest["bootlin"]["official_evidence"]["summary"]["path"]).read_bytes(),
        bundled_config,
    )
    if manifest["bootlin"]["components"] != bundle_component_records(bundled_lock):
        raise SystemExit("bundled component lock does not match compliance manifest")
    expected_official = {
        "readme": {
            **bundled_lock["official_evidence"]["readme"],
            "path": "bootlin/evidence/toolchain-readme.txt",
        },
        "summary": {
            **bundled_lock["official_evidence"]["summary"],
            "path": "bootlin/evidence/toolchain-summary.csv",
        },
    }
    if manifest["bootlin"]["official_evidence"] != expected_official:
        raise SystemExit("bundled official evidence does not match compliance manifest")
    bundled_source = source_config(directory / "sources" / "buildroot-source.json")
    raw_summary = summarize(
        directory / "legal-info",
        directory / "sources" / "buildroot-source.json",
        directory / "bootlin" / "evidence" / "toolchain-evidence.json",
    )
    raw_release_blockers = sorted(item["id"] for item in raw_summary["release_blockers"])
    if resolved_release_blockers != raw_release_blockers:
        raise SystemExit("resolved release blockers do not match bundled legal-info")
    if manifest["buildroot_source"]["repository"] != bundled_source["repository"] or manifest[
        "buildroot_source"
    ]["commit"] != bundled_source["commit"]:
        raise SystemExit("bundled Buildroot source config does not match compliance manifest")
    if any(
        manifest["bootlin"].get(field) != bundled_config[field]
        for field in ("package", "version", "archive", "archive_sha256")
    ) or any(
        manifest["bootlin"]["builder_source"].get(field)
        != bundled_config["builder_source"][field]
        for field in ("repository", "ref", "commit")
    ):
        raise SystemExit("bundled toolchain config does not match compliance manifest")
    resolved = load_json(directory / "BUILDROOT_LEGAL_SUMMARY.json")
    if not resolved.get("binary_release_ready") or resolved.get("release_blockers"):
        raise SystemExit("resolved Buildroot legal summary is not release ready")
    return {
        "schema": manifest["schema"],
        "profile": manifest["profile"],
        "binary_release_ready": True,
        "resolved_release_blockers": resolved_release_blockers,
        "buildroot_commit": manifest["buildroot_source"]["commit"],
        "bootlin_version": manifest["bootlin"]["version"],
        "manifest_sha256": sha256(manifest_path),
        "summary": manifest["summary"],
    }


def extract_archive(archive_path: Path, destination: Path) -> Path:
    process = subprocess.Popen(
        ["zstd", "-dc", "--no-progress", str(archive_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    names = set()
    roots = set()
    total_size = 0
    try:
        with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
            for member in archive:
                name = PurePosixPath(member.name)
                canonical = name.as_posix()
                if (
                    name.is_absolute()
                    or ".." in name.parts
                    or not name.parts
                    or member.name.rstrip("/") != canonical
                    or "\\" in member.name
                ):
                    raise SystemExit(f"unsafe compliance archive member: {member.name}")
                if canonical in names:
                    raise SystemExit(f"duplicate compliance archive member: {member.name}")
                names.add(canonical)
                roots.add(name.parts[0])
                if name.parts[0] != BUNDLE_ROOT or not (
                    member.isdir() or member.isfile() or member.islnk()
                ):
                    raise SystemExit(f"unsupported compliance archive member: {member.name}")
                total_size += member.size
                if total_size > 8 * 1024 * 1024 * 1024:
                    raise SystemExit("compliance archive expands beyond the 8 GiB safety limit")
                target = destination.joinpath(*name.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if member.islnk():
                    link = PurePosixPath(member.linkname)
                    if (
                        link.is_absolute()
                        or ".." in link.parts
                        or not link.parts
                        or link.parts[0] != BUNDLE_ROOT
                        or member.linkname.rstrip("/") != link.as_posix()
                        or "\\" in member.linkname
                    ):
                        raise SystemExit(
                            f"unsafe compliance archive hardlink: {member.name} -> {member.linkname}"
                        )
                    source = destination.joinpath(*link.parts)
                    if not source.is_file():
                        raise SystemExit(
                            f"unresolved compliance archive hardlink: {member.name} -> {member.linkname}"
                        )
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.link(source, target)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise SystemExit(f"unable to read compliance archive member: {member.name}")
                with target.open("wb") as stream:
                    shutil.copyfileobj(source, stream, 1024 * 1024)
    except BaseException:
        process.stdout.close()
        if process.poll() is None:
            process.kill()
        if process.stderr:
            process.stderr.read()
        process.wait()
        raise
    process.stdout.close()
    stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
    returncode = process.wait()
    if returncode != 0:
        raise SystemExit(f"invalid zstd compliance archive: {stderr.strip()}")
    if roots != {BUNDLE_ROOT}:
        raise SystemExit("compliance archive has an unexpected root")
    return destination / BUNDLE_ROOT


def verify_archive(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise SystemExit(f"compliance archive is missing: {path}")
    with tempfile.TemporaryDirectory(prefix="hidloom-compliance-verify-", dir=path.parent) as temporary:
        result = verify_directory(extract_archive(path, Path(temporary)))
    return {**result, "archive_sha256": sha256(path), "archive_size": path.stat().st_size}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    lock_parser = subparsers.add_parser("lock", help="pin exact Bootlin component files")
    lock_parser.add_argument(
        "--toolchain-evidence",
        type=Path,
        default=ROOT / "config" / "buildroot-toolchain-evidence.json",
    )
    lock_parser.add_argument(
        "--cache", type=Path, default=ROOT / "build" / "artifacts" / "bootlin-compliance-cache"
    )
    lock_parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "config" / "buildroot-toolchain-components.json",
    )
    lock_parser.add_argument("--refresh", action="store_true")
    lock_parser.add_argument("--jobs", type=int, default=4)
    lock_parser.set_defaults(handler=lock_toolchain)

    build_parser = subparsers.add_parser("build", help="build a verified compliance archive")
    build_parser.add_argument(
        "--legal-info",
        type=Path,
        default=ROOT / "build" / "artifacts" / "buildroot-m6-output" / "legal-info",
    )
    build_parser.add_argument(
        "--buildroot",
        type=Path,
        default=ROOT / "build" / "artifacts" / "buildroot-upstream",
    )
    build_parser.add_argument(
        "--bootlin-buildroot",
        type=Path,
        default=ROOT / "build" / "artifacts" / "bootlin-buildroot-toolchains",
    )
    build_parser.add_argument(
        "--buildroot-source", type=Path, default=ROOT / "config" / "buildroot-source.json"
    )
    build_parser.add_argument(
        "--toolchain-evidence",
        type=Path,
        default=ROOT / "config" / "buildroot-toolchain-evidence.json",
    )
    build_parser.add_argument(
        "--component-lock",
        type=Path,
        default=ROOT / "config" / "buildroot-toolchain-components.json",
    )
    build_parser.add_argument(
        "--cache", type=Path, default=ROOT / "build" / "artifacts" / "bootlin-compliance-cache"
    )
    build_parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "build" / "artifacts" / "hidloom-buildroot-m6-compliance.tar.zst",
    )
    build_parser.add_argument("--fetch-missing", action="store_true")
    build_parser.add_argument("--force", action="store_true")
    build_parser.add_argument("--jobs", type=int, default=4)
    build_parser.set_defaults(handler=build_bundle)

    verify_parser = subparsers.add_parser("verify", help="verify a compliance archive")
    verify_parser.add_argument("archive", type=Path)
    verify_parser.add_argument("--json", action="store_true")

    args = parser.parse_args()
    if args.command == "verify":
        result = verify_archive(args.archive)
        if args.json:
            print(json.dumps(result, sort_keys=True))
        else:
            print(
                f"ok: Buildroot compliance bundle ({result['summary']['bootlin_components']} "
                "Bootlin components)"
            )
        return
    if args.jobs <= 0:
        parser.error("--jobs must be positive")
    args.handler(args)


if __name__ == "__main__":
    main()
