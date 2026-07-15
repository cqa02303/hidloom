"""
logicd – Keyboard logic daemon for HIDloom.

matrixd/httpd feed matrix events, ctrl_events handles low-rate control, and
spid may request a high-rate spi_events connection.  logicd owns keymap/layer /
interaction handling and output routing.
"""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
import json
import logging
import os
import signal
import sys
import time
from typing import Any, Optional

from .env import env_float, env_int

log = logging.getLogger(__name__)
_BOOT_START_MONOTONIC = time.monotonic()

DEFAULT_SCRIPT_DIR = "/mnt/p3/script"
FALLBACK_SCRIPT_DIR: str | None = None
DEFAULT_SPID_SOCKET = "/tmp/spi_events.sock"

_LED_SAVE_DEBOUNCE_SEC = env_float("LOGICD_LED_SAVE_DEBOUNCE_SEC", 20.0, min_value=0.0)
_LIGHTING_STEP = env_int("LOGICD_LIGHTING_KEY_STEP", 16, min_value=1, max_value=255)
_SPID_MOTION_OUTPUT_HZ = env_float("LOGICD_SPID_MOTION_OUTPUT_HZ", 125.0, min_value=1.0)
_SPID_MOTION_MAX_BUFFERED = env_int("LOGICD_SPID_MOTION_MAX_BUFFERED", 64, min_value=1, max_value=4096)
MATRIX_ROWS = env_int("LOGICD_MATRIX_ROWS", 10, min_value=1, max_value=255)
MATRIX_COLS = env_int("LOGICD_MATRIX_COLS", 10, min_value=1, max_value=255)
CORE_KEY_EVENT_CTRL_SOCKET = os.environ.get("LOGICD_CORE_KEY_EVENT_CTRL_SOCKET", "")

_runtime_impl: Any | None = None
_notifier: Any | None = None
_spid_motion_task: Optional[asyncio.Task] = None
_spid_motion_socket: str = DEFAULT_SPID_SOCKET
_spid_runtime_settings: Any | None = None
_spid_direction_mapper: Any | None = None
_outputd_mouse_write_fn: Any | None = None
_vialrgb_effect_sequence: list[int] | None = None
_vialrgb_allowed_modes: set[int] | None = None
_vialrgb_effects: Any | None = None

_HELP = """usage: python3 -m logicd.logicd [CONFIG_JSON]

Keyboard logic daemon.

Arguments:
  CONFIG_JSON   optional path to the logicd JSON configuration

Options:
  -h, --help    show this help and exit

Common environment:
  LOG_LEVEL
  LOGICD_LED_STATE_PATH
  LOGICD_CORE_KEY_EVENT_CTRL_SOCKET
  LOGICD_MATRIX_ROWS
  LOGICD_MATRIX_COLS
"""


class _RuntimeProxy:
    def __getattr__(self, name: str) -> Any:
        return getattr(_require_runtime(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(_require_runtime(), name, value)


_runtime = _RuntimeProxy()


def _init_runtime() -> None:
    global _runtime_impl, _notifier, _spid_runtime_settings
    if _runtime_impl is not None:
        return
    started = time.monotonic()
    from .runtime_notifications import LogicdNotifier
    from .spid_runtime import SpidRuntimeSettings
    from .state import LogicdRuntime

    _runtime_impl = LogicdRuntime(
        led_state_path=os.environ.get("LOGICD_LED_STATE_PATH", "/mnt/p3/led_state.json"),
        led_last_nonzero_mode=env_int("LOGICD_DEFAULT_LED_MODE", 40, min_value=0, max_value=65535),
    )
    _notifier = LogicdNotifier(_runtime_impl)
    _spid_runtime_settings = SpidRuntimeSettings()
    log.info(
        "logicd boot marker: runtime initialized duration=%.3fs elapsed=%.3fs",
        time.monotonic() - started,
        time.monotonic() - _BOOT_START_MONOTONIC,
    )


def _require_runtime() -> Any:
    if _runtime_impl is None:
        _init_runtime()
    return _runtime_impl


def _require_notifier() -> Any:
    if _notifier is None:
        raise RuntimeError("logicd notifier is not initialized")
    return _notifier


def _vialrgb_tables() -> tuple[list[int], set[int], Any]:
    global _vialrgb_effect_sequence, _vialrgb_allowed_modes, _vialrgb_effects
    if _vialrgb_effect_sequence is None or _vialrgb_allowed_modes is None or _vialrgb_effects is None:
        from vialrgb_effects import VIALRGB_ALLOWED_MODES, VIALRGB_EFFECT_SEQUENCE, VIALRGB_EFFECTS

        _vialrgb_effect_sequence = list(VIALRGB_EFFECT_SEQUENCE)
        _vialrgb_allowed_modes = set(VIALRGB_ALLOWED_MODES)
        _vialrgb_effects = VIALRGB_EFFECTS
    return _vialrgb_effect_sequence, _vialrgb_allowed_modes, _vialrgb_effects


class _LazySessiondPtyMirrorClient:
    def __init__(self, socket_path: str, **kwargs: Any) -> None:
        self.socket_path = socket_path
        self.kwargs = kwargs
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            from .sessiond_client import SessiondPtyMirrorClient

            self._client = SessiondPtyMirrorClient(self.socket_path, **self.kwargs)
        return self._client

    @property
    def host_profile(self) -> str:
        return str(getattr(self._get_client(), "host_profile", ""))

    def build_text_plans_for_stream(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return self._get_client().build_text_plans_for_stream(*args, **kwargs)

    async def start(self, **kwargs: Any) -> dict[str, Any]:
        return await self._get_client().start(**kwargs)

    async def send_key_action(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await self._get_client().send_key_action(*args, **kwargs)

    async def poll_output(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await self._get_client().poll_output(*args, **kwargs)

    async def watch_output(self, *args: Any, **kwargs: Any) -> None:
        await self._get_client().watch_output(*args, **kwargs)

    async def stop(self, **kwargs: Any) -> dict[str, Any]:
        return await self._get_client().stop(**kwargs)


def _matrix_in_range(row: int, col: int) -> bool:
    return 0 <= row < MATRIX_ROWS and 0 <= col < MATRIX_COLS


def _fallback_script_dir() -> str:
    if FALLBACK_SCRIPT_DIR:
        return FALLBACK_SCRIPT_DIR
    from hidloom_paths import default_config_dir

    return str(default_config_dir() / "script")


def _socket_from_settings(settings: dict, key: str, default: str, env_name: str) -> str | None:
    raw = os.environ.get(env_name)
    if raw is None:
        raw = settings.get(key, default)
    value = str(raw).strip()
    if value.lower() in {"", "0", "false", "no", "none", "off", "disabled"}:
        return None
    return value


def _apply_config(cfg: dict) -> None:
    global _spid_runtime_settings, _spid_direction_mapper
    from hidloom_paths import default_config_dir
    from .config_runtime import apply_runtime_config
    from .spid_runtime import spid_settings_from_config

    runtime = _require_runtime()
    apply_runtime_config(
        cfg,
        runtime,
        default_script_dir=DEFAULT_SCRIPT_DIR,
        fallback_script_dir=_fallback_script_dir(),
        matrix_in_range=_matrix_in_range,
        push_ledd_mode=_push_ledd_mode,
        push_i2cd_mode=_push_i2cd_mode,
        broadcast_key_event=_broadcast_key_event,
        push_i2cd_script_exit=_push_i2cd_script_exit,
    )
    _spid_runtime_settings = spid_settings_from_config(cfg)
    if _spid_runtime_settings.binding is not None:
        from .spid_direction import SpidDirectionMapper

        _spid_direction_mapper = SpidDirectionMapper(_spid_runtime_settings.binding)
    else:
        _spid_direction_mapper = None
    log.info("spid runtime mode=%s", _spid_runtime_settings.mode)
    sessiond_socket = os.environ.get("SESSIOND_SOCKET") or cfg.get("settings", {}).get(
        "sessiond_socket",
        "/tmp/sessiond.sock",
    )
    settings = cfg.get("settings", {})
    sessiond_auto_start = str(
        os.environ.get("LOGICD_SESSIOND_AUTO_START", settings.get("sessiond_auto_start", "1"))
    ).strip().lower() not in {"0", "false", "no", "off"}
    sessiond_idle_exit_sec = env_float(
        "LOGICD_SESSIOND_IDLE_EXIT_SEC",
        float(settings.get("sessiond_idle_exit_sec", 10.0)),
        min_value=0.0,
    )
    sessiond_log_path = os.environ.get("SESSIOND_LOG") or str(settings.get("sessiond_log_path", "/tmp/sessiond.log"))
    sessiond_user = os.environ.get("SESSIOND_USER") or settings.get("sessiond_user")
    pty_terminal_host_profile = (
        os.environ.get("PTY_TERMINAL_HOST_PROFILE")
        or os.environ.get("LOGICD_PTY_TERMINAL_HOST_PROFILE")
        or settings.get("pty_terminal_host_profile")
    )
    runtime.pty_mirror.bind_client(
        _LazySessiondPtyMirrorClient(
            str(sessiond_socket),
            host_profile=pty_terminal_host_profile,
            auto_start=sessiond_auto_start,
            repo_root=(
                os.environ.get("HIDLOOM_REPO_ROOT")
                or str(default_config_dir().parents[1])
            ),
            idle_exit_sec=sessiond_idle_exit_sec,
            log_path=sessiond_log_path,
            sessiond_user=str(sessiond_user) if sessiond_user else None,
        )
    )


async def _usb_monitor_loop() -> None:
    from .output import usb_monitor_loop

    runtime = _require_runtime()
    await usb_monitor_loop(lambda: runtime.macros._write)


def _push_ledd_status() -> None:
    _require_notifier().push_ledd_status()


def _push_ledd_key_event(row: int, col: int, is_press: bool) -> None:
    _require_notifier().push_ledd_key_event(row, col, is_press)


def _record_observed_matrix_event(row: int, col: int, is_press: bool) -> None:
    key = (row, col)
    observed = _require_runtime().observed_pressed_matrix
    if is_press:
        observed.add(key)
    else:
        observed.discard(key)


def _matrix_status_pressed() -> set[tuple[int, int]]:
    runtime = _require_runtime()
    return set(runtime.pressed_matrix) | set(runtime.observed_pressed_matrix)


def _push_ledd_morse_feedback(event: dict) -> None:
    _require_notifier().push_ledd_morse_feedback(event)


def _push_ledd_anim(anim_id: int) -> None:
    _require_notifier().push_ledd_anim(anim_id)


def _push_ledd_overlay_state(state: str, enabled: bool) -> None:
    _require_notifier().push_ledd_overlay_state(state, enabled)


def _push_ledd_semantic_reload() -> None:
    _require_notifier().push_ledd_semantic_reload()


def _push_ledd_semantic_keymap() -> None:
    _require_notifier().push_ledd_semantic_keymap()


def _push_ledd_semantic_roles() -> None:
    _require_notifier().push_ledd_semantic_roles()


def _apply_host_led_report(report: int) -> dict[str, bool]:
    from .host_led_output import apply_host_led_report

    runtime = _require_runtime()
    # Re-send explicit "off" states on report=0 so ledd can recover if it
    # missed an earlier overlay clear or restarted with a stale visual state.
    changed = apply_host_led_report(
        report,
        runtime.led_overlay_states,
        runtime.host_led_output,
        _push_ledd_overlay_state,
        force_sync=(int(report) & 0xFF) == 0,
    )
    if changed:
        log.info("host LED output report=0x%02X changed=%s", report & 0xFF, changed)
    return changed


def _push_ledd_vialrgb() -> None:
    _require_notifier().push_ledd_vialrgb()


def _normalize_led_state(raw: dict) -> dict[str, int]:
    from .lighting import normalize_led_state as lighting_normalize_led_state

    return lighting_normalize_led_state(raw)


def _remember_nonzero_led_mode() -> None:
    from .lighting import remember_nonzero_led_mode as lighting_remember_nonzero_led_mode

    runtime = _require_runtime()
    sequence, _, _ = _vialrgb_tables()
    runtime.led_last_nonzero_mode = lighting_remember_nonzero_led_mode(
        runtime.led_state,
        sequence,
        runtime.led_last_nonzero_mode,
    )


def _normalize_vialrgb_mode(mode: int) -> int:
    from .lighting import normalize_vialrgb_mode as lighting_normalize_vialrgb_mode

    _, allowed_modes, _ = _vialrgb_tables()
    return lighting_normalize_vialrgb_mode(mode, allowed_modes)


def _load_led_state() -> None:
    from .lighting import DEFAULT_LED_STATE, load_led_state as lighting_load_led_state

    runtime = _require_runtime()
    sequence, _, _ = _vialrgb_tables()
    runtime.led_state.clear()
    runtime.led_state.update(DEFAULT_LED_STATE)
    runtime.led_last_nonzero_mode = lighting_load_led_state(
        runtime.led_state_path,
        runtime.led_state,
        sequence,
        runtime.led_last_nonzero_mode,
    )


def _save_led_state() -> str:
    from .lighting import save_led_state as lighting_save_led_state

    runtime = _require_runtime()
    return lighting_save_led_state(runtime.led_state_path, runtime.led_state)


async def _debounced_save_led_state() -> None:
    from .lighting import debounced_save_led_state as lighting_debounced_save_led_state

    runtime = _require_runtime()
    try:
        await lighting_debounced_save_led_state(
            runtime.led_state_path,
            runtime.led_state,
            _LED_SAVE_DEBOUNCE_SEC,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("LED state save failed: %s", exc)


def _schedule_led_state_save() -> None:
    from .lighting import schedule_led_state_save as lighting_schedule_led_state_save

    runtime = _require_runtime()
    runtime.led_save_task = lighting_schedule_led_state_save(
        runtime.led_save_task,
        _save_led_state,
        _debounced_save_led_state,
    )


def _cancel_led_state_save() -> None:
    runtime = _require_runtime()
    task = runtime.led_save_task
    if task is not None and not task.done():
        task.cancel()
    runtime.led_save_task = None


def _push_i2cd_alert(message: str, sec: float = 2.0, immediate: bool = False) -> None:
    _require_notifier().push_i2cd_alert(message, sec, immediate=immediate)


def _notify_i2cd_led_effect_if_changed(previous_mode: int, current_mode: int) -> None:
    if previous_mode == current_mode:
        return
    from .lighting import vialrgb_effect_name

    _, _, effects = _vialrgb_tables()
    name = vialrgb_effect_name(current_mode, effects)
    _push_i2cd_alert(f"LED Effect\n{current_mode}: {name}", sec=2.0)


def _apply_lighting_key_action(action: str, is_press: bool) -> bool:
    from .lighting import apply_lighting_key_action as lighting_apply_lighting_key_action

    runtime = _require_runtime()
    sequence, _, effects = _vialrgb_tables()
    handled, runtime.led_last_nonzero_mode = lighting_apply_lighting_key_action(
        action,
        is_press,
        runtime.led_state,
        runtime.led_last_nonzero_mode,
        step=_LIGHTING_STEP,
        sequence=sequence,
        effects=effects,
        push_ledd_vialrgb=_push_ledd_vialrgb,
        schedule_save=_schedule_led_state_save,
        push_alert=_push_i2cd_alert,
    )
    return handled


def _input_event_context() -> Any:
    from .input_events import InputEventContext

    runtime = _require_runtime()
    return InputEventContext(
        layers=runtime.layers,
        interactions=runtime.interactions,
        macros=runtime.macros,
        encoders=runtime.encoders,
        joysticks=runtime.joysticks,
        pressed_matrix=runtime.pressed_matrix,
        push_ledd_key_event=_push_ledd_key_event,
        push_ledd_status=_push_ledd_status,
        push_i2cd_status=_push_i2cd_status,
        push_i2cd_alert=_push_i2cd_alert,
        push_ledd_anim=_push_ledd_anim,
        apply_lighting_key_action=_apply_lighting_key_action,
        mouse_write_fn=_active_mouse_write_fn(),
        push_ledd_morse_feedback=_push_ledd_morse_feedback,
        led_overlay_states=runtime.led_overlay_states,
        host_led_output=runtime.host_led_output,
        push_ledd_overlay_state=_push_ledd_overlay_state,
        bt_manager=runtime.bt_manager,
        push_bt_pairing_state=_push_bt_pairing_state,
        bt_passkey=runtime.bt_passkey,
        text_send=runtime.text_send,
        text_send_settings=runtime.text_send_settings,
        pty_mirror=runtime.pty_mirror,
        pty_mirror_prepare_output=_prepare_pty_mirror_output,
        pty_mirror_set_capture=_set_pty_mirror_capture,
        pty_mirror_release_output=_release_pty_mirror_output,
        core_key_event_fn=_send_core_key_event if CORE_KEY_EVENT_CTRL_SOCKET else None,
    )


def _active_mouse_write_fn() -> Any:
    runtime = _require_runtime()
    if not _native_outputd_active():
        return runtime.mouse_write_fn
    return _outputd_mouse_writer()


def _native_outputd_active() -> bool:
    from .native_outputd import native_outputd_control_enabled

    return native_outputd_control_enabled()


def _outputd_mouse_writer() -> Any:
    global _outputd_mouse_write_fn
    if _outputd_mouse_write_fn is None:
        from usbd.hid_report_broker import KIND_MOUSE
        from .native_outputd import create_outputd_report_writer, outputd_report_socket_from_env

        _outputd_mouse_write_fn = create_outputd_report_writer(KIND_MOUSE)
        log.info("companion mouse reports routed through outputd: %s", outputd_report_socket_from_env())
    return _outputd_mouse_write_fn


def _core_key_event_id(
    action: str,
    matrix_key: tuple[int, int] | None,
    source: str | None,
) -> str:
    source_label = source or "matrix"
    if matrix_key is None:
        return f"{source_label}:none:{action}"
    row, col = matrix_key
    return f"{source_label}:{row},{col}:{action}"


def _core_key_event_payload(
    action: str,
    is_press: bool,
    matrix_key: tuple[int, int] | None,
    source: str | None,
) -> dict:
    payload = {
        "t": "key_event",
        "id": _core_key_event_id(action, matrix_key, source),
        "action": action,
        "is_press": bool(is_press),
    }
    if source == "pty_terminal_mirror":
        payload["route"] = "us_sub_keyboard"
    return payload


def _prepare_pty_mirror_output() -> None:
    from .native_outputd import native_outputd_control_enabled, send_outputd_request

    if not native_outputd_control_enabled():
        return
    response = send_outputd_request({"t": "set_output_target", "target": "usb"})
    log.info("PTY mirror prepared outputd target=%s", response.get("target"))


async def _release_pty_mirror_output() -> None:
    if CORE_KEY_EVENT_CTRL_SOCKET:
        try:
            response = await _send_core_ctrl_request({"t": "release_all"})
            log.debug("PTY mirror core release response=%s", response)
        except Exception as exc:
            log.warning("PTY mirror core release failed: %s", exc)
    try:
        from .native_outputd import native_outputd_control_enabled, send_outputd_request

        if native_outputd_control_enabled():
            response = send_outputd_request({"t": "release_all"})
            log.debug("PTY mirror outputd release response=%s", response)
    except Exception as exc:
        log.warning("PTY mirror outputd release failed: %s", exc)


async def _send_core_ctrl_request(payload: dict) -> dict:
    if not CORE_KEY_EVENT_CTRL_SOCKET:
        return {}
    try:
        reader, writer = await asyncio.open_unix_connection(CORE_KEY_EVENT_CTRL_SOCKET)
        writer.write((json.dumps(payload, separators=(",", ":")) + "\n").encode())
        await writer.drain()
        response = await reader.readline()
        writer.close()
        await writer.wait_closed()
    except Exception as exc:
        raise RuntimeError(f"core ctrl request failed: {exc}") from exc
    if not response:
        raise RuntimeError("core ctrl request returned empty response")
    try:
        result = json.loads(response.decode())
    except Exception as exc:
        raise RuntimeError(f"core ctrl request returned invalid response: {exc}") from exc
    if result.get("result") == "error":
        raise RuntimeError(str(result.get("error") or result))
    return result


async def _reload_native_core() -> dict:
    return await _send_core_ctrl_request({"t": "reload"})


async def _set_pty_mirror_capture(enabled: bool) -> None:
    if not CORE_KEY_EVENT_CTRL_SOCKET:
        return
    response = await _send_core_ctrl_request({"t": "set_matrix_delegate_all", "enabled": bool(enabled)})
    log.info("PTY mirror matrix capture enabled=%s response=%s", enabled, response.get("matrix_delegate_all"))


async def _send_core_key_event(
    action: str,
    is_press: bool,
    matrix_key: tuple[int, int] | None,
    source: str | None,
) -> None:
    if not CORE_KEY_EVENT_CTRL_SOCKET:
        return
    payload = _core_key_event_payload(action, is_press, matrix_key, source)
    try:
        _result = await _send_core_ctrl_request(payload)
    except Exception as exc:
        log.warning("core key event forward failed action=%s press=%s: %s", action, is_press, exc)
        if source == "pty_terminal_mirror":
            raise RuntimeError(f"core key event forward failed: {exc}") from exc
        return


def _push_ledd_vialrgb_direct(first_index: int, pixels: list) -> None:
    _require_notifier().push_ledd_vialrgb_direct(first_index, pixels)


def _push_ledd_vialrgb_direct_pattern(pattern: str, fps: float, brightness: int) -> None:
    _require_notifier().push_ledd_vialrgb_direct_pattern(pattern, fps, brightness)


def _push_ledd_mode(mode: str) -> None:
    _require_notifier().push_ledd_mode(mode)


def _push_bt_pairing_state(phase: str, digits: str = "") -> None:
    """BTペアリング入力状態を表示系へ通知する。"""
    _require_notifier().push_bt_pairing_state(phase, digits)


def _clear_bt_pairing_indicator() -> None:
    runtime = _require_runtime()
    passkey = getattr(runtime, "bt_passkey", None)
    if passkey is not None:
        passkey.cancel()
    _push_bt_pairing_state("off", "")


def _push_i2cd_status() -> None:
    _require_notifier().push_i2cd_status()


def _push_i2cd_mode(mode: str) -> None:
    _require_notifier().push_i2cd_mode(mode)


def _push_i2cd_daemon_status(statuses: dict[str, bool]) -> None:
    _require_notifier().push_i2cd_daemon_status(statuses)


def _push_i2cd_script_exit(name: str, exit_code: int) -> None:
    _require_notifier().push_i2cd_script_exit(name, exit_code)


def _broadcast_key_event(keycode: int, modifier: int, is_press: bool) -> None:
    _require_notifier().broadcast_key_event(keycode, modifier, is_press)


async def _i2cd_connect_loop(sock_path: str) -> None:
    from .connections import reconnecting_unix_writer_loop

    runtime = _require_runtime()

    def set_writer(writer: Optional[asyncio.StreamWriter]) -> None:
        runtime.i2cd_writer = writer

    def on_connected() -> None:
        _push_i2cd_status()
        _push_i2cd_mode(runtime.current_i2cd_mode)
        _push_i2cd_daemon_status({"logicd-core": True, "logicd-companion": True})

    await reconnecting_unix_writer_loop(
        sock_path,
        get_writer=lambda: runtime.i2cd_writer,
        set_writer=set_writer,
        on_connected=on_connected,
        label="i2cd",
    )


async def _i2cd_daemon_status_loop(interval_sec: float = 5.0) -> None:
    while True:
        try:
            from .daemon_status import daemon_status_snapshot

            _push_i2cd_daemon_status(await daemon_status_snapshot())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.debug("daemon status snapshot failed: %s", exc)
        await asyncio.sleep(interval_sec)


async def _handle_spid_direction_motion(event: Any) -> None:
    if _spid_direction_mapper is None:
        log.warning("spid direction event ignored: direction binding is not configured")
        return
    from .spid_direction_actions import dispatch_spid_direction_result

    ctx = _input_event_context()
    result = _spid_direction_mapper.process(event, ctx.layers.get_action)
    await dispatch_spid_direction_result(
        result,
        ctx,
        hold_sec=_spid_runtime_settings.tap_hold_sec,
        gap_sec=_spid_runtime_settings.tap_gap_sec,
    )


async def _start_spid_motion(socket_path: str) -> None:
    global _spid_motion_task, _spid_motion_socket
    from .hid_report import MouseState

    runtime = _require_runtime()
    _spid_motion_socket = socket_path or DEFAULT_SPID_SOCKET
    if _spid_motion_task is not None and not _spid_motion_task.done():
        _spid_motion_task.cancel()
        try:
            await _spid_motion_task
        except asyncio.CancelledError:
            pass
    from .spid_motion import spid_motion_connect_loop

    event_handler = _handle_spid_direction_motion if _spid_runtime_settings.mode == "direction" else None

    def mouse_write_with_held_buttons(report: bytes) -> None:
        buttons = int(getattr(runtime.macros, "mouse_buttons", 0) or 0)
        _active_mouse_write_fn()(MouseState.merge_buttons(report, buttons))

    _spid_motion_task = asyncio.create_task(
        spid_motion_connect_loop(
            _spid_motion_socket,
            mouse_write_with_held_buttons,
            enabled=True,
            output_hz=_SPID_MOTION_OUTPUT_HZ,
            max_buffered_events=_SPID_MOTION_MAX_BUFFERED,
            event_handler=event_handler,
        )
    )
    log.info("spid motion connection requested: %s mode=%s", _spid_motion_socket, _spid_runtime_settings.mode)


async def _stop_spid_motion() -> None:
    global _spid_motion_task
    if _spid_motion_task is None:
        return
    _spid_motion_task.cancel()
    try:
        await _spid_motion_task
    except asyncio.CancelledError:
        pass
    _spid_motion_task = None
    log.info("spid motion connection stopped")


async def _dispatch_touch_flick_event(event: Any) -> dict[str, Any]:
    from .touch_flick_dispatch import dispatch_touch_flick_event

    return await dispatch_touch_flick_event(event, _input_event_context())


async def _handle_ledd_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    from .sockets import handle_ledd_client as socket_handle_ledd_client

    runtime = _require_runtime()

    def send_initial() -> None:
        _push_ledd_semantic_roles()
        _push_ledd_semantic_keymap()
        _push_ledd_status()
        _push_ledd_mode(runtime.current_hid_mode)
        _push_ledd_vialrgb()
        for state, enabled in runtime.led_overlay_states.items():
            if enabled:
                _push_ledd_overlay_state(state, True)

    await socket_handle_ledd_client(reader, writer, writers=runtime.ledd_writers, send_initial=send_initial)


async def _handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    from .matrix_pipeline import handle_matrix_client as pipeline_handle_matrix_client

    await pipeline_handle_matrix_client(
        reader,
        writer,
        runtime=_require_runtime(),
        matrix_in_range=_matrix_in_range,
    )


async def _handle_matrix_tap_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    from .protocol import parse_matrix_event_packet

    peer = writer.get_extra_info("peername") or "<matrix-tap>"
    log.debug("matrix tap client connected: %s", peer)
    buffer = b""
    try:
        while True:
            chunk = await reader.read(64)
            if not chunk:
                break
            buffer += chunk
            while len(buffer) >= 4:
                packet, buffer = buffer[:4], buffer[4:]
                parsed = parse_matrix_event_packet(packet)
                if parsed is None:
                    log.warning("matrix tap event ignored: invalid packet=%r", packet)
                    continue
                kind, row, col = parsed
                if not _matrix_in_range(row, col):
                    log.warning(
                        "matrix tap event ignored: out-of-range kind=%s row=%d col=%d",
                        kind,
                        row,
                        col,
                    )
                    continue
                _record_observed_matrix_event(row, col, kind == "P")
                # The tap stream carries press and release for matrix testers.
                # LED reactive effects only need press triggers.
                if kind == "P":
                    _push_ledd_key_event(row, col, True)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def _process_ctrl_json(line: str, writer: Optional[asyncio.StreamWriter] = None) -> None:
    from .ctrl import CtrlContext, process_ctrl_json
    from .input_events import handle_analog_stick as input_handle_analog_stick

    runtime = _require_runtime()
    ctx = CtrlContext(
        matrix_in_range=_matrix_in_range,
        handle_analog_stick=lambda index, x, y: input_handle_analog_stick(index, x, y, _input_event_context()),
        layers=runtime.layers,
        current_hid_mode=runtime.current_hid_mode,
        current_output_target=runtime.current_output_target,
        pressed_matrix=_matrix_status_pressed(),
        save_runtime_keymap=_save_runtime_keymap,
        reset_runtime_keymap=_reset_runtime_keymap,
        led_state=runtime.led_state,
        normalize_led_state=_normalize_led_state,
        load_led_state=_load_led_state,
        save_led_state=_save_led_state,
        cancel_led_state_save=_cancel_led_state_save,
        push_ledd_vialrgb_direct=_push_ledd_vialrgb_direct,
        push_ledd_vialrgb_direct_pattern=_push_ledd_vialrgb_direct_pattern,
        normalize_vialrgb_mode=_normalize_vialrgb_mode,
        remember_nonzero_led_mode=_remember_nonzero_led_mode,
        push_ledd_vialrgb=_push_ledd_vialrgb,
        schedule_led_state_save=_schedule_led_state_save,
        notify_i2cd_led_effect_if_changed=_notify_i2cd_led_effect_if_changed,
        interactions=runtime.interactions,
        handle_spid_connect=_start_spid_motion,
        handle_spid_disconnect=_stop_spid_motion,
        handle_bt_action=_handle_ctrl_bt_action,
        handle_output_target=_handle_ctrl_output_target,
        handle_host_led_report=_handle_ctrl_host_led_report,
        push_ledd_semantic_reload=_push_ledd_semantic_reload,
        drain_morse_feedback=runtime.interactions.drain_morse_feedback,
        handle_touch_flick_event=_dispatch_touch_flick_event,
        cancel_text_send=_cancel_text_send,
        joysticks=runtime.joysticks,
        push_ledd_key_event=_push_ledd_key_event,
        reload_native_core=_reload_native_core if CORE_KEY_EVENT_CTRL_SOCKET else None,
    )
    await process_ctrl_json(line, ctx, writer)


async def _handle_ctrl_bt_action(action: str) -> None:
    from .input_events import handle_resolved_action as input_handle_resolved_action

    await input_handle_resolved_action(action, True, _input_event_context())


async def _handle_ctrl_output_target(target: str) -> None:
    runtime = _require_runtime()
    _cancel_text_send("output_switch")
    write_fn = getattr(runtime.macros, "_write", None)
    fn_name = {
        "auto": "force_auto",
        "gadget": "force_gadget",
        "uinput": "force_uinput",
        "bt": "force_bt",
    }.get(target)
    if fn_name is None:
        raise ValueError(f"invalid output target: {target!r}")
    fn = getattr(write_fn, fn_name, None)
    if fn is None:
        raise RuntimeError(f"output target {target!r} is not available")
    if target == "bt":
        await runtime.bt_manager.ensure_powered_for_output()
    fn()
    if target != "auto":
        _push_ledd_mode(target)
        _push_i2cd_mode(target)
    if target in {"bt", "auto"}:
        _clear_bt_pairing_indicator()
    log.info("ctrl OUTPUT: forced output target %s", target)


def _cancel_text_send(reason: str) -> dict:
    status = _require_runtime().text_send.cancel(reason)
    return _finalize_text_send_cancel(reason, status)


def _expire_text_send_runner(now: float) -> dict | None:
    status = _require_runtime().text_send.cancel_if_timed_out(now)
    if status is None:
        return None
    return _finalize_text_send_cancel("runner_timeout", status)


def _finalize_text_send_cancel(reason: str, status: dict) -> dict:
    runtime = _require_runtime()
    if status.get("zero_report_required"):
        from .hid_report import HidState

        runtime.state.release_all()
        try:
            runtime.macros._write(HidState.null_report())
        except Exception as exc:
            log.warning("text send zero report failed: %s", exc)
        else:
            status.update(runtime.text_send.mark_zero_report_sent(reason))
    if status.get("canceled"):
        log.info("text send canceled: reason=%s", status.get("last_cancel_reason"))
    return status


async def _handle_ctrl_host_led_report(report: int) -> dict[str, bool]:
    return _apply_host_led_report(report)


def _save_runtime_keymap() -> str:
    from hidloom_paths import default_config_file
    from .keymap_store import save_runtime_keymap

    runtime = _require_runtime()
    preferred = "/mnt/p3/keymap.json"
    fallback = str(default_config_file("keymap.json"))
    return save_runtime_keymap(runtime.layers.layers_snapshot(), preferred=preferred, fallback=fallback)


def _reset_runtime_keymap() -> dict:
    from hidloom_paths import default_config_file
    from .keymap_store import reset_runtime_keymap

    runtime = _require_runtime()
    runtime_path = "/mnt/p3/keymap.json"
    default_path = str(default_config_file("keymap.json"))
    return reset_runtime_keymap(runtime.layers, runtime_path=runtime_path, default_path=default_path)


async def _handle_ctrl_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    from .sockets import handle_ctrl_client as socket_handle_ctrl_client

    await socket_handle_ctrl_client(reader, writer, process_line=_process_ctrl_json)


async def _handle_key_event_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    from .key_event_pipeline import handle_key_event_client as pipeline_handle_key_event_client

    await pipeline_handle_key_event_client(reader, writer, runtime=_require_runtime())


async def _output_processor() -> None:
    from .key_event_pipeline import output_processor as pipeline_output_processor

    await pipeline_output_processor(_require_runtime())


async def _main_async(cfg_path: Optional[str]) -> None:
    from . import config_loader
    from .host_led_reader import host_led_output_report_loop
    from .matrix_pipeline import event_processor as pipeline_event_processor

    runtime = _require_runtime()
    log.info("logicd boot marker: main_async start elapsed=%.3fs", time.monotonic() - _BOOT_START_MONOTONIC)
    started = time.monotonic()
    cfg = config_loader.load(cfg_path)
    log.info(
        "logicd boot marker: config loaded duration=%.3fs elapsed=%.3fs",
        time.monotonic() - started,
        time.monotonic() - _BOOT_START_MONOTONIC,
    )
    started = time.monotonic()
    _load_led_state()
    log.info(
        "logicd boot marker: led state loaded duration=%.3fs elapsed=%.3fs",
        time.monotonic() - started,
        time.monotonic() - _BOOT_START_MONOTONIC,
    )
    started = time.monotonic()
    _apply_config(cfg)
    log.info(
        "logicd boot marker: runtime config applied duration=%.3fs elapsed=%.3fs",
        time.monotonic() - started,
        time.monotonic() - _BOOT_START_MONOTONIC,
    )

    settings = cfg.get("settings", {})
    key_sock = _socket_from_settings(settings, "socket", "/tmp/matrix_events.sock", "LOGICD_MATRIX_SOCKET")
    delegate_sock = _socket_from_settings(
        settings,
        "delegate_socket",
        "/tmp/logicd_delegate_events.sock",
        "LOGICD_DELEGATE_SOCKET",
    )
    matrix_tap_sock = _socket_from_settings(
        settings,
        "matrix_tap_socket",
        "/tmp/matrix_tap_events.sock",
        "LOGICD_MATRIX_TAP_SOCKET",
    )
    ctrl_sock = _socket_from_settings(settings, "ctrl_socket", "/tmp/ctrl_events.sock", "LOGICD_CTRL_SOCKET")
    ledd_sock = _socket_from_settings(settings, "ledd_socket", "/tmp/ledd_events.sock", "LOGICD_LEDD_SOCKET")
    i2c_sock = _socket_from_settings(settings, "i2c_socket", "/tmp/i2c_events.sock", "LOGICD_I2C_SOCKET")
    key_event_sock = _socket_from_settings(
        settings,
        "key_event_socket",
        "/tmp/key_events.sock",
        "LOGICD_KEY_EVENT_SOCKET",
    )
    hidg_path = settings.get("hidg", "/dev/hidg0")

    for path in (key_sock, delegate_sock, matrix_tap_sock, ctrl_sock, ledd_sock, key_event_sock):
        if path is not None and os.path.exists(path):
            os.unlink(path)

    servers: list[tuple[str, asyncio.AbstractServer]] = []
    if key_sock is not None:
        servers.append(("matrix events", await asyncio.start_unix_server(_handle_client, path=key_sock)))
    if delegate_sock is not None:
        servers.append(("delegated matrix events", await asyncio.start_unix_server(_handle_client, path=delegate_sock)))
    if matrix_tap_sock is not None:
        servers.append(("matrix tap events", await asyncio.start_unix_server(_handle_matrix_tap_client, path=matrix_tap_sock)))
    if ctrl_sock is not None:
        servers.append(("ctrl events", await asyncio.start_unix_server(_handle_ctrl_client, path=ctrl_sock)))
    if ledd_sock is not None:
        servers.append(("ledd events", await asyncio.start_unix_server(_handle_ledd_client, path=ledd_sock)))
    if key_event_sock is not None:
        servers.append(("key events", await asyncio.start_unix_server(_handle_key_event_client, path=key_event_sock)))

    if key_sock is not None:
        os.chmod(key_sock, 0o660)
    if delegate_sock is not None:
        os.chmod(delegate_sock, 0o666)
    if matrix_tap_sock is not None:
        os.chmod(matrix_tap_sock, 0o666)
    if ctrl_sock is not None:
        os.chmod(ctrl_sock, 0o666)
    if ledd_sock is not None:
        os.chmod(ledd_sock, 0o666)
    if key_event_sock is not None:
        os.chmod(key_event_sock, 0o666)

    if key_sock is not None:
        log.info("Listening on %s (matrix events)", key_sock)
    else:
        log.info("Matrix events socket disabled")
    if delegate_sock is not None:
        log.info("Listening on %s (delegated matrix events)", delegate_sock)
    if matrix_tap_sock is not None:
        log.info("Listening on %s (matrix tap events)", matrix_tap_sock)
    if ctrl_sock is not None:
        log.info("Listening on %s (ctrl events)", ctrl_sock)
    if ledd_sock is not None:
        log.info("Listening on %s (ledd events)", ledd_sock)
    if key_event_sock is not None:
        log.info("Listening on %s (key events)", key_event_sock)
    log.info("logicd boot marker: sockets listening elapsed=%.3fs", time.monotonic() - _BOOT_START_MONOTONIC)
    if i2c_sock is not None:
        log.info("Connecting to %s (i2c events – i2cd server)", i2c_sock)

    loop = asyncio.get_running_loop()

    async def _reload_config() -> None:
        try:
            _cancel_text_send("config_reload")
            next_cfg = config_loader.load(cfg_path)
            _apply_config(next_cfg)
            _push_ledd_semantic_roles()
            _push_ledd_semantic_keymap()
            _push_ledd_status()
            _push_i2cd_status()
            _push_ledd_mode(runtime.current_hid_mode)
            _push_i2cd_mode(runtime.current_i2cd_mode)
            _push_ledd_vialrgb()
            log.info("SIGHUP reload complete")
        except Exception:
            log.exception("SIGHUP reload failed")

    def _on_sighup() -> None:
        log.info("SIGHUP received – reloading config")
        asyncio.create_task(_reload_config())

    def _on_sigterm() -> None:
        for task in asyncio.all_tasks():
            task.cancel()

    loop.add_signal_handler(signal.SIGHUP, _on_sighup)
    loop.add_signal_handler(signal.SIGTERM, _on_sigterm)

    processor = asyncio.create_task(pipeline_event_processor(runtime, _input_event_context))
    output_proc = asyncio.create_task(_output_processor())
    usb_monitor = asyncio.create_task(_usb_monitor_loop())
    host_led_reader = asyncio.create_task(host_led_output_report_loop(hidg_path, _handle_ctrl_host_led_report))
    i2cd_connect = asyncio.create_task(_i2cd_connect_loop(i2c_sock)) if i2c_sock is not None else None
    i2cd_daemon_status = asyncio.create_task(_i2cd_daemon_status_loop())

    try:
        async with AsyncExitStack() as stack:
            for _, server in servers:
                await stack.enter_async_context(server)
            await asyncio.gather(*(server.serve_forever() for _, server in servers))
    except asyncio.CancelledError:
        pass
    finally:
        if runtime.led_save_task is not None and not runtime.led_save_task.done():
            runtime.led_save_task.cancel()
            try:
                await runtime.led_save_task
            except asyncio.CancelledError:
                pass
        try:
            _save_led_state()
        except Exception as exc:
            log.warning("LED state final save failed: %s", exc)
        processor.cancel()
        output_proc.cancel()
        usb_monitor.cancel()
        host_led_reader.cancel()
        if i2cd_connect is not None:
            i2cd_connect.cancel()
        i2cd_daemon_status.cancel()
        await _stop_spid_motion()
        _cancel_text_send("daemon_shutdown")
        runtime.state.release_all()
        try:
            from .hid_report import HidState

            runtime.macros._write(HidState.null_report())
        except Exception:
            pass
        if runtime.hid_fd is not None:
            try:
                os.close(runtime.hid_fd)
            except OSError:
                pass
            runtime.hid_fd = None
        for path in (key_sock, delegate_sock, matrix_tap_sock, ctrl_sock, ledd_sock, key_event_sock):
            if path is not None and os.path.exists(path):
                os.unlink(path)
        log.info("logicd stopped")


def main() -> None:
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        print(_HELP.rstrip())
        return

    from .runtime import setup_logging_from_env

    setup_logging_from_env()
    log.info("logicd boot marker: logging ready elapsed=%.3fs", time.monotonic() - _BOOT_START_MONOTONIC)
    _init_runtime()
    cfg_path: Optional[str] = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        asyncio.run(_main_async(cfg_path))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
