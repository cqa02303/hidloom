#!/usr/bin/env python3
"""Regression checks for the module structure document."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    doc = (ROOT / "docs" / "architecture" / "module-structure.md").read_text(encoding="utf-8")
    paths = re.findall(
        r"`((?:daemon/)?(?:logicd|http|btd|ledd|viald|spid)/[^`]+\.(?:py|js))`",
        doc,
    )
    assert paths, "no module paths found"
    missing = [path for path in paths if not (ROOT / path).exists()]
    assert not missing, f"documented module paths do not exist: {missing}"

    for required in [
        "daemon/logicd/logicd.py",
        "daemon/logicd/ctrl.py",
        "daemon/http/system_api.py",
        "daemon/http/static/status_panel.js",
        "daemon/btd/bluez_backend.py",
        "daemon/ledd/ledd.py",
        "daemon/ledd/direct_frame_socket.py",
        "daemon/viald/protocol.py",
    ]:
        assert required in doc, required

    assert "direct-frame" in doc
    assert "python3 script/test_validation_suite.py" in doc
    print("ok: module structure document is current")


if __name__ == "__main__":
    main()
