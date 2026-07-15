#!/usr/bin/env python3
"""Build regression test for matrixd C sources."""
from __future__ import annotations

import shutil
import subprocess
import sysconfig
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    if shutil.which("gcc") is None:
        raise SystemExit("gcc is required for matrixd build test")

    source = (ROOT / "daemon" / "matrixd" / "matrixd.c").read_text(encoding="utf-8")
    assert "MATRIXD_EVENT_LOG_PATH" in source
    assert "matrixd_log_event" in source
    assert "matrixd_log_debounce" in source
    assert "matrixd_debounce" in source
    assert "matrixd_event" in source
    assert "key_active_seen" in source
    assert "tap_socket_path" in source
    assert "TAP_CONNECT_RETRY_MS" in source
    assert "matrix tap" in source
    assert "startup_quiet_ms" in source
    assert "startup_quiet_until_us" in source

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / f"matrixd{sysconfig.get_config_var('EXE') or ''}"
        subprocess.run(
            [
                "gcc",
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-O2",
                "-D_POSIX_C_SOURCE=200809L",
                "-I",
                str(ROOT / "daemon" / "matrixd"),
                str(ROOT / "daemon" / "matrixd" / "matrixd.c"),
                str(ROOT / "daemon" / "matrixd" / "debounce.c"),
                "-o",
                str(out),
            ],
            check=True,
        )
        assert out.exists()

    print("ok: matrixd C sources build")


if __name__ == "__main__":
    main()
