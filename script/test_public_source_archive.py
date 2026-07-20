#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def file_record(root: Path, relative: str) -> dict[str, object]:
    path = root / relative
    if path.is_symlink():
        content = os.readlink(path).encode()
        kind = "symlink"
    else:
        content = path.read_bytes()
        kind = "file"
    return {
        "path": relative,
        "kind": kind,
        "mode": (
            0o777
            if kind == "symlink"
            else (0o755 if path.stat().st_mode & 0o111 else 0o644)
        ),
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, capture_output=True, text=True)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        source = workspace / "source"
        source.mkdir()
        (source / ".github").mkdir()
        dependabot = source / ".github/dependabot.yml"
        dependabot.write_text("version: 2\n", encoding="utf-8")
        dependabot.chmod(0o644)
        (source / "bin").mkdir()
        executable = source / "bin/hidloom-check"
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
        readme = source / "README.md"
        readme.write_text("fixture\n", encoding="utf-8")
        readme.chmod(0o644)
        (source / "README.link").symlink_to("README.md")
        provenance = {
            "schema": "hidloom.source-provenance.v1",
            "mode": "clean-head",
            "publishable": True,
            "base_commit": "1" * 40,
            "base_tree": "2" * 40,
            "base_revision_count": 1,
            "selected_path_count": 5,
            "selected_snapshot_sha256": "3" * 64,
        }
        report = {
            "schema": "hidloom.public-export-report.v2",
            "source_provenance": provenance,
            "file_count": 5,
            "source_selection": {
                "tracked_paths": 5,
                "public_source_paths": 5,
                "private_only_paths": 0,
                "generated_output_paths": 0,
                "unclassified_paths": 0,
            },
        }
        report_path = source / "PUBLIC_EXPORT_REPORT.json"
        report_path.write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        report_path.chmod(0o644)
        listed = [
            ".github/dependabot.yml",
            "bin/hidloom-check",
            "PUBLIC_EXPORT_REPORT.json",
            "README.link",
            "README.md",
        ]
        manifest = {
            "schema": "hidloom.public-export-manifest.v2",
            "source_provenance": provenance,
            "files": [file_record(source, relative) for relative in listed],
        }
        (source / "PUBLIC_EXPORT_MANIFEST.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        (source / "unlisted.tmp").write_text("exclude\n", encoding="utf-8")

        archives = [workspace / "one.tar.zst", workspace / "two.tar.zst"]
        reports = [workspace / "one.json", workspace / "two.json"]
        for archive, archive_report in zip(archives, reports, strict=True):
            created = run(
                [
                    "python3",
                    str(ROOT / "tools/public_source_archive.py"),
                    str(source),
                    str(archive),
                    "--root-name",
                    "hidloom-public",
                    "--report",
                    str(archive_report),
                ],
                check=False,
            )
            assert created.returncode == 0, created.stdout + created.stderr
        assert archives[0].read_bytes() == archives[1].read_bytes()
        payload = json.loads(reports[0].read_text(encoding="utf-8"))
        assert payload["schema"] == "hidloom.public-source-archive.v2"
        assert payload["source_commit"] == "1" * 40
        assert payload["source_tree"] == "2" * 40
        assert payload["source_snapshot_sha256"] == "3" * 64
        assert payload["file_count"] == len(listed) + 1
        assert len(payload["archive"]["sha256"]) == 64

        members = run(["tar", "--zstd", "-tf", str(archives[0])]).stdout.splitlines()
        assert "hidloom-public/.github/dependabot.yml" in members
        assert "hidloom-public/PUBLIC_EXPORT_MANIFEST.json" in members
        assert not any("unlisted.tmp" in member for member in members)
        extracted = workspace / "extracted"
        extracted.mkdir()
        run(
            [
                "tar",
                "--zstd",
                "--same-permissions",
                "-xf",
                str(archives[0]),
                "-C",
                str(extracted),
            ]
        )
        root = extracted / "hidloom-public"
        assert (root / ".github/dependabot.yml").read_text(encoding="utf-8") == "version: 2\n"
        assert (root / "bin/hidloom-check").stat().st_mode & 0o777 == 0o755
        assert (root / "README.md").stat().st_mode & 0o777 == 0o644
        assert (root / "README.link").is_symlink()
        assert os.readlink(root / "README.link") == "README.md"

        readme.chmod(0o755)
        bad_mode = run(
            [
                "python3",
                str(ROOT / "tools/public_source_archive.py"),
                str(source),
                str(workspace / "bad-mode.tar.zst"),
            ],
            check=False,
        )
        assert bad_mode.returncode != 0
        assert "mode:README.md" in bad_mode.stderr
        readme.chmod(0o644)

        executable.unlink()
        failed = run(
            [
                "python3",
                str(ROOT / "tools/public_source_archive.py"),
                str(source),
                str(workspace / "invalid.tar.zst"),
            ],
            check=False,
        )
        assert failed.returncode != 0
        assert "missing:bin/hidloom-check" in failed.stderr

    private_workflow = ROOT / ".github/workflows/public-export-check.yml"
    if private_workflow.is_file():
        workflow = private_workflow.read_text(encoding="utf-8")
        assert "python3 tools/public_source_archive.py" in workflow
        assert "hidloom-public-source.tar.zst" in workflow
        assert "PUBLIC_SOURCE_ARCHIVE.json" in workflow
        assert "${{ runner.temp }}/hidloom-public\n" not in workflow

    print("ok: public source archive is deterministic, bounded, and mode-normalized")


if __name__ == "__main__":
    main()
