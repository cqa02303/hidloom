#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HEADER = [
    "PACKAGE", "VERSION", "LICENSE", "LICENSE FILES", "SOURCE ARCHIVE", "SOURCE SITE",
    "DEPENDENCIES WITH LICENSES",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    tracked = json.loads(
        (ROOT / "docs/ops/buildroot-m6-legal-summary.json").read_text(encoding="utf-8")
    )
    assert tracked["schema"] == "hidloom.buildroot-legal-summary.v1"
    assert tracked["source_audit_ready"] is True
    assert tracked["binary_release_ready"] is False
    assert tracked["summary"]["target_packages"] == 20
    matrixd = next(item for item in tracked["target_packages"] if item["name"] == "hidloom-matrixd")
    assert matrixd["license"] == "GPL-3.0-or-later"
    assert matrixd["license_files_saved"] == ["COPYING"]

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        legal = workspace / "legal-info"
        legal.mkdir()
        toolchain_archive = "toolchain.tar.xz"
        matrixd_archive = "hidloom-matrixd-1.tar.gz"
        toolchain_source = legal / "sources/toolchain-external-bootlin-1/toolchain.tar.xz"
        matrixd_source = legal / f"sources/hidloom-matrixd-1/{matrixd_archive}"
        matrixd_license = legal / "licenses/hidloom-matrixd-1/COPYING"
        for path, content in (
            (toolchain_source, b"toolchain"),
            (matrixd_source, b"matrixd"),
            (matrixd_license, b"GPL fixture"),
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        with (legal / "manifest.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, quoting=csv.QUOTE_ALL)
            writer.writerow(HEADER)
            writer.writerow([
                "toolchain-external-bootlin", "1", "unknown", "", toolchain_archive,
                "https://example.invalid", "",
            ])
            writer.writerow([
                "hidloom-matrixd", "1", "GPL-3.0-or-later", "COPYING", matrixd_archive,
                "/private/source", "",
            ])
        with (legal / "host-manifest.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, quoting=csv.QUOTE_ALL)
            writer.writerow(HEADER)
            writer.writerow(["buildroot", "1", "GPL-2.0+", "COPYING", "not saved", "not saved", ""])
        (legal / "README").write_text(
            "WARNING: the Buildroot source code has not been saved\n"
            "WARNING: toolchain-external-bootlin-1: cannot save license\n",
            encoding="utf-8",
        )
        checksum_files = [toolchain_source, matrixd_source, matrixd_license]
        (legal / "legal-info.sha256").write_text(
            "".join(f"{sha256(path)}  {path.relative_to(legal).as_posix()}\n" for path in checksum_files),
            encoding="utf-8",
        )
        buildroot_source = workspace / "buildroot-source.json"
        buildroot_source.write_text(
            json.dumps({"repository": "https://example.invalid/buildroot", "commit": "a" * 40}),
            encoding="utf-8",
        )
        toolchain = workspace / "toolchain.json"
        toolchain.write_text(
            json.dumps({
                "package": "toolchain-external-bootlin",
                "version": "1",
                "archive_sha256": sha256(toolchain_source),
                "license_summary": "GPL test",
                "review": "complete",
                "binary_release_requirement": "bundle fixture evidence",
            }),
            encoding="utf-8",
        )
        output = workspace / "summary.json"
        subprocess.run(
            [
                "python3", str(ROOT / "tools/summarize_buildroot_legal_info.py"), str(legal),
                "--buildroot-source", str(buildroot_source), "--toolchain-evidence", str(toolchain),
                "--output", str(output),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        summary = json.loads(output.read_text(encoding="utf-8"))
        assert summary["source_audit_ready"] is True
        assert summary["binary_release_ready"] is False
        assert summary["summary"]["target_complete"] == 2
        assert [item["id"] for item in summary["release_blockers"]] == [
            "buildroot-source-not-bundled",
            "bootlin-toolchain-compliance-not-bundled",
        ]

    print("ok: Buildroot legal-info summary is exact and release-conservative")


if __name__ == "__main__":
    main()
