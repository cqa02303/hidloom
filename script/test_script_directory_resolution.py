#!/usr/bin/env python3
"""Smoke-test KC_SH script directory priority for logicd and HTTP UI."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "daemon" / "http"))

if "aiohttp" not in sys.modules:
    fake_web = types.SimpleNamespace(
        middleware=lambda fn: fn,
        HTTPUnauthorized=RuntimeError,
        WebSocketResponse=object,
        Request=object,
        Handler=object,
        StreamResponse=object,
        Response=object,
        Application=object,
        json_response=lambda *args, **kwargs: {"args": args, "kwargs": kwargs},
    )
    sys.modules["aiohttp"] = types.SimpleNamespace(web=fake_web)

import httpd  # noqa: E402
import script_store  # noqa: E402
from logicd import logicd  # noqa: E402
from logicd.ctrl import script_dirs_from_config  # noqa: E402
from logicd.hid_report import HidState  # noqa: E402
from logicd.macro import MacroExecutor  # noqa: E402


def write_script(directory: Path, name: str, label: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.sh"
    path.write_text(
        f"#!/bin/sh\n# @label {label}\necho {name}\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o755)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        configured = root / "configured"
        runtime = root / "runtime"
        fallback = root / "fallback"
        config_json = root / "config.json"
        keycodes_json = root / "keycodes.json"
        config_json.write_text(
            json.dumps({"settings": {"script_dir": str(configured)}}) + "\n",
            encoding="utf-8",
        )
        keycodes_json.write_text(
            json.dumps({"KC_SH0": {}, "KC_SH1": {}, "KC_SH2": {}, "KC_NO": {}, "KC_SHUTDOWN": {}}) + "\n",
            encoding="utf-8",
        )

        write_script(configured, "KC_SH0", "configured zero")
        write_script(runtime, "KC_SH0", "runtime zero")
        write_script(runtime, "KC_SH1", "runtime one")
        write_script(fallback, "KC_SH1", "fallback one")
        write_script(fallback, "KC_SH2", "fallback two")

        old_http_config = httpd.CONFIG_JSON
        old_http_default = httpd.DEFAULT_SCRIPT_DIR
        old_http_fallback = httpd.FALLBACK_SCRIPT_DIR
        old_script_store_keycodes = script_store.KEYCODES_JSON
        old_logicd_default = logicd.DEFAULT_SCRIPT_DIR
        old_logicd_fallback = logicd.FALLBACK_SCRIPT_DIR
        try:
            httpd.CONFIG_JSON = config_json
            httpd.DEFAULT_SCRIPT_DIR = runtime
            httpd.FALLBACK_SCRIPT_DIR = fallback
            script_store.KEYCODES_JSON = keycodes_json
            logicd.DEFAULT_SCRIPT_DIR = str(runtime)
            logicd.FALLBACK_SCRIPT_DIR = str(fallback)

            assert script_dirs_from_config(
                {"settings": {"script_dir": str(configured)}},
                logicd.DEFAULT_SCRIPT_DIR,
                logicd.FALLBACK_SCRIPT_DIR,
            ) == [
                str(configured),
                str(runtime),
                str(fallback),
            ]

            entries = httpd._iter_script_entries()
            labels = {entry["keycode"]: entry["label"] for entry in entries}
            paths = {entry["keycode"]: Path(entry["path"]).parent for entry in entries}
            assert [entry["keycode"] for entry in entries] == ["KC_SH0", "KC_SH1", "KC_SH2"]
            assert labels == {
                "KC_SH0": "configured zero",
                "KC_SH1": "runtime one",
                "KC_SH2": "fallback two",
            }
            assert paths == {
                "KC_SH0": configured,
                "KC_SH1": runtime,
                "KC_SH2": fallback,
            }
            assert httpd._valid_script_keycode("KC_SH2")
            assert not httpd._valid_script_keycode("KC_SH3")

            executor = MacroExecutor(HidState(), lambda report: None, {}, script_dir=[
                str(configured),
                str(runtime),
                str(fallback),
            ])
            assert executor._resolve_shell_script("KC_SH0") == str(configured / "KC_SH0.sh")
            assert executor._resolve_shell_script("KC_SH1") == str(runtime / "KC_SH1.sh")
            assert executor._resolve_shell_script("KC_SH2") == str(fallback / "KC_SH2.sh")
            script_env = executor._shell_script_env()
            assert script_env["PATH"].split(os.pathsep)[0] == str(ROOT / "bin")
            assert script_env["HIDLOOM_REPO_ROOT"] == str(ROOT)
            assert script_env["HIDLOOM_REPO_ROOT"] == str(ROOT)
            if os.name == "nt":
                print("skip: shell script execution requires POSIX")
                return

            bash_script = configured / "KC_SH0.sh"
            bash_script.write_text(
                "#!/bin/bash\n# @label bash only\nset -euo pipefail\n[[ 1 -eq 1 ]]\n",
                encoding="utf-8",
            )
            os.chmod(bash_script, 0o755)
            exits: list[tuple[str, int]] = []
            reports: list[tuple[str, str, str, int]] = []
            hid_reports: list[bytes] = []
            executor = MacroExecutor(
                HidState(),
                lambda report: hid_reports.append(bytes(report)),
                {},
                script_dir=[str(configured)],
                script_exit_notify=lambda name, code: exits.append((name, code)),
                script_report_notify=lambda name, sink, text, code: reports.append((name, sink, text, code)),
            )
            asyncio.run(executor._run_shell_script("KC_SH0"))
            assert exits == [("KC_SH0", 0)]
            assert reports == []
            assert hid_reports == []

            bash_script.write_text(
                "#!/bin/bash\n"
                "# @label report opt-in\n"
                "# @report hid_text\n"
                "# @report-ansi visible\n"
                "set -euo pipefail\n"
                "printf '\\033[31mhello\\033[0m\\n'\n"
                "printf 'warn\\n' >&2\n",
                encoding="utf-8",
            )
            os.chmod(bash_script, 0o755)
            exits.clear()
            reports.clear()
            hid_reports.clear()
            asyncio.run(executor._run_shell_script("KC_SH0"))
            assert exits == [("KC_SH0", 0)]
            assert len(reports) == 1
            assert reports[0][0] == "KC_SH0"
            assert reports[0][1] == "hid_text"
            assert "^[" in reports[0][2]
            assert "hello" in reports[0][2]
            assert "[stderr]" in reports[0][2]
            assert "warn" in reports[0][2]
            assert reports[0][3] == 0
            assert hid_reports

            bash_script.write_text(
                "#!/bin/bash\n"
                "# @label report truncation\n"
                "# @report hid_text\n"
                "# @report-max-bytes 4\n"
                "printf 'abcdefgh\\n'\n",
                encoding="utf-8",
            )
            os.chmod(bash_script, 0o755)
            exits.clear()
            reports.clear()
            hid_reports.clear()
            asyncio.run(executor._run_shell_script("KC_SH0"))
            assert exits == [("KC_SH0", 0)]
            assert len(reports) == 1
            assert "abcd" in reports[0][2]
            assert "efgh" not in reports[0][2]
            assert "[truncated to 4 bytes]" in reports[0][2]
            assert hid_reports

            bash_script.write_text(
                "#!/bin/bash\n"
                "# @label report failure\n"
                "# @report hid_text\n"
                "printf 'before-fail\\n'\n"
                "exit 7\n",
                encoding="utf-8",
            )
            os.chmod(bash_script, 0o755)
            exits.clear()
            reports.clear()
            hid_reports.clear()
            asyncio.run(executor._run_shell_script("KC_SH0"))
            assert exits == [("KC_SH0", 7)]
            assert len(reports) == 1
            assert reports[0][3] == 7
            assert "before-fail" in reports[0][2]
            assert hid_reports
        finally:
            httpd.CONFIG_JSON = old_http_config
            httpd.DEFAULT_SCRIPT_DIR = old_http_default
            httpd.FALLBACK_SCRIPT_DIR = old_http_fallback
            script_store.KEYCODES_JSON = old_script_store_keycodes
            logicd.DEFAULT_SCRIPT_DIR = old_logicd_default
            logicd.FALLBACK_SCRIPT_DIR = old_logicd_fallback

    print("ok: script directory priority matches between logicd and HTTP UI")


if __name__ == "__main__":
    main()
