#!/usr/bin/env python3
"""Regression tests for tracked source syntax validation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "source_syntax_hygiene.py"


def write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def run(
    root: Path,
    *,
    check: bool,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), "--root", str(root)],
        capture_output=True,
        text=True,
        check=check,
        env=environment,
    )


def main() -> None:
    current = run(ROOT, check=True)
    for source_type in ("python", "json", "toml", "yaml", "shell", "javascript", "svg"):
        assert f"{source_type}=" in current.stdout, source_type

    with tempfile.TemporaryDirectory() as temporary:
        fixture = Path(temporary) / "fixture"
        fixture.mkdir()
        subprocess.run(["git", "init", "-q", str(fixture)], check=True)
        write(fixture / "valid.py", b"value = 1\n")
        write(fixture / "valid.json", b'{"value": 1}\n')
        write(fixture / "valid.toml", b"value = 1\n")
        write(fixture / "valid.yml", b"value: 1\n")
        write(fixture / "valid.sh", b"#!/bin/sh\nexit 0\n")
        write(fixture / "valid.js", b"const value = 1;\n")
        write(fixture / "valid.svg", b'<svg xmlns="http://www.w3.org/2000/svg"/>\n')
        subprocess.run(["git", "-C", str(fixture), "add", "."], check=True)
        valid = run(fixture, check=True)
        assert "7 files from git index" in valid.stdout

        write(fixture / "invalid.py", b"def broken(:\n")
        write(fixture / "invalid.json", b"{]\n")
        write(fixture / "invalid.toml", b"value = [\n")
        write(fixture / "invalid.yml", b"value: [\n")
        write(fixture / "invalid.sh", b"#!/bin/sh\nif then\n")
        write(fixture / "invalid.js", b"function broken( {\n")
        write(fixture / "invalid.svg", b"<svg>\n")
        subprocess.run(["git", "-C", str(fixture), "add", "."], check=True)
        invalid = run(fixture, check=False)
        assert invalid.returncode == 1
        output = invalid.stdout + invalid.stderr
        for finding in (
            "python_syntax: invalid.py",
            "json_syntax: invalid.json",
            "toml_syntax: invalid.toml",
            "yaml_syntax: invalid.yml",
            "shell_syntax: invalid.sh",
            "javascript_syntax: invalid.js",
            "svg_syntax: invalid.svg",
        ):
            assert finding in output, finding

    with tempfile.TemporaryDirectory() as temporary:
        exported = Path(temporary) / "public"
        exported.mkdir()
        write(exported / "valid.py", b"value = 1\n")
        write(exported / "valid.js", b"const value = 1;\n")
        manifest = {
            "schema": "hidloom.public-export-manifest.v2",
            "files": [
                {
                    "path": "valid.py",
                    "kind": "file",
                    "mode": 0o644,
                    "size": 10,
                    "sha256": "fixture",
                },
                {
                    "path": "valid.js",
                    "kind": "file",
                    "mode": 0o644,
                    "size": 17,
                    "sha256": "fixture",
                },
            ],
        }
        (exported / "PUBLIC_EXPORT_MANIFEST.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        raw = run(exported, check=True)
        assert "3 files from PUBLIC_EXPORT_MANIFEST.json" in raw.stdout
        no_parser_environment = os.environ.copy()
        no_parser_environment["PATH"] = ""
        no_parser = run(exported, check=False, environment=no_parser_environment)
        assert no_parser.returncode == 1
        assert "missing_parser: valid.js: node not found" in no_parser.stderr
        assert not any(exported.rglob("__pycache__"))

    private_export_workflow = ROOT / ".github" / "workflows" / "public-export-check.yml"
    if private_export_workflow.exists():
        workflow = private_export_workflow.read_text(encoding="utf-8")
        assert workflow.count("python3 script/test_source_syntax_hygiene.py") == 2
        assert "python3-yaml" in workflow
        assert 'echo "/usr/bin" >> "$GITHUB_PATH"' in workflow
        assert '"tools/**"' in workflow
        assert '"script/**"' in workflow

    private_sync_workflow = ROOT / ".github" / "workflows" / "public-sync.yml"
    if private_sync_workflow.exists():
        workflow = private_sync_workflow.read_text(encoding="utf-8")
        assert workflow.count("python3 script/test_source_syntax_hygiene.py") == 1
        assert "python3-yaml" in workflow
        assert 'echo "/usr/bin" >> "$GITHUB_PATH"' in workflow

    print("ok: source syntax hygiene rejects malformed tracked formats")


if __name__ == "__main__":
    main()
