#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import hidloom_paths


DISPLAY_NAME_PATHS = (
    "README.md",
    "FRESH_INSTALL.md",
    "RELEASE_CHECKLIST.md",
    "docs/README.md",
    "docs/architecture/specification.md",
    "tools/package/build_deb_package.sh",
    "tools/package/build_device_profile_deb.sh",
)


def main() -> None:
    identity = json.loads((ROOT / "config" / "project-identity.json").read_text(encoding="utf-8"))
    assert identity["schema"] == "hidloom.project-identity.v1"
    assert identity["project_name"] == "HIDloom"
    assert identity["project_slug"] == "hidloom"
    assert identity["device_profiles"] == ["cqa02303v5"]
    assert identity["license"] == "GPL-3.0-or-later"
    assert identity["initial_public_version"] == "0.1.0"
    assert identity["copyright"] == {
        "model": "individual-contributors",
        "assignment_required": False,
        "public_notice": "HIDloom contributors",
    }
    authors = (ROOT / "AUTHORS.md").read_text(encoding="utf-8")
    assert "HIDloom contributors" in authors
    assert "does not require copyright assignment" in authors

    for relative_path in DISPLAY_NAME_PATHS:
        content = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "HIDloom" in content, relative_path

    assert hidloom_paths.default_config_file("keymap.json").name == "keymap.json"

    old = os.environ.get("HIDLOOM_RUNTIME_DIR")
    try:
        os.environ["HIDLOOM_RUNTIME_DIR"] = "/tmp/hidloom-runtime"
        assert hidloom_paths.runtime_dir() == Path("/tmp/hidloom-runtime")
    finally:
        if old is None:
            os.environ.pop("HIDLOOM_RUNTIME_DIR", None)
        else:
            os.environ["HIDLOOM_RUNTIME_DIR"] = old
    print("ok: HIDloom canonical identity and paths")


if __name__ == "__main__":
    main()
