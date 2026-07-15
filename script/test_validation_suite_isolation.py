#!/usr/bin/env python3
"""Verify canonical validation never builds inside a clean source checkout."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "script"))

import test_validation_suite as validation_suite  # noqa: E402


def main() -> None:
    suite_source = (ROOT / "script/test_validation_suite.py").read_text(encoding="utf-8")
    assert suite_source.index("sys.dont_write_bytecode = True") < suite_source.index(
        "from suite_runner import"
    )

    with tempfile.TemporaryDirectory() as temporary:
        fixture = Path(temporary) / "source"
        script = fixture / "script/test_validation_suite.py"
        script.parent.mkdir(parents=True)
        script.write_text(
            "from pathlib import Path\n"
            "Path('build').mkdir()\n"
            "Path('build/ignored-output').write_text('fixture\\n')\n",
            encoding="utf-8",
        )
        (fixture / ".gitignore").write_text("/build/\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=fixture, check=True)
        subprocess.run(["git", "config", "user.name", "HIDloom Test"], cwd=fixture, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.invalid"], cwd=fixture, check=True
        )
        subprocess.run(["git", "add", "."], cwd=fixture, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=fixture, check=True)

        previous_root = validation_suite.ROOT
        previous_snapshot = os.environ.pop("HIDLOOM_VALIDATION_SNAPSHOT", None)
        validation_suite.ROOT = fixture
        try:
            try:
                validation_suite.run_from_clean_snapshot()
            except SystemExit as exc:
                assert exc.code == 0
            else:
                raise AssertionError("clean source did not run through an isolated snapshot")
        finally:
            validation_suite.ROOT = previous_root
            if previous_snapshot is not None:
                os.environ["HIDLOOM_VALIDATION_SNAPSHOT"] = previous_snapshot

        assert not (fixture / "build").exists()
        assert subprocess.check_output(
            ["git", "status", "--porcelain=v1", "--ignored"], cwd=fixture, text=True
        ) == ""

    print("ok: validation suite isolates clean and dirty source checkouts")


if __name__ == "__main__":
    main()
