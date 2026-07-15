#!/usr/bin/env python3
"""Regression tests for value-safe local dotenv hygiene."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/local_environment_hygiene.py"
RETIRED_PREFIX = "C" + "QA_"
REWRITE_CONFIRMATION = "REWRITE-LOCAL-ENV-KEYS"


def run(
    root: Path,
    env_file: Path,
    *args: str,
    check: bool,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--root",
            str(root),
            "--env-file",
            str(env_file),
            *args,
        ],
        capture_output=True,
        text=True,
        check=check,
    )


def main() -> None:
    example = run(ROOT, ROOT / ".env.example", check=True)
    assert "4 assignments" in example.stdout
    assert "keyboard.example" not in example.stdout

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        env_file = root / ".env"
        missing = run(root, env_file, check=True)
        assert "no local environment file" in missing.stdout

        secret = "fixture-secret-value"
        env_file.write_text(
            "HIDLOOM_ACTIVE_DEVICE=XX\n"
            f"HIDLOOM_HTTPD_BASIC_AUTH_PASSWORD={secret}\n"
            "PATH=/usr/bin\n",
            encoding="utf-8",
        )
        env_file.chmod(0o600)
        canonical = run(root, env_file, check=True)
        assert "3 assignments" in canonical.stdout
        assert secret not in canonical.stdout + canonical.stderr

        retired_key = RETIRED_PREFIX + "SSH_TARGET"
        env_file.write_text(f"{retired_key}={secret}\n", encoding="utf-8")
        retired = run(root, env_file, check=False)
        assert retired.returncode == 1
        assert f"key={retired_key}" in retired.stderr
        assert "replacement=HIDLOOM_SSH_TARGET" in retired.stderr
        assert secret not in retired.stdout + retired.stderr

        device_key = RETIRED_PREFIX + "DEVICE_XX_SSH_TARGET"
        value_marker = "value-" + RETIRED_PREFIX + "UNCHANGED"
        original = (
            "# preserve comments and spacing\n"
            f" export {retired_key} = {secret}\n"
            f"{device_key}='{value_marker}'"
        )
        env_file.write_text(original, encoding="utf-8")
        env_file.chmod(0o600)
        planned = run(root, env_file, "--rewrite-retired-keys", check=True)
        assert planned.stdout.count("rewrite: key=") == 2
        assert "plan: 2 key(s)" in planned.stdout
        assert env_file.read_text(encoding="utf-8") == original
        assert secret not in planned.stdout + planned.stderr
        assert value_marker not in planned.stdout + planned.stderr

        wrong_confirmation = run(
            root,
            env_file,
            "--rewrite-retired-keys",
            "--apply",
            "--confirm",
            "WRONG-CONFIRMATION",
            check=False,
        )
        assert wrong_confirmation.returncode == 1
        assert env_file.read_text(encoding="utf-8") == original
        assert secret not in wrong_confirmation.stdout + wrong_confirmation.stderr

        applied = run(
            root,
            env_file,
            "--rewrite-retired-keys",
            "--apply",
            "--confirm",
            REWRITE_CONFIRMATION,
            check=True,
        )
        expected = original.replace(retired_key, "HIDLOOM_SSH_TARGET", 1).replace(
            device_key,
            "HIDLOOM_DEVICE_XX_SSH_TARGET",
            1,
        )
        assert env_file.read_bytes() == expected.encode("utf-8")
        assert env_file.stat().st_mode & 0o777 == 0o600
        assert not list(root.glob(".env.hidloom-key-rewrite.*"))
        assert "rewrote 2 local environment key(s) atomically" in applied.stdout
        assert "no backup was created" in applied.stdout
        assert secret not in applied.stdout + applied.stderr
        assert value_marker not in applied.stdout + applied.stderr
        run(root, env_file, check=True)

        collision = (
            f"{retired_key}={secret}\n"
            "HIDLOOM_SSH_TARGET=canonical-fixture-value\n"
        )
        env_file.write_text(collision, encoding="utf-8")
        collision_plan = run(root, env_file, "--rewrite-retired-keys", check=False)
        assert collision_plan.returncode == 1
        assert "environment_rewrite_collision" in collision_plan.stderr
        assert env_file.read_text(encoding="utf-8") == collision
        assert secret not in collision_plan.stdout + collision_plan.stderr
        assert "canonical-fixture-value" not in collision_plan.stdout + collision_plan.stderr

        env_file.write_text(
            "HIDLOOM_SSH_TARGET=first\nHIDLOOM_SSH_TARGET=second\n",
            encoding="utf-8",
        )
        duplicate = run(root, env_file, check=False)
        assert duplicate.returncode == 1
        assert "duplicate_environment_name" in duplicate.stderr
        assert "first" not in duplicate.stderr
        assert "second" not in duplicate.stderr

        env_file.write_text("not an assignment with secret material\n", encoding="utf-8")
        malformed = run(root, env_file, check=False)
        assert malformed.returncode == 1
        assert "invalid_environment_assignment" in malformed.stderr
        assert "secret material" not in malformed.stderr

        env_file.write_text("HIDLOOM_SSH_TARGET=keyboard.example\n", encoding="utf-8")
        env_file.chmod(0o644)
        insecure = run(root, env_file, check=False)
        assert insecure.returncode == 1
        assert "insecure_environment_mode" in insecure.stderr
        assert "keyboard.example" not in insecure.stderr

        env_file.write_text(f"{retired_key}={secret}\n", encoding="utf-8")
        insecure_plan = run(root, env_file, "--rewrite-retired-keys", check=False)
        assert insecure_plan.returncode == 1
        assert "insecure_environment_mode" in insecure_plan.stderr
        assert env_file.read_text(encoding="utf-8") == f"{retired_key}={secret}\n"
        assert secret not in insecure_plan.stdout + insecure_plan.stderr

        target = root / "target.env"
        target.write_text("HIDLOOM_ACTIVE_DEVICE=XX\n", encoding="utf-8")
        env_file.unlink()
        env_file.symlink_to(target)
        symlink = run(root, env_file, check=False)
        assert symlink.returncode == 1
        assert "symlink_environment_file" in symlink.stderr
        symlink_rewrite = run(root, env_file, "--rewrite-retired-keys", check=False)
        assert symlink_rewrite.returncode == 1
        assert "symlink_environment_file" in symlink_rewrite.stderr
        assert target.read_text(encoding="utf-8") == "HIDLOOM_ACTIVE_DEVICE=XX\n"

    print("ok: local environment hygiene never exposes dotenv values")


if __name__ == "__main__":
    main()
