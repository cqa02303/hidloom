#!/usr/bin/env python3
"""Actual HTTP route regression: runtime writes preserve immutable defaults."""
import asyncio
import base64
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "daemon/http"), str(ROOT)]
import httpd
import interaction_api
import settings_api
from vil_macro_import import apply_vial_macro_buffer


class Request:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


async def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        defaults, runtime = root / "defaults", root / "runtime"
        defaults.mkdir()
        runtime.mkdir()
        default_config = defaults / "config.json"
        runtime_config = runtime / "config.json"
        vial = defaults / "vial.json"
        vial.write_text('{"matrix":{"rows":2,"cols":2}}')
        document = {"settings": {"interaction": {"tapping_term": 0.2}, "http_basic_auth": {"username": "fixture", "password": "fixture-only"}}, "macros": {"USER": ["KC_A"]}, "unknown": {"preserve": 7}}
        default_config.write_text(json.dumps(document))
        immutable = default_config.read_bytes()
        with patch.dict(os.environ, {"HIDLOOM_DEFAULT_CONFIG_DIR": str(defaults), "HIDLOOM_RUNTIME_DIR": str(runtime)}), patch.object(httpd, "CONFIG_JSON", default_config), patch.object(httpd, "VIAL_JSON", vial):
            for present in (False, True):
                if present:
                    latest = json.loads(runtime_config.read_text())
                    latest["latest"] = "untouched"
                    runtime_config.write_text(json.dumps(latest))
                response = await httpd.handle_interaction_put(Request({"settings": {"tapping_term": 0.321}, "reload": False}))
                assert response.status == 200, response.text
                assert default_config.read_bytes() == immutable, "HTTP wrote packaged defaults"
                result = json.loads(runtime_config.read_text())
                assert result["settings"]["interaction"]["tapping_term"] == 0.321
                assert result["unknown"] == document["unknown"]
                assert result["macros"] == document["macros"]
                if present:
                    assert result["latest"] == "untouched"
                response = await httpd.handle_interaction_get(Request({}))
                assert json.loads(response.text)["raw"]["tapping_term"] == 0.321
            auth_source = []
            with patch.object(httpd, "load_http_basic_auth", side_effect=lambda path, *args: auth_source.append(path)), patch.object(httpd, "load_tls_paths", side_effect=lambda path, *args: auth_source.append(path)):
                httpd._load_http_basic_auth()
                httpd._load_tls_paths()
            assert auth_source == [default_config, default_config]
            apply_vial_macro_buffer(runtime_config, base64.b64encode(b"\x00").decode())
            assert json.loads(runtime_config.read_text())["macros"]["USER"] == ["KC_A"]
            before = runtime_config.read_bytes()
            with patch.object(interaction_api.os, "replace", side_effect=OSError("fixture interruption")):
                response = await httpd.handle_interaction_put(Request({"settings": {"tapping_term": 0.5}, "reload": False}))
                assert response.status == 500
            assert runtime_config.read_bytes() == before
            runtime_config.write_text("malformed existing runtime")
            response = await httpd.handle_interaction_put(Request({"settings": {}, "reload": False}))
            assert response.status == 500
            assert runtime_config.read_text() == "malformed existing runtime"
            assert default_config.read_bytes() == immutable
    print("http runtime config: ok")


if __name__ == "__main__":
    asyncio.run(main())
