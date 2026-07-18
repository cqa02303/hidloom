#!/usr/bin/env python3
"""Regression tests for side-effect-free HTTP system status helpers."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon" / "http"))

import status_api  # noqa: E402
import system_api  # noqa: E402
from system_api import (  # noqa: E402
    board_profile_status,
    hidd_status,
    ledd_direct_frame_status,
    logicd_runtime_environment,
    output_display_label,
    output_status,
    outputd_status,
    resolve_output_state,
    spid_status,
    usbd_status,
)

STATUS_JS = ROOT / "daemon" / "http" / "static" / "status_panel.js"
STATUS_CSS = ROOT / "daemon" / "http" / "static" / "status_panel.css"
INTERACTION_CSS = ROOT / "daemon" / "http" / "static" / "interaction_panel.css"


async def _fake_run_text(*cmd: str, timeout: float = 3.0) -> tuple[int, str, str]:
    joined = " ".join(cmd)
    if joined == "systemctl is-active bluetooth":
        return 0, "active\n", ""
    if joined == "systemctl show logicd -p Environment --no-pager":
        return 0, "Environment=LOGICD_OUTPUTS=auto BTD_EVENTS_SOCK=/tmp/service-btd.sock\n", ""
    if joined == "systemctl is-active --quiet logicd-companion":
        return 0, "", ""
    if joined == "systemctl show logicd-companion -p Environment --no-pager":
        return 0, "Environment=LOGICD_OUTPUTS=debug LOGICD_NATIVE_OUTPUTD_CTRL=1\n", ""
    if joined == "bluetoothctl show":
        return 0, "Powered: yes\nDiscoverable: no\nPairable: yes\n", ""
    if joined == "bluetoothctl paired-devices":
        return 1, "", "Invalid command in menu main: paired-devices\n"
    if joined == "bluetoothctl devices":
        return 0, "Device aa:bb:cc:dd:ee:ff Host One\nDevice 11:22:33:44:55:66 Host Two\n", ""
    if joined == "bluetoothctl devices Connected":
        return 0, "Device 11:22:33:44:55:66 Host Two\n", ""
    if joined == "bluetoothctl info AA:BB:CC:DD:EE:FF":
        return 0, "Name: Host One\nPaired: yes\nBonded: yes\nTrusted: yes\nConnected: no\n", ""
    if joined == "bluetoothctl info 11:22:33:44:55:66":
        return 0, "Name: Host Two\nPaired: no\nBonded: no\nTrusted: no\nConnected: yes\n", ""
    raise AssertionError(f"unexpected command: {cmd!r}")


async def _assert_bluetooth_and_btd_status_helpers() -> None:
    original = system_api._run_text
    calls: list[tuple[str, ...]] = []

    async def counting_run_text(*cmd: str, timeout: float = 3.0) -> tuple[int, str, str]:
        calls.append(cmd)
        return await _fake_run_text(*cmd, timeout=timeout)

    try:
        system_api._run_text = counting_run_text
        system_api._bluetooth_status_cache = None
        status = await system_api.bluetooth_status()
        first_call_count = len(calls)
        cached_status = await system_api.bluetooth_status()
    finally:
        system_api._bluetooth_status_cache = None
        system_api._run_text = original

    assert len(calls) == first_call_count
    assert cached_status == status
    assert cached_status is not status
    assert cached_status["devices"] is not status["devices"]
    assert status["available"] is True
    assert status["bluetooth_service_active"] is True
    assert status["powered"] is True
    assert status["discoverable"] is False
    assert status["pairable"] is True
    assert status["paired_devices"] == ["AA:BB:CC:DD:EE:FF"]
    assert status["connected_devices"] == ["11:22:33:44:55:66"]
    assert status["devices"] == [
        {
            "mac": "AA:BB:CC:DD:EE:FF",
            "name": "Host One",
            "paired": True,
            "bonded": True,
            "trusted": True,
            "connected": False,
            "display_name": None,
            "display_name_source": None,
            "last_seen_name": None,
            "last_connected_at": None,
            "last_connected_source": None,
        },
        {
            "mac": "11:22:33:44:55:66",
            "name": "Host Two",
            "paired": False,
            "bonded": False,
            "trusted": False,
            "connected": True,
            "display_name": None,
            "display_name_source": None,
            "last_seen_name": None,
            "last_connected_at": None,
            "last_connected_source": None,
        },
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        hosts_path = Path(tmpdir) / "bluetooth_hosts.json"
        hosts_path.write_text(
            '{"version":1,"hosts":{"aa:bb:cc:dd:ee:ff":'
            '{"last_connected_at":"2026-05-28T12:34:56+09:00",'
            '"last_connected_source":"btd_notify_ready",'
            '"last_seen_name":"Desk phone",'
            '"display_name":"Work laptop"}}}',
            encoding="utf-8",
        )
        metadata = system_api._load_bluetooth_host_metadata(str(hosts_path))
    assert metadata["AA:BB:CC:DD:EE:FF"]["last_connected_source"] == "btd_notify_ready"
    assert metadata["AA:BB:CC:DD:EE:FF"]["display_name"] == "Work laptop"
    assert metadata["AA:BB:CC:DD:EE:FF"]["last_seen_name"] == "Desk phone"
    merged = system_api._merge_bluetooth_host_metadata(
        [{"mac": "AA:BB:CC:DD:EE:FF"}, {"mac": "00:00:00:00:00:00"}],
        metadata,
    )
    assert merged[0]["display_name"] == "Work laptop"
    assert merged[0]["display_name_source"] == "local_metadata"
    assert merged[0]["last_seen_name"] == "Desk phone"
    assert merged[0]["last_connected_at"] == "2026-05-28T12:34:56+09:00"
    assert merged[0]["last_connected_source"] == "btd_notify_ready"
    assert merged[1]["display_name"] is None
    assert merged[1]["display_name_source"] is None
    assert merged[1]["last_connected_at"] is None
    assert merged[1]["last_connected_source"] is None
    assert "btd" in system_api.process_statuses()
    assert "btd" in system_api.LOG_ALLOWED_SERVICES
    assert "hidd" in system_api.process_statuses()
    assert "hidd" in system_api.LOG_ALLOWED_SERVICES
    matched = system_api._match_process_statuses([
        "/usr/bin/python3 -m logicd.logicd",
        "/usr/bin/python3 /repo/daemon/http/httpd.py",
        "/repo/daemon/matrixd/matrixd /repo/config/default/matrixd.json",
        "/usr/bin/python3 -m ledd.ledd",
        "/usr/bin/python3 -m i2cd.i2cd",
        "/repo/bin/hidloom-hidd",
        "bash -lc systemctl is-active btd bluetooth",
    ])
    assert matched["logicd"] is True
    assert matched["httpd"] is True
    assert matched["matrixd"] is True
    assert matched["ledd"] is True
    assert matched["i2cd"] is True
    assert matched["hidd"] is True
    assert matched["btd"] is False
    assert matched["usbd"] is False

    false_positive_probe = system_api._match_process_statuses([
        "bash -lc systemctl status matrixd.service logicd-companion.service ledd.service usbd.service",
    ])
    assert false_positive_probe["matrixd"] is False
    assert false_positive_probe["logicd-companion"] is False
    assert false_positive_probe["ledd"] is False
    assert false_positive_probe["usbd"] is False

    matched = system_api._match_process_statuses(["/usr/bin/python3 -m btd.btd"])
    assert matched["btd"] is True
    assert system_api._parse_systemd_active_states(
        "Id=logicd.service\nActiveState=active\n\n"
        "Id=matrixd.service\nActiveState=inactive\n\n"
    ) == {"logicd.service": True, "matrixd.service": False}

    if hasattr(socket, "AF_UNIX"):
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "btd.sock")
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.bind(socket_path)
                btd = system_api.btd_status(socket_path)
            finally:
                sock.close()

            assert btd["socket"]["path"] == socket_path
            assert btd["socket"]["exists"] is True
            assert btd["socket"]["is_socket"] is True
            assert isinstance(btd["socket"]["mode"], str)
            assert btd["runtime"] is None

    missing_sock = os.path.join(tempfile.gettempdir(), "missing-btd.sock")
    missing = system_api.btd_status(missing_sock)
    assert missing["socket"]["exists"] is False
    assert missing["socket"]["is_socket"] is False
    system_api._btd_runtime_status_cache.clear()
    runtime = await system_api.query_btd_runtime_status(missing_sock, timeout=0.01)
    cached_runtime = await system_api.query_btd_runtime_status(missing_sock, timeout=0.01)
    assert runtime["available"] is False
    assert cached_runtime == runtime
    assert cached_runtime is not runtime

    parsed = system_api._parse_systemd_environment_show(
        "Environment=BTD_BACKEND=bluez BTD_GATT_SECURITY=encrypt "
        "'BTD_EVENTS_SOCK=/tmp/quoted btd.sock'\n"
    )
    assert parsed["BTD_BACKEND"] == "bluez"
    assert parsed["BTD_GATT_SECURITY"] == "encrypt"
    assert parsed["BTD_EVENTS_SOCK"] == "/tmp/quoted btd.sock"

    original = system_api._run_text
    try:
        system_api._run_text = _fake_run_text
        system_api._service_env_cache.clear()
        runtime_env = await logicd_runtime_environment()
        service_env = await system_api.service_environment("logicd")
        cached_env = await system_api.service_environment("logicd")
    finally:
        system_api._run_text = original
    assert service_env["LOGICD_OUTPUTS"] == "auto"
    assert service_env["BTD_EVENTS_SOCK"] == "/tmp/service-btd.sock"
    assert runtime_env["LOGICD_OUTPUTS"] == "debug"
    assert runtime_env["LOGICD_NATIVE_OUTPUTD_CTRL"] == "1"
    assert cached_env == service_env
    assert cached_env is not service_env

    fallback_calls: list[tuple[str, ...]] = []

    async def fallback_run_text(*cmd: str, timeout: float = 3.0) -> tuple[int, str, str]:
        fallback_calls.append(cmd)
        if cmd == ("systemctl", "is-active", "--quiet", "logicd-companion"):
            return 3, "", "inactive"
        if cmd == ("systemctl", "is-active", "--quiet", "logicd"):
            return 0, "", ""
        if cmd == ("systemctl", "show", "logicd", "-p", "Environment", "--no-pager"):
            return 0, "Environment=LOGICD_OUTPUTS=auto\n", ""
        raise AssertionError(f"unexpected fallback command: {cmd!r}")

    original = system_api._run_text
    try:
        system_api._run_text = fallback_run_text
        system_api._service_env_cache.clear()
        fallback_env = await logicd_runtime_environment()
    finally:
        system_api._service_env_cache.clear()
        system_api._run_text = original
    assert fallback_env == {"LOGICD_OUTPUTS": "auto"}
    assert fallback_calls == [
        ("systemctl", "is-active", "--quiet", "logicd-companion"),
        ("systemctl", "is-active", "--quiet", "logicd"),
        ("systemctl", "show", "logicd", "-p", "Environment", "--no-pager"),
    ]

    btd = system_api.btd_status(service_env={
        "BTD_BACKEND": "bluez",
        "BTD_GATT_ADAPTER": "bluez-dbus",
        "BTD_ADVERTISING_ADAPTER": "bluez-dbus",
        "BTD_ADVERTISING_MODE": "pairing",
        "BTD_ADVERTISING_MONITOR_INTERVAL": "1",
        "BTD_GATT_SECURITY": "encrypt",
        "BTD_STATUS_INTERVAL": "30",
        "BTD_DISCONNECT_MONITOR_INTERVAL": "2",
        "BTD_STUCK_RECONNECT_POLLS": "3",
        "BTD_STUCK_RECONNECT_COOLDOWN": "30",
    })
    assert btd["backend_env"] == "bluez"
    assert btd["gatt_adapter_env"] == "bluez-dbus"
    assert btd["advertising_adapter_env"] == "bluez-dbus"
    assert btd["advertising_mode_env"] == "pairing"
    assert btd["advertising_monitor_interval_env"] == "1"
    assert btd["gatt_security_env"] == "encrypt"
    assert btd["status_interval_env"] == "30"
    assert btd["disconnect_monitor_interval_env"] == "2"
    assert btd["stuck_reconnect_polls_env"] == "3"
    assert btd["stuck_reconnect_cooldown_env"] == "30"
    enriched = system_api.btd_status(service_env={}, runtime_status={"available": True, "host_connected": True})
    assert enriched["runtime"]["host_connected"] is True

    if hasattr(socket, "AF_UNIX"):
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "usbd_hid_reports.sock")
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            try:
                sock.bind(socket_path)
                usbd = usbd_status(
                    usbd_env={
                        "USBD_HID_REPORT_SOCKET_ENABLED": "1",
                        "USBD_HID_REPORT_SOCKET": socket_path,
                        "USBD_HID_REPORT_LOG": "1",
                    },
                    logicd_env={
                        "LOGICD_USBD_HID_REPORT_BROKER": "1",
                        "LOGICD_USBD_HID_REPORT_SOCKET": socket_path,
                        "LOGICD_HID_REPORT_LOG": "1",
                    },
                )
            finally:
                sock.close()

            assert usbd["hid_report_socket"]["path"] == socket_path
            assert usbd["hid_report_socket"]["exists"] is True
            assert usbd["hid_report_socket"]["is_socket"] is True
            assert usbd["hid_report_socket_enabled_env"] == "1"
            assert usbd["logicd_broker_enabled_env"] == "1"
            assert usbd["hid_report_log_env"] == "1"
            assert usbd["logicd_hid_report_log_env"] == "1"
            assert usbd["broker_ready"] is True
            assert usbd["owner"] in {"hidloom-hidd", "usbd", "unknown"}

            hidd_status_path = os.path.join(tmpdir, "hidd-status.json")
            Path(hidd_status_path).write_text(
                json.dumps({"process": True}),
                encoding="utf-8",
            )
            native_route = hidd_status(
                hidd_env={"USBD_HID_REPORT_SOCKET": socket_path},
                logicd_env={
                    "LOGICD_USBD_HID_REPORT_BROKER": "0",
                    "LOGICD_NATIVE_OUTPUTD_CTRL": "1",
                },
                hidd_status_path=hidd_status_path,
            )
            assert native_route["owner"] == "hidloom-hidd"
            assert native_route["logicd_broker_enabled_env"] == "0"
            assert native_route["logicd_native_outputd_ctrl_env"] == "1"
            assert native_route["broker_ready"] is True

    not_ready = usbd_status(
        usbd_env={"USBD_HID_REPORT_SOCKET_ENABLED": "1"},
        logicd_env={
            "LOGICD_USBD_HID_REPORT_BROKER": "0",
            "LOGICD_NATIVE_OUTPUTD_CTRL": "0",
        },
    )
    assert not_ready["broker_ready"] is False
    native = hidd_status(
        hidd_env={"USBD_HID_REPORT_SOCKET": "/tmp/native-hidd.sock"},
        logicd_env={"LOGICD_USBD_HID_REPORT_BROKER": "1"},
        hidd_status_path="/tmp/missing-hidd-status.json",
    )
    assert native["hid_report_socket"]["path"] == "/tmp/native-hidd.sock"
    assert native["status"]["available"] is False

    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "config.json"
        config_path.write_text(
            json.dumps({
                "settings": {
                    "unicode": {"mode": "windows_ime_hex_f5", "host_profile": "win11-ime"},
                    "text_send_runner": {
                        "connected": True,
                        "method": "logicd_keyboard_tap_runner",
                        "target": "active_output_keyboard",
                        "cancel_path": "text_send_runtime_state",
                        "zero_report_on_cancel": True,
                        "timeout_sec": 2.0,
                    },
                    "send_strings": {"kana_a": {"text": "あ", "enabled": True}},
                }
            }),
            encoding="utf-8",
        )
        text_send = status_api.text_send_status(config_path)
    assert text_send["schema"] == "text_send.status.v1"
    assert text_send["safety_route"] == "/api/interaction/text-send-safety"
    assert text_send["plan_route"] == "/api/interaction/text-send-safety/plan"
    assert text_send["unicode_mode"] == "windows_ime_hex_f5"
    assert text_send["host_profile_explicit"] is True
    assert text_send["runner_ready"] is True
    assert text_send["runner_connected"] is True
    assert text_send["real_send_allowed"] is True
    assert text_send["send_string_actions_executable"] is True
    assert text_send["send_string_entry_count"] == 1
    assert text_send["send_string_error_count"] == 0
    assert text_send["blocking_reasons"] == []

    unavailable = status_api.text_send_status(None)
    assert unavailable["available"] is False
    assert unavailable["reason"] == "config_json_not_available"


async def _assert_bluetooth_inactive_skips_bluetoothctl() -> None:
    original = system_api._run_text
    calls: list[tuple[str, ...]] = []

    async def inactive_run_text(*cmd: str, timeout: float = 3.0) -> tuple[int, str, str]:
        calls.append(cmd)
        if cmd == ("systemctl", "is-active", "bluetooth"):
            return 3, "inactive\n", ""
        raise AssertionError(f"bluetoothctl should not run while service is inactive: {cmd!r}")

    try:
        system_api._run_text = inactive_run_text
        system_api._bluetooth_status_cache = None
        status = await system_api.bluetooth_status()
    finally:
        system_api._bluetooth_status_cache = None
        system_api._run_text = original

    assert calls == [("systemctl", "is-active", "bluetooth")]
    assert status["available"] is False
    assert status["bluetooth_service_active"] is False
    assert status["paired_devices"] == []
    assert status["connected_devices"] == []
    assert status["error"] == "inactive"


def main() -> None:
    old_env = dict(os.environ)
    try:
        os.environ.clear()
        os.environ.update({
            "LOGICD_OUTPUTS": "bt,debug",
            "BTD_EVENTS_SOCK": "/tmp/test_btd.sock",
            "SPID_ENABLED": "true",
            "SPID_BACKEND": "mock",
            "LOGICD_SPID_MODE": "direction",
            "SPID_EVENTS_SOCK": "/tmp/test_spi_events.sock",
            "SPID_SPI_BUS": "0",
            "SPID_SPI_DEVICE": "1",
            "SPID_SPI_MODE": "3",
            "SPID_SPI_SPEED_HZ": "2000000",
            "SPID_PAW3805EK_CPI": "200",
            "SPID_PAW3805EK_SCALE": "1.25",
            "LEDD_DIRECT_FRAME_SOCK": "/tmp/test_ledd_direct.sock",
        })

        output = output_status()
        assert output["logicd_outputs_env"] == "bt,debug"
        assert output["configured_outputs"] == ["bt", "debug"]
        assert output["bt_enabled_by_env"] is True
        assert output["debug_enabled_by_env"] is True
        assert output["btd_events_sock_env"] == "/tmp/test_btd.sock"
        assert output["runtime_mode_label"] == ""
        assert output["output_target_label"] == ""
        assert output["display_label"] == ""
        assert output_display_label("bt", "auto") == "AUTO BT"
        assert output_display_label("gadget", "auto") == "AUTO USB"
        assert output_display_label("uinput", "uinput") == "Pi"

        output = output_status(runtime_mode="bt", output_target="auto")
        assert output["runtime_mode_label"] == "BT"
        assert output["output_target_label"] == "auto"
        assert output["display_label"] == "AUTO BT"

        with tempfile.TemporaryDirectory() as tmpdir:
            outputd_path = Path(tmpdir) / "outputd-status.json"
            outputd_path.write_text(json.dumps({
                "schema": "hidloom.outputd.status.v1",
                "process": True,
                "target": "auto",
            }), encoding="utf-8")
            native_output = outputd_status(str(outputd_path))
            assert native_output["available"] is True
            assert resolve_output_state("uinput", "auto", native_output) == ("gadget", "auto")

            outputd_path.write_text(json.dumps({
                "schema": "hidloom.outputd.status.v1",
                "process": True,
                "target": "uinput",
            }), encoding="utf-8")
            native_output = outputd_status(str(outputd_path))
            assert resolve_output_state("gadget", "auto", native_output) == ("uinput", "uinput")

            outputd_path.write_text(json.dumps({
                "schema": "wrong.schema",
                "target": "auto",
            }), encoding="utf-8")
            native_output = outputd_status(str(outputd_path))
            assert native_output["available"] is False
            assert resolve_output_state("uinput", "auto", native_output) == ("uinput", "auto")

            outputd_path.write_text(json.dumps({
                "schema": "hidloom.outputd.status.v1",
                "process": False,
                "target": "auto",
            }), encoding="utf-8")
            native_output = outputd_status(str(outputd_path))
            assert native_output["available"] is False
            assert resolve_output_state("uinput", "auto", native_output) == ("uinput", "auto")

        interaction = status_api._normalized_interaction_status({
            "result": "ok",
            "schema": "interaction.runtime_status.v1",
            "source": "logicd.interactions",
            "save_payload_includes_runtime_state": False,
            "caps_word": {"enabled": True, "active": True},
            "repeat_key": {
                "enabled": True,
                "history_available": True,
                "alternate_available": False,
                "alternate_pair_count": 9,
            },
            "key_lock": {
                "keys": [
                    {"action": "KC_LSFT", "kind": "modifier", "source": "KEY_LOCK"},
                    {"action": "KC_BTN1", "kind": "mouse_button", "source": "DRAG_LOCK"},
                ]
            },
            "one_shot_layer": {"active_count": 1, "source": "LayerManager.active_snapshot.oneshot"},
        })
        assert interaction["available"] is True
        assert interaction["caps_word"] == {"enabled": True, "active": True}
        assert interaction["repeat_key"]["history_available"] is True
        assert interaction["repeat_key"]["alternate_pair_count"] == 9
        assert interaction["key_lock"]["active_count"] == 2
        assert interaction["one_shot_layer"]["active_count"] == 1
        assert "KC_LEFT" not in json.dumps(interaction), "status payload must not leak repeat history action"
        missing_interaction = status_api._normalized_interaction_status(None)
        assert missing_interaction["available"] is False
        assert missing_interaction["caps_word"]["active"] is None
        assert missing_interaction["one_shot_layer"]["active_count"] == 0

        spid = spid_status()
        assert spid["enabled_env"] == "true"
        assert spid["backend_env"] == "mock"
        assert spid["logicd_mode_env"] == "direction"
        assert spid["events_socket"]["path"] == "/tmp/test_spi_events.sock"
        assert spid["events_socket"]["exists"] is False
        assert spid["spi_device_env"] == "1"
        assert spid["paw3805ek_scale_env"] == "1.25"

        missing_direct = ledd_direct_frame_status(status_path="/tmp/hidloom-missing-direct-frame-status.json")
        assert missing_direct["metrics_source"] == "missing"
        assert missing_direct["accepted_frames"] is None
        assert missing_direct["direct_frame_active"] is None
        assert "metrics_error" not in missing_direct

        with tempfile.TemporaryDirectory() as td:
            status_path = Path(td) / "direct.json"
            status_path.write_text(
                '{"available":true,"accepted_frames":3,"rejected_frames":1,'
                '"bytes_received":123,"last_frame_id":7,"last_error":"bad",'
                '"producer_connects":2,"producer_disconnects":1,'
                '"direct_frame_active":true,"applied_frames":2,"ignored_frames":1,'
                '"last_applied_frame_id":7,"updated_at":42.0}',
                encoding="utf-8",
            )
            os.environ["LEDD_DIRECT_FRAME_STATUS"] = str(status_path)
            direct = ledd_direct_frame_status()
        assert direct["socket"]["path"] == "/tmp/test_ledd_direct.sock"
        assert direct["socket"]["exists"] is False
        assert direct["metrics_source"] == "json_file"
        assert direct["accepted_frames"] == 3
        assert direct["rejected_frames"] == 1
        assert direct["bytes_received"] == 123
        assert direct["last_frame_id"] == 7
        assert direct["last_error"] == "bad"
        assert direct["direct_frame_active"] is True
        assert direct["applied_frames"] == 2
        assert direct["ignored_frames"] == 1
        assert direct["last_applied_frame_id"] == 7

        with tempfile.TemporaryDirectory() as td:
            missing_board = board_profile_status(
                str(Path(td) / "missing-board.json"),
                str(Path(td) / "missing-touch-panel.json"),
                str(Path(td) / "missing-device-profile.json"),
            )
            assert missing_board["board_version"] == "ver1.0"
            assert missing_board["source"] == "fallback"
            assert missing_board["marker_exists"] is False
            assert missing_board["display_label"] == "ver1.0"
            board_marker = Path(td) / "board_profile.json"
            board_marker.write_text(
                json.dumps({
                    "board_version": "ver0.1",
                    "prototype": True,
                    "device_name": "<keyboard-host>",
                }),
                encoding="utf-8",
            )
            board = board_profile_status(
                str(board_marker),
                str(Path(td) / "missing-touch-panel.json"),
                str(Path(td) / "missing-device-profile.json"),
            )
        assert board["board_version"] == "ver0.1"
        assert board["source"] == "marker"
        assert board["prototype"] is True
        assert board["device_name"] == "<keyboard-host>"
        assert board["display_label"] == "ver0.1 prototype"
        with tempfile.TemporaryDirectory() as td:
            touch_marker = Path(td) / "touch_panel_profile.json"
            touch_marker.write_text(
                json.dumps({
                    "profile": "waveshare-8.8",
                    "reason": "auto:480x1920:test",
                    "sizes": [{"width": 480, "height": 1920, "source": "test"}],
                }),
                encoding="utf-8",
            )
            touch_board = board_profile_status(
                str(Path(td) / "missing-board.json"),
                str(touch_marker),
            )
        assert touch_board["board_version"] == "ver1.0"
        assert touch_board["device_name"] == "<keyboard-host>"
        assert touch_board["runtime_profile"]["kind"] == "touch-panel"
        assert touch_board["runtime_profile"]["profile"] == "waveshare-8.8"
        assert touch_board["display_label"] == "<keyboard-host> touch-panel (waveshare-8.8)"
        with tempfile.TemporaryDirectory() as td:
            device_marker = Path(td) / "device_profile.json"
            device_marker.write_text(
                json.dumps({
                    "schema": "cqa02303v5.device-profile.v1",
                    "id": "touch-waveshare-8.8",
                    "kind": "touch-panel",
                    "selected_at": "2026-07-05T00:00:00Z",
                    "selected_by": "script/apply_device_profile.py",
                }),
                encoding="utf-8",
            )
            touch_board = board_profile_status(
                str(Path(td) / "missing-board.json"),
                str(Path(td) / "missing-touch-panel.json"),
                str(device_marker),
            )
        assert touch_board["board_version"] == "ver1.0"
        assert touch_board["device_name"] == "<keyboard-host>"
        assert touch_board["runtime_profile"]["kind"] == "touch-panel"
        assert touch_board["runtime_profile"]["source"] == "device-profile"
        assert touch_board["runtime_profile"]["id"] == "touch-waveshare-8.8"
        assert touch_board["runtime_profile"]["profile"] == "waveshare-8.8"
        assert touch_board["display_label"] == "<keyboard-host> touch-panel (waveshare-8.8)"
    finally:
        os.environ.clear()
        os.environ.update(old_env)

    status_js = STATUS_JS.read_text(encoding="utf-8")
    status_css = STATUS_CSS.read_text(encoding="utf-8")
    interaction_css = INTERACTION_CSS.read_text(encoding="utf-8")
    assert "function outputModeDisplayLabel(mode)" in status_js
    assert 'gadget: "USB"' in status_js
    assert 'bt: "BT"' in status_js
    assert 'uinput: "Pi"' in status_js
    assert "data.output?.display_label" in status_js
    assert "`AUTO ${modeLabel}`" in status_js
    assert "let _statusFetchBusy = false" in status_js
    assert "if (_statusFetchBusy) return" in status_js
    assert "function ensureWifiStatusRow()" in status_js
    assert 'status.id = "stat-wifi"' in status_js
    assert "function updateWifiStatusUI(wifi)" in status_js
    assert "updateWifiStatusUI(data.wifi || {})" in status_js
    assert "function ensureBoardProfileStatusRow()" in status_js
    assert 'status.id = "stat-board-profile"' in status_js
    assert "function updateBoardProfileStatusUI(board)" in status_js
    assert "updateBoardProfileStatusUI(data.board_profile || {})" in status_js
    assert "function ensureInteractionStatusRow()" in status_js
    assert 'status.id = "stat-interaction"' in status_js
    assert "function updateInteractionStatusUI(interaction)" in status_js
    assert "updateInteractionStatusUI(data.interaction || {})" in status_js
    assert "function ensureTextSendStatusRow()" in status_js
    assert 'status.id = "stat-text-send"' in status_js
    assert "function updateTextSendStatusUI(textSend)" in status_js
    assert "updateTextSendStatusUI(data.text_send || {})" in status_js
    assert "Text Send: real_send_allowed=" in status_js
    assert "Blocked ${mode}" in status_js
    assert "caps_word.active" in status_js
    assert "repeat.history_available" in status_js
    assert "one_shot_layer.active_count" in status_js
    assert "OSL ${oneShotCount}" in status_js
    assert "key_lock.active_count" in status_js
    assert "Board profile: version=" in status_js
    assert "board.display_label" in status_js
    assert "touch_profile=" in status_js
    assert "wifi.persistent_power_off" in status_js
    assert "wifi.recovery_first" in status_js
    assert "function injectBluetoothHostPanelStyles()" not in status_js
    assert "document.createElement(\"style\")" not in status_js
    assert "function ensureBluetoothHostPanel()" in status_js
    assert 'panel.id = "bt-host-panel"' in status_js
    assert 'id="bt-host-list"' in status_js
    assert "function updateBluetoothHostPanel(bt)" in status_js
    assert "bluetoothHostDisplayName" in status_js
    assert "bluetoothHostStateText" in status_js
    assert "bluetoothHostClassName" in status_js
    assert "bluetoothHostLastConnectedText" in status_js
    assert "Last connected: -" in status_js
    assert "updateBluetoothHostPanel(bt)" in status_js
    assert "device?.trusted" in status_js
    assert "device?.bonded" in status_js
    assert "device?.last_connected_at" in status_js
    assert '@import url("/static/status_panel.css")' in interaction_css
    assert ".bt-host-panel" in status_css
    assert ".bt-host.connected" in status_css
    assert ".bt-host.paired" in status_css
    assert ".bt-host.error" in status_css
    assert ".bt-host-last-connected" in status_css

    httpd_py = (ROOT / "daemon" / "http" / "httpd.py").read_text(encoding="utf-8")
    system_api_py = (ROOT / "daemon" / "http" / "system_api.py").read_text(encoding="utf-8")
    assert "class _HttpAccessLogger" in httpd_py
    assert '_QUIET_POLLING_PATHS = {"/api/status", "/api/keymap/active", "/api/matrix"}' in httpd_py
    assert "request.path in _QUIET_POLLING_PATHS and response.status < 400" in httpd_py
    assert "async def _query_logicd_active_layers()" in httpd_py
    assert 'data = await _send_ctrl_command({"t": "ACTIVE"})' in httpd_py
    assert 'data = await _send_ctrl_command({"t": "INTERACTION_STATUS"})' in httpd_py
    assert "logicd_data = await _query_logicd_active_layers()" in httpd_py
    assert "access_log_class=_HttpAccessLogger" in httpd_py
    assert "HTTPD_SHUTDOWN_TIMEOUT_SECONDS" in httpd_py
    assert "HTTPD_WS_CLOSE_TIMEOUT_SECONDS" in httpd_py
    assert "app.on_shutdown.append(_close_ws_clients_on_shutdown)" in httpd_py
    assert "await asyncio.wait_for(" in httpd_py
    assert "shutdown_timeout=HTTPD_SHUTDOWN_TIMEOUT_SECONDS" in httpd_py
    assert "handler_cancellation=True" in httpd_py
    assert "from wifi_status import wifi_status" in httpd_py
    assert "logicd_data, interaction_status, logicd_env, btd_env, usbd_env, hidd_env, bt, wifi = await asyncio.gather" in (ROOT / "daemon" / "http" / "status_api.py").read_text(encoding="utf-8")
    assert "logicd_runtime_environment()," in (ROOT / "daemon" / "http" / "status_api.py").read_text(encoding="utf-8")
    assert '"wifi": wifi,' in httpd_py
    assert '"interaction": _normalized_interaction_status(interaction_status),' in (ROOT / "daemon" / "http" / "status_api.py").read_text(encoding="utf-8")
    status_api_source = (ROOT / "daemon" / "http" / "status_api.py").read_text(encoding="utf-8")
    assert '"hidd": hidd_status(hidd_env=hidd_env, logicd_env=logicd_env),' in status_api_source
    assert '"hid_broker": hidd_status(hidd_env=hidd_env, logicd_env=logicd_env),' in status_api_source
    assert '"usbd": usbd_status(usbd_env=usbd_env, hidd_env=hidd_env, logicd_env=logicd_env),' in status_api_source
    assert '"text_send": text_send_status(config_json),' in (ROOT / "daemon" / "http" / "status_api.py").read_text(encoding="utf-8")
    assert "config_json=CONFIG_JSON" in httpd_py
    assert "def _proc_cmdlines()" in system_api_py
    assert "def _systemd_active_statuses()" in system_api_py
    assert "return {name: systemd.get(name, fallback[name])" in system_api_py
    assert "_SERVICE_ENV_CACHE_TTL = 30.0" in system_api_py
    assert "_BLUETOOTH_STATUS_CACHE_TTL = 5.0" in system_api_py
    assert "_BTD_RUNTIME_STATUS_CACHE_TTL = 5.0" in system_api_py
    assert 'DEFAULT_BLUETOOTH_HOSTS_FILE = "/mnt/p3/bluetooth_hosts.json"' in system_api_py
    assert 'DEFAULT_BOARD_PROFILE_FILE = "/mnt/p3/board_profile.json"' in system_api_py
    assert 'DEFAULT_BOARD_VERSION = "ver1.0"' in system_api_py
    assert "def board_profile_status" in system_api_py
    assert "_service_env_cache" in system_api_py
    assert "_bluetooth_status_cache" in system_api_py
    assert "proc.kill()" in system_api_py
    assert "bluetooth service inactive" in system_api_py
    assert "_btd_runtime_status_cache" in system_api_py
    assert "def usbd_status" in system_api_py
    assert "def hidd_status" in system_api_py
    assert 'DEFAULT_USBD_HID_REPORT_SOCKET = "/tmp/usbd_hid_reports.sock"' in system_api_py
    assert 'DEFAULT_HIDD_STATUS_PATH = "/run/hidloom/hidd-status.json"' in system_api_py
    assert 'DEFAULT_OUTPUTD_STATUS_PATH = "/run/hidloom/outputd-status.json"' in system_api_py
    assert '"outputd": native_output,' in status_api_source
    assert '"hidd"' in (ROOT / "daemon" / "http" / "system_logs.py").read_text(encoding="utf-8")
    assert '"hidloom-hidd.service"' in (ROOT / "daemon" / "http" / "system_logs.py").read_text(encoding="utf-8")
    assert '"devices": devices' in system_api_py
    assert "_bluetooth_device_detail" in system_api_py
    assert "_load_bluetooth_host_metadata" in system_api_py
    assert "_merge_bluetooth_host_metadata" in system_api_py
    assert "Paired" in system_api_py
    assert "Bonded" in system_api_py
    assert "Trusted" in system_api_py
    assert "Connected" in system_api_py
    status_api_py = (ROOT / "daemon" / "http" / "status_api.py").read_text(encoding="utf-8")
    assert "board_profile_status" in status_api_py
    assert '"board_profile": board_profile_status(),' in status_api_py

    env = {
        **os.environ,
        "LOGICD_OUTPUTS": "gadget,uinput,bt,debug",
        "LOGICD_AUTO_BT_FALLBACK": "1",
        "LOGICD_BT_DISCONNECT_ON_OUTPUT_DISABLE": "1",
        "BTD_EVENTS_SOCK": "/tmp/example-btd.sock",
    }
    with patch.dict(os.environ, env, clear=True):
        output = system_api.output_status(runtime_mode="bt", output_target="auto")
    assert output["logicd_outputs_env"] == "gadget,uinput,bt,debug"
    assert output["configured_outputs"] == ["gadget", "uinput", "bt", "debug"]
    assert output["runtime_mode"] == "bt"
    assert output["output_target"] == "auto"
    assert output["bt_enabled_by_env"] is True
    assert output["auto_bt_fallback_env"] == "1"
    assert output["bt_disconnect_on_output_disable_env"] == "1"
    assert output["btd_events_sock_env"] == "/tmp/example-btd.sock"

    output = system_api.output_status({"LOGICD_OUTPUTS": "auto", "BTD_EVENTS_SOCK": "/tmp/service-btd.sock"})
    assert output["logicd_outputs_env"] == "auto"
    assert output["configured_outputs"] == ["auto"]
    assert output["bt_enabled_by_env"] is False
    assert output["btd_events_sock_env"] == "/tmp/service-btd.sock"

    asyncio.run(_assert_bluetooth_and_btd_status_helpers())
    asyncio.run(_assert_bluetooth_inactive_skips_bluetoothctl())

    print("ok: HTTP system status helpers")


if __name__ == "__main__":
    main()
