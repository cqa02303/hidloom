#!/usr/bin/env python3
"""Smoke tests for HTTP Settings API helpers."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon" / "http"))
sys.path.insert(0, str(ROOT))

import httpd  # noqa: E402
import settings_api  # noqa: E402


class FakeRequest:
    def __init__(self, body: dict) -> None:
        self._body = body

    async def json(self) -> dict:
        return self._body


async def _main_async() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "config.json"
        config_path.write_text(json.dumps({
            "settings": {
                "http_basic_auth": {
                    "username": "admin",
                    "password": "old-pass",
                }
            }
        }), encoding="utf-8")

        original_config = httpd.CONFIG_JSON
        original_username = httpd.HTTP_BASIC_AUTH_USERNAME
        original_password = httpd.HTTP_BASIC_AUTH_PASSWORD
        original_auth_file_fn = httpd._http_basic_auth_file
        original_gethostname = httpd.socket.gethostname
        original_i2cd_json = httpd.I2CD_JSON
        original_run_phase_calibration = settings_api.run_phase_calibration
        try:
            httpd.socket.gethostname = lambda: "node-01"  # type: ignore[assignment]
            assert httpd._resolve_initial_http_basic_auth_password("__HOSTNAME__") == "node-01"
            assert httpd._resolve_initial_http_basic_auth_password(None) == "node-01"
            assert httpd._resolve_initial_http_basic_auth_password("explicit-pass") == "explicit-pass"

            httpd.CONFIG_JSON = config_path
            auth_file = Path(tmpdir) / "http_basic_auth.json"
            httpd._http_basic_auth_file = lambda: auth_file  # type: ignore[assignment]
            httpd.HTTP_BASIC_AUTH_USERNAME = "admin"
            httpd.HTTP_BASIC_AUTH_PASSWORD = "old-pass"
            i2cd_path = Path(tmpdir) / "i2cd.json"
            i2cd_path.write_text(json.dumps({
                "analog_stick": {
                    "enabled": True,
                    "stick": 0,
                    "deadzone": 20,
                    "min_range_volts": 0.2,
                    "auto_center_on_start": True,
                    "auto_center_duration": 2.0,
                    "x": {"channel": 0, "center": 1.23, "low": 0.1, "high": 2.9, "invert": True},
                    "y": {"channel": 1, "center": 1.45, "low": 0.2, "high": 3.0, "invert": False},
                }
            }), encoding="utf-8")
            httpd.I2CD_JSON = i2cd_path

            bad = await httpd.handle_settings_http_auth(FakeRequest({
                "current_password": "wrong",
                "new_password": "new-pass",
                "confirm_password": "new-pass",
            }))
            assert bad.status == 403
            assert json.loads(bad.text)["result"] == "error"

            mismatch = await httpd.handle_settings_http_auth(FakeRequest({
                "current_password": "old-pass",
                "new_password": "new-pass",
                "confirm_password": "different",
            }))
            assert mismatch.status == 400

            ok = await httpd.handle_settings_http_auth(FakeRequest({
                "current_password": "old-pass",
                "new_password": "new-pass",
                "confirm_password": "new-pass",
            }))
            assert ok.status == 200
            assert json.loads(ok.text)["result"] == "ok"
            assert httpd.HTTP_BASIC_AUTH_PASSWORD.startswith("pbkdf2_sha256$")
            assert httpd._verify_http_basic_auth_password("new-pass", httpd.HTTP_BASIC_AUTH_PASSWORD)

            stored_config = json.loads(config_path.read_text(encoding="utf-8"))
            assert stored_config["settings"]["http_basic_auth"]["password"] == "old-pass"
            stored_auth = json.loads(auth_file.read_text(encoding="utf-8"))
            assert stored_auth["username"] == "admin"
            assert "password" not in stored_auth
            assert stored_auth["password_hash"].startswith("pbkdf2_sha256$")
            assert "new-pass" not in auth_file.read_text(encoding="utf-8")
            if os.name != "nt":
                assert auth_file.stat().st_mode & 0o777 == 0o600

            settings_get = await httpd.handle_settings_get(FakeRequest({}))
            payload = json.loads(settings_get.text)
            assert payload["result"] == "ok"
            assert payload["send_strings"] == {}
            assert payload["send_string_validation"]["valid"] is True
            assert payload["analog_stick_calibration"]["x"]["center"] == 1.23
            assert abs(payload["analog_stick_calibration"]["x"]["span"] - 2.8) < 0.000001
            assert payload["analog_stick_calibration"]["x"]["center_valid"] is True
            assert payload["analog_stick_calibration"]["x"]["span_valid"] is True
            assert payload["analog_stick_calibration"]["x"]["valid"] is True
            assert payload["analog_stick_calibration"]["y"]["high"] == 3.0
            assert payload["analog_stick_calibration"]["center_valid"] is True
            assert payload["analog_stick_calibration"]["span_valid"] is True
            assert payload["analog_stick_calibration"]["valid"] is True
            assert payload["analog_stick_calibration"]["errors"] == []
            assert payload["analog_stick_calibration"]["min_range_volts"] == 0.2

            i2cd_path.write_text(json.dumps({
                "analog_stick": {
                    "enabled": True,
                    "min_range_volts": 0.2,
                    "x": {"channel": 0, "center": 3.1, "low": 0.1, "high": 2.9},
                    "y": {"channel": 1, "center": 1.45, "low": 1.40, "high": 1.45},
                }
            }), encoding="utf-8")
            invalid_settings_get = await httpd.handle_settings_get(FakeRequest({}))
            invalid_payload = json.loads(invalid_settings_get.text)
            invalid_stick = invalid_payload["analog_stick_calibration"]
            assert invalid_stick["valid"] is False
            assert invalid_stick["x"]["center_valid"] is False
            assert invalid_stick["y"]["span_valid"] is False
            assert "x.center must be between low and high" in invalid_stick["errors"]
            assert any(error.startswith("y.span ") for error in invalid_stick["errors"])
            i2cd_path.write_text(json.dumps({
                "analog_stick": {
                    "enabled": True,
                    "stick": 0,
                    "deadzone": 20,
                    "min_range_volts": 0.2,
                    "auto_center_on_start": True,
                    "auto_center_duration": 2.0,
                    "x": {"channel": 0, "center": 1.23, "low": 0.1, "high": 2.9, "invert": True},
                    "y": {"channel": 1, "center": 1.45, "low": 0.2, "high": 3.0, "invert": False},
                }
            }), encoding="utf-8")

            invalid_send_strings = await httpd.handle_settings_send_strings(FakeRequest({
                "send_strings": {"bad": {"text": "line\nbreak", "enabled": True}},
                "reload": False,
            }))
            assert invalid_send_strings.status == 400
            invalid_payload = json.loads(invalid_send_strings.text)
            assert invalid_payload["result"] == "error"
            assert "newline requires allow_newline" in invalid_payload["send_string_validation"]["entries"][0]["errors"]

            ok_send_strings = await httpd.handle_settings_send_strings(FakeRequest({
                "send_strings": {"kana_a": {"text": "あ", "enabled": True}},
                "reload": False,
            }))
            assert ok_send_strings.status == 200
            send_payload = json.loads(ok_send_strings.text)
            assert send_payload["result"] == "ok"
            assert send_payload["send_string_validation"]["valid"] is True
            assert send_payload["send_strings"]["kana_a"]["text"] == "あ"
            stored_config = json.loads(config_path.read_text(encoding="utf-8"))
            assert stored_config["settings"]["send_strings"]["kana_a"]["enabled"] is True

            calls = []

            def fake_run_phase_calibration(**kwargs):
                calls.append(kwargs)
                return {
                    "phase": kwargs["phase"],
                    "samples": 3,
                    "x": {"center": 1.23} if kwargs["phase"] == "center" else {"low": 0.1, "high": 2.9},
                    "y": {"center": 1.45} if kwargs["phase"] == "center" else {"low": 0.2, "high": 3.0},
                    "written": kwargs["write"],
                    "config": str(kwargs["config_path"]),
                }

            settings_api.run_phase_calibration = fake_run_phase_calibration  # type: ignore[assignment]
            center = await httpd.handle_settings_analog_stick_calibration(FakeRequest({
                "phase": "center",
                "duration": 1.5,
                "write": True,
            }))
            center_payload = json.loads(center.text)
            assert center.status == 200
            assert center_payload["result"] == "ok"
            assert center_payload["x"]["center"] == 1.23
            assert calls[-1]["config_path"] == i2cd_path
            assert calls[-1]["phase"] == "center"
            assert calls[-1]["duration"] == 1.5
            assert calls[-1]["min_range_volts"] == 0.2
            assert calls[-1]["write"] is True

            validate_call_count = len(calls)
            validation = await httpd.handle_settings_analog_stick_calibration(FakeRequest({
                "phase": "validate",
            }))
            validation_payload = json.loads(validation.text)
            assert validation.status == 200
            assert validation_payload["min_range_volts"] == 0.2
            assert validation_payload["valid"] is True
            assert validation_payload["x"]["span_valid"] is True
            assert abs(validation_payload["y"]["span"] - 2.8) < 0.000001
            assert len(calls) == validate_call_count

            range_missing_confirm = await httpd.handle_settings_analog_stick_calibration(FakeRequest({
                "phase": "range",
                "duration": 1.5,
                "write": True,
            }))
            assert range_missing_confirm.status == 400
            assert "confirm_range=true" in json.loads(range_missing_confirm.text)["msg"]

            range_dry_run = await httpd.handle_settings_analog_stick_calibration(FakeRequest({
                "phase": "range",
                "duration": 1.5,
                "write": False,
            }))
            assert range_dry_run.status == 200
            assert json.loads(range_dry_run.text)["x"]["low"] == 0.1

            range_confirmed = await httpd.handle_settings_analog_stick_calibration(FakeRequest({
                "phase": "range",
                "duration": 1.5,
                "write": True,
                "confirm_range": True,
            }))
            assert range_confirmed.status == 200
            assert json.loads(range_confirmed.text)["written"] is True

            bad_phase = await httpd.handle_settings_analog_stick_calibration(FakeRequest({"phase": "bad"}))
            assert bad_phase.status == 400
        finally:
            httpd.CONFIG_JSON = original_config
            httpd.HTTP_BASIC_AUTH_USERNAME = original_username
            httpd.HTTP_BASIC_AUTH_PASSWORD = original_password
            httpd._http_basic_auth_file = original_auth_file_fn  # type: ignore[assignment]
            httpd.socket.gethostname = original_gethostname  # type: ignore[assignment]
            httpd.I2CD_JSON = original_i2cd_json
            settings_api.run_phase_calibration = original_run_phase_calibration  # type: ignore[assignment]


def main() -> None:
    asyncio.run(_main_async())
    print("ok: HTTP Settings API updates Basic auth password")


if __name__ == "__main__":
    main()
