#!/usr/bin/env python3
"""Regression tests for tracked repository artifact hygiene."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "repository_hygiene.py"
CONFIG = ROOT / "config" / "repository-hygiene.json"
sys.path.insert(0, str(ROOT / "tools"))

from repository_hygiene import portable_path_findings  # noqa: E402


def run(
    root: Path,
    *,
    check: bool,
    config: Path = CONFIG,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(TOOL), "--root", str(root), "--config", str(config)],
        check=check,
        capture_output=True,
        text=True,
    )


def write(path: Path, content: bytes | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if content is None:
        content = f"fixture:{path.as_posix()}\n".encode()
    path.write_bytes(content)


def main() -> None:
    current = run(ROOT, check=True)
    assert "ok: repository hygiene" in current.stdout
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert attributes == [
        "* text=auto eol=lf",
        "",
        "*.f3d binary",
        "*.ico binary",
        "*.jpg binary",
        "*.jpeg binary",
        "*.png binary",
    ]
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert config["schema"] == "hidloom.repository-hygiene.v5"
    assert config["duplicate_file_threshold_bytes"] == 1
    allow_groups = config["duplicate_file_allow_groups"]
    assert len(allow_groups) == 10
    assert [tuple(item["paths"]) for item in allow_groups] == sorted(
        tuple(item["paths"]) for item in allow_groups
    )
    for item in allow_groups:
        paths = [ROOT / relative for relative in item["paths"]]
        assert all(path.is_file() for path in paths)
        assert len({path.read_bytes() for path in paths}) == 1
        assert item["reason"].strip()
    policy = config["portable_path_policy"]
    direct_findings = portable_path_findings(
        ["docs/" + "x" * 256, "docs/COM¹.txt", "docs/\udcff.txt"],
        policy,
    )
    assert any("maximum is 255" in item.detail for item in direct_findings)
    assert any("reserved on Windows/Git" in item.detail for item in direct_findings)
    assert any("not valid Unicode" in item.detail for item in direct_findings)

    with tempfile.TemporaryDirectory() as tmp:
        fixture = Path(tmp) / "fixture"
        fixture.mkdir()
        subprocess.run(["git", "init", "-q", str(fixture)], check=True)
        write(fixture / "src" / "main.py")
        for dirname in ("inbox", "running", "done", "failed"):
            write(fixture / "codex_tasks" / dirname / "example.json.sample")
        write(fixture / "daemon" / "i2cd" / "__init__.py", b"")
        write(fixture / "assets" / "fixture.png", b"\x89PNG\r\n\x1a\n\x00")
        subprocess.run(["git", "-C", str(fixture), "add", "."], check=True)
        clean = run(fixture, check=True)
        assert "7 files" in clean.stdout

        large_content = b"x" * 1048577
        placeholders = [
            "build/artifacts/.gitkeep",
            "demo/assets/.gitkeep",
            "codex_tasks/inbox/.gitkeep",
            "codex_tasks/running/.gitkeep",
            "codex_tasks/done/.gitkeep",
            "codex_tasks/failed/.gitkeep",
        ]
        for placeholder in placeholders:
            write(fixture / placeholder, b"")
        write(fixture / "config" / "stale.json.bak2")
        write(fixture / "release.zip")
        write(fixture / "codex_tasks" / "done" / "real.result.json")
        write(fixture / "kicad" / "OLD" / "board.txt")
        write(fixture / "huge.bin", b"y" * 1048577)
        write(fixture / "case" / "duplicate-a.f3d", large_content)
        write(fixture / "case" / "duplicate-b.f3d", large_content)
        write(fixture / "Portable" / "README.md")
        write(fixture / "portable" / "other.md")
        write(fixture / "docs" / "CON.txt")
        write(fixture / "docs" / "bad:name.txt")
        write(fixture / "docs" / "trailing.")
        write(fixture / "docs" / "cafe\u0301.md")
        write(fixture / "long" / ("a" * 90) / (("b" * 90) + ".txt"))
        write(fixture / "content" / "empty.txt", b"")
        write(fixture / "content" / "crlf.txt", b"one\r\ntwo\r\n")
        write(fixture / "content" / "bom.txt", b"\xef\xbb\xbftext\n")
        write(fixture / "content" / "no-final-newline.txt", b"text")
        write(fixture / "content" / "trailing.txt", b"text \n")
        write(fixture / "content" / "non-utf8.txt", b"\xff\n")
        write(fixture / "content" / "bad-executable.py", b"print('fixture')\n")
        (fixture / "content" / "bad-executable.py").chmod(0o755)
        write(fixture / "content" / "non-executable.sh", b"#!/bin/sh\ntrue\n")
        write(fixture / "content" / "python-module.py", b"#!/usr/bin/env python3\n")
        write(fixture / ".gitignore", b"ignored-but-tracked.txt\n")
        write(fixture / "ignored-but-tracked.txt")
        write(
            fixture / "tools" / "missing-lock" / "Cargo.toml",
            b"[package]\nname='missing-lock'\nversion='0.1.0'\n",
        )
        subprocess.run(["git", "-C", str(fixture), "add", "-f", "."], check=True)
        dirty = run(fixture, check=False)
        assert dirty.returncode == 1
        output = dirty.stdout + dirty.stderr
        for placeholder in placeholders:
            assert f"forbidden_artifact: {placeholder}" in output, placeholder
        for finding in [
            "forbidden_artifact: config/stale.json.bak2",
            "forbidden_artifact: release.zip",
            "runtime_artifact: codex_tasks/done/real.result.json",
            "generated_path: kicad/OLD/board.txt",
            "unapproved_large_file: huge.bin",
            "unapproved_duplicate_file: case/duplicate-a.f3d",
            "tracked_ignored_file: ignored-but-tracked.txt",
            "missing_companion_file: tools/missing-lock/Cargo.lock",
            "portable_path_collision: Portable",
            "nonportable_path: docs/CON.txt",
            "nonportable_path: docs/bad:name.txt",
            "nonportable_path: docs/trailing.",
            "empty_tracked_file: content/empty.txt",
            "non_lf_line_ending: content/crlf.txt",
            "text_bom: content/bom.txt",
            "missing_final_newline: content/no-final-newline.txt",
            "trailing_whitespace: content/trailing.txt",
            "non_utf8_text: content/non-utf8.txt",
            "executable_without_shebang: content/bad-executable.py",
            "non_executable_shell: content/non-executable.sh",
        ]:
            assert finding in output, finding
        assert "component is not NFC-normalized" in output
        assert "path uses 190 UTF-16 units; maximum is 180" in output

    with tempfile.TemporaryDirectory() as tmp:
        fixture = Path(tmp) / "allowed-duplicate"
        fixture.mkdir()
        subprocess.run(["git", "init", "-q", str(fixture)], check=True)
        duplicate = b"reviewed duplicate\n"
        first = fixture / "docs" / "copy-a.txt"
        second = fixture / "docs" / "copy-b.txt"
        third = fixture / "docs" / "copy-c.txt"
        write(first, duplicate)
        write(second, duplicate)
        subprocess.run(["git", "-C", str(fixture), "add", "."], check=True)
        fixture_config = dict(config)
        fixture_config["duplicate_file_allow_groups"] = [
            {
                "paths": ["docs/copy-a.txt", "docs/copy-b.txt"],
                "reason": "Fixture files model independently consumable snapshots.",
            }
        ]
        config_path = Path(tmp) / "repository-hygiene.json"
        config_path.write_text(
            json.dumps(fixture_config, indent=2) + "\n", encoding="utf-8"
        )
        allowed = run(fixture, check=True, config=config_path)
        assert "ok: repository hygiene" in allowed.stdout

        write(third, duplicate)
        subprocess.run(["git", "-C", str(fixture), "add", "."], check=True)
        expanded = run(fixture, check=False, config=config_path)
        assert expanded.returncode == 1
        assert "unapproved_duplicate_file: docs/copy-a.txt" in (
            expanded.stdout + expanded.stderr
        )

        subprocess.run(
            ["git", "-C", str(fixture), "rm", "-fq", "docs/copy-c.txt"], check=True
        )
        write(second, b"diverged copy\n")
        subprocess.run(["git", "-C", str(fixture), "add", "docs/copy-b.txt"], check=True)
        stale = run(fixture, check=False, config=config_path)
        assert stale.returncode == 1
        assert "stale_duplicate_allowance: docs/copy-a.txt" in (
            stale.stdout + stale.stderr
        )

        subprocess.run(
            ["git", "-C", str(fixture), "rm", "-fq", "docs/copy-b.txt"], check=True
        )
        incomplete = run(fixture, check=False, config=config_path)
        assert incomplete.returncode == 1
        assert "incomplete_duplicate_allowance: docs/copy-a.txt" in (
            incomplete.stdout + incomplete.stderr
        )

    with tempfile.TemporaryDirectory() as tmp:
        exported = Path(tmp) / "public"
        exported.mkdir()
        write(exported / "README.md")
        manifest = {
            "schema": "hidloom.public-export-manifest.v2",
            "files": [
                {
                    "path": "README.md",
                    "kind": "file",
                    "mode": 0o644,
                    "size": 8,
                    "sha256": "fixture",
                }
            ],
        }
        (exported / "PUBLIC_EXPORT_MANIFEST.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        fallback = run(exported, check=True)
        assert "from PUBLIC_EXPORT_MANIFEST.json" in fallback.stdout

        write(exported / "script" / "entrypoint.sh", b"#!/bin/sh\ntrue\n")
        manifest["files"].append(
            {
                "path": "script/entrypoint.sh",
                "kind": "file",
                "mode": 0o644,
                "size": 15,
                "sha256": "fixture",
            }
        )
        (exported / "PUBLIC_EXPORT_MANIFEST.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        non_executable_export = run(exported, check=False)
        assert non_executable_export.returncode == 1
        assert "non_executable_shell: script/entrypoint.sh" in (
            non_executable_export.stdout + non_executable_export.stderr
        )
        manifest["files"][-1]["mode"] = 0o755
        (exported / "PUBLIC_EXPORT_MANIFEST.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        executable_export = run(exported, check=True)
        assert "from PUBLIC_EXPORT_MANIFEST.json" in executable_export.stdout

        write(exported / "Portable" / "README.md")
        write(exported / "portable" / "other.md")
        manifest["files"].extend(
            [
                {"path": "Portable/README.md", "kind": "file", "mode": 0o644, "size": 8},
                {"path": "portable/other.md", "kind": "file", "mode": 0o644, "size": 8},
            ]
        )
        (exported / "PUBLIC_EXPORT_MANIFEST.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        nonportable_export = run(exported, check=False)
        assert nonportable_export.returncode == 1
        assert "portable_path_collision: Portable" in (
            nonportable_export.stdout + nonportable_export.stderr
        )

    if (ROOT / "PUBLIC_EXPORT_MANIFEST.json").is_file() and not (ROOT / ".git").exists():
        assert not any(ROOT.rglob("__pycache__"))

    print("ok: repository hygiene rejects tracked development artifacts")


if __name__ == "__main__":
    main()
