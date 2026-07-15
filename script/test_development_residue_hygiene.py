#!/usr/bin/env python3
"""Regression tests for tracked development-residue validation."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "development_residue_hygiene.py"


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def run(root: Path, *, check: bool) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), "--root", str(root)],
        capture_output=True,
        text=True,
        check=check,
    )


def main() -> None:
    current = run(ROOT, check=True)
    for source_type in ("javascript", "python", "rust", "shell", "text"):
        assert f"{source_type}=" in current.stdout, source_type

    with tempfile.TemporaryDirectory() as temporary:
        fixture = Path(temporary) / "fixture"
        fixture.mkdir()
        subprocess.run(["git", "init", "-q", str(fixture)], check=True)
        write(
            fixture / "clean.py",
            'marker_example = "# TODO inside data"\n'
            'repo = env.get("HIDLOOM_REPO_ROOT") or "/opt/hidloom"\n',
        )
        write(
            fixture / "clean.sh",
            '#!/bin/sh\nprintf "%s\\n" "${HIDLOOM_REPO_ROOT:-/opt/hidloom}" \'# FIXME inside data\'\n',
        )
        write(
            fixture / "clean.js",
            'const example = "console.log and // HACK are data";\nconsole.warn("expected warning");\n',
        )
        write(
            fixture / "clean.rs",
            'const EXAMPLE: &str = "todo!() and // WIP are data";\nfn borrowed<\'a>(value: &\'a str) -> &\'a str { value }\n',
        )
        write(fixture / "clean.c", 'const char *example = "/* TBD inside data */";\n')
        write(fixture / "test_marker.py", "# TODO documents a test scenario\nvalue = 1\n")
        write(fixture / "notes.txt", "clean fixture\n")
        subprocess.run(["git", "-C", str(fixture), "add", "."], check=True)
        valid = run(fixture, check=True)
        assert "7 files from git index" in valid.stdout

        write(
            fixture / "duplicate.py",
            "import pdb\n"
            "# TODO remove unfinished production path\n"
            "class FeatureNotImplemented(RuntimeError):\n"
            "    pass\n"
            "def unfinished():\n"
            "    raise NotImplementedError('unfinished')\n"
            'repo = env.get("HIDLOOM_REPO_ROOT") or env.get("HIDLOOM_REPO_ROOT")\n'
            'mapping = {"duplicate": 1, "duplicate": 2}\n'
            'flags = ("HIDLOOM_REPO_ROOT", "HIDLOOM_REPO_ROOT")\n'
            'env["MODE"] = "test"\n'
            'env["MODE"] = "test"\n'
            "breakpoint()\n"
            "pdb.set_trace()\n",
        )
        write(
            fixture / "dirty.sh",
            "#!/bin/sh\n"
            "# FIXME remove diagnostic mode\n"
            "set -x\n"
            'ROOT="${HIDLOOM_REPO_ROOT:-${HIDLOOM_REPO_ROOT:-}}"\n'
            'HIDLOOM_REPO_ROOT="$ROOT" HIDLOOM_REPO_ROOT="$ROOT" command\n',
        )
        write(
            fixture / "dirty.js",
            '// HACK remove debug route\nconsole.log("debug");\nconsole.debug("debug");\ndebugger;\n',
        )
        write(
            fixture / "dirty.rs",
            "// WIP remove placeholder\nfn unfinished<'a>(value: &'a str) { dbg!(value); todo!(); unimplemented!(); }\n",
        )
        write(fixture / "dirty.c", "/* TBD replace placeholder */\nint value = 1;\n")
        write(fixture / "conflict.txt", "<<<<<<< ours\n=======\n>>>>>>> theirs\n")
        subprocess.run(["git", "-C", str(fixture), "add", "."], check=True)
        invalid = run(fixture, check=False)
        assert invalid.returncode == 1
        output = invalid.stdout + invalid.stderr
        for finding in (
            "duplicate_or_operand: duplicate.py",
            "duplicate_dict_key: duplicate.py",
            "duplicate_environment_name: duplicate.py",
            "duplicate_adjacent_statement: duplicate.py",
            "python_debug_hook: duplicate.py",
            "python_unfinished_symbol: duplicate.py",
            "python_not_implemented_raise: duplicate.py",
            "development_marker_comment: duplicate.py",
            "development_marker_comment: dirty.sh",
            "development_marker_comment: dirty.js",
            "development_marker_comment: dirty.rs",
            "development_marker_comment: dirty.c",
            "shell_xtrace: dirty.sh",
            "shell_self_fallback: dirty.sh",
            "duplicate_shell_environment: dirty.sh",
            "javascript_debug_output: dirty.js",
            "javascript_debugger: dirty.js",
            "rust_placeholder_macro: dirty.rs",
            "merge_conflict_marker: conflict.txt",
        ):
            assert finding in output, finding

    with tempfile.TemporaryDirectory() as temporary:
        exported = Path(temporary) / "public"
        exported.mkdir()
        write(exported / "clean.py", "value = 1\n")
        write(exported / "clean.js", 'console.warn("expected warning");\n')
        manifest = {
            "schema": "hidloom.public-export-manifest.v2",
            "files": [
                {"path": "clean.py", "kind": "file", "mode": 0o644},
                {"path": "clean.js", "kind": "file", "mode": 0o644},
            ],
        }
        write(
            exported / "PUBLIC_EXPORT_MANIFEST.json",
            json.dumps(manifest, indent=2) + "\n",
        )
        raw = run(exported, check=True)
        assert "3 files from PUBLIC_EXPORT_MANIFEST.json" in raw.stdout
        write(exported / "clean.js", 'console.trace("leftover");\n')
        raw_invalid = run(exported, check=False)
        assert raw_invalid.returncode == 1
        assert "javascript_debug_output: clean.js" in raw_invalid.stderr
        assert not any(exported.rglob("__pycache__"))

    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "development-residue-hygiene:" in makefile
    assert "public-export-check: repository-hygiene source-syntax-hygiene development-residue-hygiene" in makefile

    private_export = ROOT / ".github" / "workflows" / "public-export-check.yml"
    if private_export.exists():
        workflow = private_export.read_text(encoding="utf-8")
        assert workflow.count("python3 script/test_development_residue_hygiene.py") == 2

    private_sync = ROOT / ".github" / "workflows" / "public-sync.yml"
    if private_sync.exists():
        workflow = private_sync.read_text(encoding="utf-8")
        assert workflow.count("python3 script/test_development_residue_hygiene.py") == 1

    public_ci = ROOT / ".github" / "workflows" / "public-ci.yml"
    if public_ci.exists():
        workflow = public_ci.read_text(encoding="utf-8")
        assert workflow.count("python3 script/test_development_residue_hygiene.py") == 1

    print("ok: development residue hygiene rejects debug and mechanical leftovers")


if __name__ == "__main__":
    main()
