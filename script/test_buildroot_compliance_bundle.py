#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def git_checkout(workspace: Path, name: str, files: dict[str, str]) -> tuple[Path, str, str]:
    seed = workspace / f"{name}-seed"
    seed.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=seed, check=True)
    subprocess.run(["git", "config", "user.name", "HIDloom Test"], cwd=seed, check=True)
    subprocess.run(["git", "config", "user.email", "test@localhost"], cwd=seed, check=True)
    for relative, content in files.items():
        path = seed / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=seed, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=seed, check=True)
    origin = workspace / f"{name}.git"
    checkout = workspace / name
    subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(checkout)], check=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout, text=True).strip()
    return checkout, str(origin), commit


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "PACKAGE",
        "VERSION",
        "LICENSE",
        "LICENSE FILES",
        "SOURCE ARCHIVE",
        "SOURCE SITE",
        "DEPENDENCIES WITH LICENSES",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)


def write_checksums(directory: Path) -> None:
    files = sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.name != "legal-info.sha256"
    )
    (directory / "legal-info.sha256").write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  "
            f"{path.relative_to(directory).as_posix()}\n"
            for path in files
        ),
        encoding="utf-8",
    )


def make_compliance_fixture(workspace: Path, tool_root: Path = ROOT) -> Path:
    workspace.mkdir(parents=True)
    buildroot, buildroot_origin, buildroot_commit = git_checkout(
        workspace, "buildroot", {"COPYING": "GPL fixture\n", "Makefile": "all:\n\t@true\n"}
    )
    builder, builder_origin, builder_commit = git_checkout(
        workspace,
        "bootlin-builder",
        {"COPYING": "GPL fixture\n", "configs/fixture_defconfig": "BR2_arm=y\n"},
    )
    subprocess.run(
        ["git", "--git-dir", builder_origin, "tag", "fixture", builder_commit], check=True
    )

    official = workspace / "official"
    source_content = b"official compiler source fixture\n"
    compiler_license = b"official compiler license fixture\n"
    buildroot_license = b"official Buildroot license fixture\n"
    (official / "sources" / "gcc-final-1.0").mkdir(parents=True)
    (official / "sources" / "gcc-final-1.0" / "gcc-1.0.tar.xz").write_bytes(source_content)
    (official / "licenses" / "gcc-final-1.0").mkdir(parents=True)
    (official / "licenses" / "gcc-final-1.0" / "COPYING").write_bytes(compiler_license)
    (official / "licenses" / "buildroot").mkdir(parents=True)
    (official / "licenses" / "buildroot" / "COPYING").write_bytes(buildroot_license)
    readme = official / "toolchain-readme.txt"
    readme.write_text("official Bootlin fixture evidence\n", encoding="utf-8")
    summary = official / "toolchain-summary.csv"
    summary_rows = [
        {
            "PACKAGE": "gcc-final",
            "VERSION": "1.0",
            "LICENSE": "GPL-3.0-with-GCC-exception",
            "LICENSE FILES": "COPYING",
            "SOURCE ARCHIVE": "gcc-1.0.tar.xz",
            "SOURCE SITE": "https://example.invalid/gcc",
            "DEPENDENCIES WITH LICENSES": "",
        },
        {
            "PACKAGE": "gcc-final",
            "VERSION": "1.0",
            "LICENSE": "GPL-3.0",
            "LICENSE FILES": "COPYING",
            "SOURCE ARCHIVE": "gcc-1.0.tar.xz",
            "SOURCE SITE": "https://example.invalid/gcc",
            "DEPENDENCIES WITH LICENSES": "",
        },
        {
            "PACKAGE": "buildroot",
            "VERSION": f"fixture-g{builder_commit[:10]}",
            "LICENSE": "GPL-2.0+",
            "LICENSE FILES": "COPYING",
            "SOURCE ARCHIVE": "not saved",
            "SOURCE SITE": "not saved",
            "DEPENDENCIES WITH LICENSES": "",
        },
    ]
    write_csv(summary, summary_rows)

    toolchain_archive = b"external toolchain fixture\n"
    evidence = {
        "schema": "hidloom.buildroot-toolchain-evidence.v2",
        "package": "toolchain-external-bootlin",
        "version": "fixture",
        "archive": "toolchain-fixture.tar.xz",
        "archive_sha256": digest(toolchain_archive),
        "license_summary": "GPL fixture",
        "official_evidence": {
            "release_page": "https://example.invalid/fixture",
            "readme": readme.as_uri(),
            "readme_sha256": digest(readme.read_bytes()),
            "summary": summary.as_uri(),
            "summary_sha256": digest(summary.read_bytes()),
            "sources": (official / "sources").as_uri() + "/",
            "licenses": (official / "licenses").as_uri() + "/",
        },
        "builder_source": {
            "repository": builder_origin,
            "ref": "refs/tags/fixture",
            "commit": builder_commit,
        },
        "target_components": [],
        "review": "complete",
        "binary_release_requirement": "fixture compliance material",
    }
    evidence_path = workspace / "toolchain-evidence.json"
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    buildroot_source = {
        "schema": "hidloom.buildroot-source.v1",
        "repository": buildroot_origin,
        "commit": buildroot_commit,
    }
    buildroot_source_path = workspace / "buildroot-source.json"
    buildroot_source_path.write_text(json.dumps(buildroot_source, indent=2) + "\n", encoding="utf-8")

    legal = workspace / "legal-info"
    (legal / "sources" / "fixture-package-1").mkdir(parents=True)
    fixture_source = legal / "sources" / "fixture-package-1" / "fixture-package-1.tar.gz"
    fixture_source.write_bytes(b"fixture package source\n")
    (legal / "sources" / "toolchain-external-bootlin-fixture").mkdir(parents=True)
    (legal / "sources" / "toolchain-external-bootlin-fixture" / evidence["archive"]).write_bytes(
        toolchain_archive
    )
    (legal / "licenses" / "fixture-package-1").mkdir(parents=True)
    (legal / "licenses" / "fixture-package-1" / "COPYING").write_text(
        "fixture package license\n", encoding="utf-8"
    )
    (legal / "host-sources" / "fixture-package-1").mkdir(parents=True)
    os.link(
        fixture_source,
        legal / "host-sources" / "fixture-package-1" / "fixture-package-1.tar.gz",
    )
    legal_rows = [
        {
            "PACKAGE": "fixture-package",
            "VERSION": "1",
            "LICENSE": "GPL-3.0-or-later",
            "LICENSE FILES": "COPYING",
            "SOURCE ARCHIVE": "fixture-package-1.tar.gz",
            "SOURCE SITE": "https://example.invalid/fixture-package",
            "DEPENDENCIES WITH LICENSES": "",
        },
        {
            "PACKAGE": evidence["package"],
            "VERSION": evidence["version"],
            "LICENSE": "unknown",
            "LICENSE FILES": "",
            "SOURCE ARCHIVE": evidence["archive"],
            "SOURCE SITE": "https://example.invalid/toolchain",
            "DEPENDENCIES WITH LICENSES": "",
        },
    ]
    write_csv(legal / "manifest.csv", legal_rows)
    write_csv(legal / "host-manifest.csv", [])
    (legal / "README").write_text(
        "WARNING: Buildroot source code has not been saved\n"
        "WARNING: toolchain-external-bootlin-fixture has no license files defined\n",
        encoding="utf-8",
    )
    (legal / "buildroot.config").write_text("BR2_arm=y\n", encoding="utf-8")
    write_checksums(legal)

    cache = workspace / "cache"
    lock = workspace / "component-lock.json"
    archive = workspace / "compliance.tar.zst"
    tool = tool_root / "tools" / "buildroot_compliance_bundle.py"
    locked = subprocess.run(
        [
            "python3",
            str(tool),
            "lock",
            "--toolchain-evidence",
            str(evidence_path),
            "--cache",
            str(cache),
            "--output",
            str(lock),
            "--jobs",
            "2",
        ],
        cwd=tool_root,
        capture_output=True,
        text=True,
    )
    assert locked.returncode == 0, locked.stdout + locked.stderr
    build_command = [
        "python3",
        str(tool),
        "build",
        "--legal-info",
        str(legal),
        "--buildroot",
        str(buildroot),
        "--bootlin-buildroot",
        str(builder),
        "--buildroot-source",
        str(buildroot_source_path),
        "--toolchain-evidence",
        str(evidence_path),
        "--component-lock",
        str(lock),
        "--cache",
        str(cache),
        "--output",
        str(archive),
        "--jobs",
        "2",
    ]
    built = subprocess.run(
        build_command,
        cwd=tool_root,
        capture_output=True,
        text=True,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    first = archive.read_bytes()
    rebuilt = subprocess.run(
        [*build_command, "--force"],
        cwd=tool_root,
        capture_output=True,
        text=True,
    )
    assert rebuilt.returncode == 0, rebuilt.stdout + rebuilt.stderr
    assert archive.read_bytes() == first
    return archive


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary)
        fixture = workspace / "fixture"
        archive = make_compliance_fixture(fixture)
        verified = subprocess.run(
            [
                "python3",
                str(ROOT / "tools" / "buildroot_compliance_bundle.py"),
                "verify",
                str(archive),
                "--json",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(verified.stdout)
        assert payload["binary_release_ready"] is True
        assert payload["resolved_release_blockers"] == [
            "bootlin-toolchain-compliance-not-bundled",
            "buildroot-source-not-bundled",
        ]
        assert payload["summary"] == {
            "bootlin_components": 2,
            "bootlin_license_files": 2,
            "bootlin_source_archives": 2,
            "bootlin_summary_rows": 3,
            "host_packages": 0,
            "target_packages": 2,
            "unique_bootlin_objects": 3,
        }

        tampered = workspace / "tampered.tar.zst"
        shutil.copy2(archive, tampered)
        content = bytearray(tampered.read_bytes())
        content[len(content) // 2] ^= 0x01
        tampered.write_bytes(content)
        failed = subprocess.run(
            [
                "python3",
                str(ROOT / "tools" / "buildroot_compliance_bundle.py"),
                "verify",
                str(tampered),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert failed.returncode != 0

    print("ok: deterministic Buildroot compliance bundle and tamper gate")


if __name__ == "__main__":
    main()
