#!/usr/bin/env python3
"""Regression tests for bounded ignored-workspace debris cleanup."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/workspace_debris_hygiene.py"


def run(root: Path, *args: str, check: bool) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), "--root", str(root), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def write(path: Path, content: str = "fixture\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def main() -> None:
    current = run(ROOT, check=True)
    assert "operator state preserved" in current.stdout

    with tempfile.TemporaryDirectory() as temporary:
        fixture = Path(temporary) / "repository"
        fixture.mkdir()
        git(fixture, "init", "-q")
        git(fixture, "config", "user.name", "HIDloom fixture")
        git(fixture, "config", "user.email", "fixture@example.invalid")

        secret = "fixture-secret-value"
        environment_text = f"HIDLOOM_SECRET={secret}\n"
        write(fixture / ".env", environment_text)
        disposable = (
            fixture / ".pytest_cache/v/cache/nodeids",
            fixture / "daemon/logicd/__pycache__/logicd.pyc",
            fixture / "orphan.pyc",
            fixture / ".coverage",
        )
        for path in disposable:
            write(path)

        review_backup = fixture / "config/device.json.bak"
        nested_environment = fixture / "operator/.env.local"
        write(review_backup, secret)
        write(nested_environment, secret)

        preserved = (
            fixture / ".venv/lib/__pycache__/dependency.pyc",
            fixture / "build/output/__pycache__/builder.pyc",
            fixture / "tools/crate/target/debug/cache.pyc",
            fixture / "demo/assets/__pycache__/preview.pyc",
        )
        for path in preserved:
            write(path)

        tracked = fixture / "tracked.pyc"
        write(tracked)
        git(fixture, "add", "-f", "tracked.pyc")
        git(fixture, "commit", "-qm", "Track fixture debris")

        external = Path(temporary) / "external-cache"
        marker = external / "keep.txt"
        write(marker)
        linked = fixture / "linked/__pycache__"
        linked.parent.mkdir(parents=True)
        linked.symlink_to(external, target_is_directory=True)

        failed = run(fixture, check=False)
        assert failed.returncode == 1
        assert "disposable_workspace_directory" in failed.stderr
        assert "disposable_workspace_file" in failed.stderr
        assert "review_workspace_file" in failed.stderr
        assert "review_environment_file" in failed.stderr
        assert "tracked_workspace_debris" in failed.stderr
        assert "review_workspace_symlink" in failed.stderr
        assert secret not in failed.stdout + failed.stderr

        cleaned = run(fixture, "--clean", check=False)
        assert cleaned.returncode == 1
        assert cleaned.stdout.count("removed:") == 4
        assert all(not path.exists() for path in disposable)
        assert all(path.is_file() for path in preserved)
        assert review_backup.is_file()
        assert review_backup.read_text(encoding="utf-8") == secret
        assert nested_environment.is_file()
        assert nested_environment.read_text(encoding="utf-8") == secret
        assert tracked.is_file()
        assert linked.is_symlink()
        assert marker.is_file()
        assert marker.read_text(encoding="utf-8") == "fixture\n"
        assert (fixture / ".env").read_text(encoding="utf-8") == environment_text
        assert secret not in cleaned.stdout + cleaned.stderr

        review_backup.unlink()
        nested_environment.unlink()
        linked.unlink()
        git(fixture, "rm", "-q", "tracked.pyc")
        clean = run(fixture, check=True)
        assert "operator state preserved" in clean.stdout
        assert (fixture / ".env").is_file()
        assert secret not in clean.stdout + clean.stderr

    with tempfile.TemporaryDirectory() as temporary:
        exported = Path(temporary)
        tracked_coverage = exported / ".coverage"
        write(tracked_coverage)
        manifest = {
            "files": [
                {
                    "path": ".coverage",
                    "mode": "0644",
                    "sha256": "fixture",
                    "size": tracked_coverage.stat().st_size,
                }
            ]
        }
        write(
            exported / "PUBLIC_EXPORT_MANIFEST.json",
            json.dumps(manifest, indent=2) + "\n",
        )
        refused = run(exported, "--clean", check=False)
        assert refused.returncode == 1
        assert "tracked_workspace_debris: .coverage" in refused.stderr
        assert tracked_coverage.is_file()

    print("ok: workspace debris cleanup is bounded and preserves operator state")


if __name__ == "__main__":
    main()
