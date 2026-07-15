#!/usr/bin/env python3
"""Ensure web icons are original, local, and reproducibly generated."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "daemon" / "http" / "static"
GENERATOR = ROOT / "tools" / "generate_hidloom_icons.py"
OUTPUTS = (
    "android-chrome-192x192.png",
    "android-chrome-512x512.png",
    "apple-touch-icon.png",
    "favicon-32x32.png",
    "favicon.ico",
    "hidloom-mark.svg",
)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        generated = Path(tmp) / "icons"
        subprocess.run(
            ["python3", str(GENERATOR), "--output-dir", str(generated)],
            check=True,
            capture_output=True,
            text=True,
        )
        for name in OUTPUTS:
            assert (generated / name).read_bytes() == (STATIC / name).read_bytes(), name

    index = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'type="image/svg+xml" href="/static/hidloom-mark.svg"' in index
    assert "keyboard-layout-editor.com/favicon.ico" not in index
    assert 'class="kle-open-icon" aria-hidden="true">KLE</span>' in index
    svg = (STATIC / "hidloom-mark.svg").read_text(encoding="utf-8")
    assert "HIDloom mark" in svg
    assert "Interwoven cyan and violet threads" in svg
    print("ok: HIDloom icon assets are local and reproducible")


if __name__ == "__main__":
    main()
