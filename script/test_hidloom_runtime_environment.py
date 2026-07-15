#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hidloom_paths import environment_value


def main() -> None:
    registry = json.loads(
        (ROOT / "config/runtime-environment.json").read_text(encoding="utf-8")
    )
    assert registry["schema"] == "hidloom.runtime-environment.v1"
    assert registry["compatibility_aliases"] is False
    variables = set(registry["variables"])
    assert variables
    assert all(name.startswith("HIDLOOM_") for name in variables)

    consumers = {
        "HIDLOOM_REPO_ROOT": (
            "daemon/http/script_runner.py",
            "daemon/logicd/logicd.py",
            "daemon/logicd/macro.py",
            "daemon/logicd/sessiond_client.py",
            "system/systemd/btd.service",
            "config/default/script/KC_SH1.sh",
            "config/default/script/KC_SH2.sh",
            "config/default/script/KC_SH4.sh",
            "config/default/script/KC_SH7.sh",
            "config/default/script/KC_SH8.sh",
        ),
        "HIDLOOM_DEB_MAINTAINER": (
            "tools/package/build_deb_package.sh",
            "tools/package/build_device_profile_deb.sh",
        ),
    }
    for variable, paths in consumers.items():
        assert variable in variables
        for relative_path in paths:
            assert variable in (ROOT / relative_path).read_text(encoding="utf-8"), relative_path

    direct_consumers = {
        "SYSTEMD_ETC_DIR": "script/apply_device_profile.py",
        "RUNTIME_KEYMAP": "dev/mcp/keyboard/server.py",
        "RUNTIME_LED_STATE": "dev/mcp/keyboard/server.py",
        "RUNTIME_BLUETOOTH_HOSTS": "dev/mcp/keyboard/server.py",
        "RUNTIME_BOARD_PROFILE": "dev/mcp/keyboard/server.py",
        "HTTP_STATUS_URL": "dev/mcp/keyboard/server.py",
    }
    for suffix, relative_path in direct_consumers.items():
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        assert f'environment_value("{suffix}"' in text, relative_path

    path_source = (ROOT / "hidloom_paths.py").read_text(encoding="utf-8")
    for suffix in ("DEFAULT_CONFIG_DIR", "BOARD_PROFILES_DIR", "RUNTIME_DIR", "RUNTIME_SCRIPT_DIR"):
        assert f'environment_value("{suffix}"' in path_source, suffix

    original = os.environ.get("HIDLOOM_TEST_VALUE")
    try:
        os.environ.pop("HIDLOOM_TEST_VALUE", None)
        assert environment_value("TEST_VALUE", "default") == "default"
        os.environ["HIDLOOM_TEST_VALUE"] = "canonical"
        assert environment_value("TEST_VALUE", "default") == "canonical"
    finally:
        if original is None:
            os.environ.pop("HIDLOOM_TEST_VALUE", None)
        else:
            os.environ["HIDLOOM_TEST_VALUE"] = original

    print("ok: HIDloom runtime environment accepts canonical names only")


if __name__ == "__main__":
    main()
