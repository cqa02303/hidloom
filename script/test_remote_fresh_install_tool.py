#!/usr/bin/env python3
"""Regression checks for remote fresh install helper."""
from __future__ import annotations

from pathlib import Path
import sys
import tarfile
import tempfile

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import remote_fresh_install as remote  # noqa: E402


def main() -> None:
    remote_target = "pi" + "@" + "keyboard.test"
    assert remote.safe_name(remote_target) == "pi_keyboard.test"
    assert remote.should_exclude(".git/config")
    assert remote.should_exclude(".venv/bin/python")
    assert remote.should_exclude(".tmp-test/file", is_dir=True)
    assert remote.should_exclude("build/artifacts/example.txt")
    assert remote.should_exclude("daemon/matrixd/matrixd")
    assert not remote.should_exclude("system/install/setup_fresh_rpi.sh")
    assert remote.should_normalize_lf("setup_fresh_rpi.sh", b"#!/bin/bash\r\n")
    assert remote.should_normalize_lf("system/systemd/logicd.service", b"[Unit]\r\n")
    assert remote.should_normalize_lf("build/buildroot/example", b"text\r\n")
    assert not remote.should_normalize_lf("README.md", b"# Title\r\n")

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        archive = remote.create_archive(out, "test")
        assert archive.exists()
        with tarfile.open(archive, "r:gz") as tar:
            names = set(tar.getnames())
            assert "setup_fresh_rpi.sh" in names
            assert "system/install/setup_fresh_rpi.sh" in names
            assert "daemon/matrixd/matrixd" not in names
            setup_member = tar.extractfile("setup_fresh_rpi.sh")
            assert setup_member is not None
            setup = setup_member.read()
            assert b"\r\n" not in setup

    readme = (ROOT / "tools" / "README.md").read_text(encoding="utf-8")
    assert "remote_fresh_install.py" in readme
    assert "--run-setup" in readme
    assert not any((ROOT / "tools").rglob("*.pyc"))

    print("ok: remote fresh install helper")


if __name__ == "__main__":
    main()
