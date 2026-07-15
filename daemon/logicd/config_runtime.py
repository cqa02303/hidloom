"""Runtime configuration application for logicd."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Callable

from .bindings import load_encoder_bindings, load_joystick_bindings
from .btd_sender import BtdReportSender, DEFAULT_BTD_SOCKET
from .ctrl import script_dirs_from_config
from .encoder import EncoderManager
from .hid_report import (
    HID_REPORT_ID_CONSUMER,
    HID_REPORT_ID_KEYBOARD,
    HID_REPORT_ID_MOUSE,
    add_hid_report_id,
)
from .host_led_output import normalize_host_led_output_config
from .interaction_config import validate_interaction_settings
from .interaction_engine import InteractionEngine
from .joystick import JoystickManager
from .keymap import LayerManager
from .macro import MacroExecutor
from .native_outputd import NativeOutputdSwitchWriter, native_outputd_control_enabled, outputd_ctrl_socket_from_env
from .output import (
    create_dynamic_write_fn,
    create_uinput_write_fn,
    make_consumer_report_fn,
    make_consumer_fn,
    new_hid_write_fn,
    with_hid_report_id,
)
from .output_router import (
    BluetoothHidOutputBackend,
    CallableOutputBackend,
    DebugOutputBackend,
    OutputRouter,
    parse_output_targets,
)
from .state import LogicdRuntime
from .usbd_report_broker import (
    DEFAULT_USBD_HID_REPORT_SOCKET,
    KIND_CONSUMER,
    KIND_KEYBOARD,
    KIND_MOUSE,
    KIND_US_SUB_KEYBOARD,
    create_usbd_hid_report_writer,
    env_flag_enabled,
)

log = logging.getLogger(__name__)


def _interaction_settings(cfg: dict, *, matrix_in_range: Callable[[int, int], bool]) -> dict:
    settings = cfg.get("settings", {})
    validation = validate_interaction_settings(
        settings.get("interaction", {}),
        matrix_in_range=matrix_in_range,
    )
    for warning in validation.warnings:
        log.warning(warning)
    return validation.settings


def _host_led_output_config(cfg: dict):
    return normalize_host_led_output_config(cfg.get("settings", {}).get("host_led_output"))


def _configured_output_targets(cfg: dict) -> tuple[str, ...]:
    """Return enabled keyboard output targets.

    Design intent:
    - Outputs are no longer an exclusive selector such as gadget OR uinput.
    - ``gadget``, ``uinput``, ``bt``, and ``debug`` are peer connections.
    - A key report may be delivered to every enabled target at the same time.

    Selection policy:
    - ``LOGICD_OUTPUTS`` has first priority.
    - ``settings.outputs`` in config has second priority.
    - default is ``auto`` for single-output automatic selection:
      gadget, then uinput. Bluetooth fallback is opt-in via
      ``LOGICD_AUTO_BT_FALLBACK=1`` / ``settings.auto_bt_fallback``.

    Examples:
    - ``LOGICD_OUTPUTS=debug`` for debug-only logging
    - ``LOGICD_OUTPUTS=gadget,uinput,debug,bt`` for simultaneous fan-out
    """
    settings = cfg.get("settings", {})
    raw = os.environ.get("LOGICD_OUTPUTS")
    if raw is None:
        raw = settings.get("outputs")
    return parse_output_targets(raw, default="auto")


def _btd_socket_path(cfg: dict) -> str:
    """Return btd socket path used by the logicd Bluetooth output backend.

    The socket path is configuration, not protocol. Keeping it here lets tests
    and local development redirect BT output to a temporary btd instance without
    changing OutputRouter or BluetoothHidOutputBackend.
    """
    settings = cfg.get("settings", {})
    return os.environ.get("BTD_EVENTS_SOCK") or settings.get("btd_events_sock") or DEFAULT_BTD_SOCKET


def _bt_disconnect_on_output_disable(cfg: dict) -> bool:
    settings = cfg.get("settings", {})
    raw = os.environ.get("LOGICD_BT_DISCONNECT_ON_OUTPUT_DISABLE")
    if raw is None:
        raw = settings.get("bt_disconnect_on_output_disable", True)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def _auto_bt_fallback_enabled(cfg: dict) -> bool:
    settings = cfg.get("settings", {})
    raw = os.environ.get("LOGICD_AUTO_BT_FALLBACK")
    if raw is None:
        raw = settings.get("auto_bt_fallback", False)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _usbd_hid_report_broker_enabled(cfg: dict) -> bool:
    settings = cfg.get("settings", {})
    raw = os.environ.get("LOGICD_USBD_HID_REPORT_BROKER")
    if raw is None:
        raw = settings.get("usbd_hid_report_broker", False)
    return env_flag_enabled(raw)


def _usbd_hid_report_socket_path(cfg: dict) -> str:
    settings = cfg.get("settings", {})
    return (
        os.environ.get("LOGICD_USBD_HID_REPORT_SOCKET")
        or settings.get("usbd_hid_report_socket")
        or DEFAULT_USBD_HID_REPORT_SOCKET
    )


def _usb_split_keyboard_enabled(cfg: dict) -> bool:
    settings = cfg.get("settings", {})
    raw = os.environ.get("LOGICD_USB_SPLIT_KEYBOARD")
    if raw is None:
        raw_config = settings.get("usb_split_keyboard", {})
        raw = raw_config.get("enabled", False) if isinstance(raw_config, dict) else raw_config
    return env_flag_enabled(raw)


def _usb_split_keyboard_route(cfg: dict) -> str:
    settings = cfg.get("settings", {})
    raw = os.environ.get("LOGICD_USB_SPLIT_KEYBOARD_ROUTE")
    if raw is None:
        raw_config = settings.get("usb_split_keyboard", {})
        raw = raw_config.get("route", "ime_keys") if isinstance(raw_config, dict) else "ime_keys"
    route = str(raw or "ime_keys").strip().lower().replace("-", "_")
    if route in {"all", "all_keys"}:
        return "all"
    if route in {
        "jis_special_us_default",
        "jis_specials_us_default",
        "us_default_jis_special",
        "us_default_jis_specials",
        "jis_special",
        "jis_specials",
    }:
        return "jis_special_us_default"
    return "ime_keys"


SPLIT_KEYBOARD_SWITCH_USAGES = frozenset(range(0x87, 0x99))
JIS_ZENKAKU_HANKAKU_INTERNAL_MARKER = 0x5A
JIS_ZENKAKU_HANKAKU_HID_USAGE = 0x35
JIS_SPECIAL_ON_MAIN_USAGES = frozenset(
    {
        0x87,  # KC_RO / KC_INT1
        0x88,  # KC_KANA / KC_INT2
        0x89,  # KC_JYEN / KC_INT3
        0x8A,  # KC_HENKAN / KC_INT4
        0x8B,  # KC_MUHENKAN / KC_INT5
        0x8C,  # KC_INT6
        0x8D,  # KC_INT7
        0x8E,  # KC_INT8
        0x8F,  # KC_INT9
    }
)


def _report_has_usage(report: bytes, usage: int) -> bool:
    report = bytes(report)
    return any(key == usage for key in report[2:8])


def _report_is_internal_zenkaku_hankaku(report: bytes) -> bool:
    report = bytes(report)
    return (
        len(report) >= 8
        and report[1] == JIS_ZENKAKU_HANKAKU_INTERNAL_MARKER
        and _report_has_usage(report, JIS_ZENKAKU_HANKAKU_HID_USAGE)
    )


def _clear_report_reserved_byte(report: bytes) -> bytes:
    rewritten = bytearray(report)
    if len(rewritten) >= 2:
        rewritten[1] = 0
    return bytes(rewritten)


def _report_has_split_keyboard_switch_key(report: bytes) -> bool:
    report = bytes(report)
    return any(key in SPLIT_KEYBOARD_SWITCH_USAGES for key in report[2:8])


def _report_has_jis_special_on_main_key(report: bytes) -> bool:
    report = bytes(report)
    return any(key in JIS_SPECIAL_ON_MAIN_USAGES for key in report[2:8])


def _with_usb_split_keyboard_switch(
    primary_write: Callable[[bytes], None],
    us_sub_write: Callable[[bytes], None],
    *,
    route: str = "ime_keys",
) -> Callable[[bytes], None]:
    """Route reports between the JIS main keyboard and the US sub keyboard."""
    us_sub_key_active = False
    primary_key_active = False
    primary_modifier_mirror_active = False
    zenkaku_hankaku_active = False

    def primary_modifier_report(report: bytes) -> bytes:
        return bytes([report[0] if report else 0, 0, 0, 0, 0, 0, 0, 0])

    def write(report: bytes) -> None:
        nonlocal us_sub_key_active, primary_key_active, primary_modifier_mirror_active, zenkaku_hankaku_active
        report = bytes(report)
        if route == "all":
            if _report_is_internal_zenkaku_hankaku(report):
                us_sub_write(_clear_report_reserved_byte(report))
                return
            us_sub_write(report)
            return
        if route == "jis_special_us_default":
            if _report_is_internal_zenkaku_hankaku(report):
                primary_key_active = False
                primary_modifier_mirror_active = bool(report[0])
                us_sub_key_active = False
                zenkaku_hankaku_active = True
                primary_write(_clear_report_reserved_byte(report))
                return
            if report == bytes(8) and zenkaku_hankaku_active:
                zenkaku_hankaku_active = False
                primary_modifier_mirror_active = False
                primary_write(report)
                return
            zenkaku_hankaku_active = False
            if _report_has_jis_special_on_main_key(report):
                primary_key_active = True
                primary_modifier_mirror_active = bool(report[0])
                us_sub_key_active = False
                primary_write(report)
                return
            if primary_key_active:
                primary_key_active = False
                primary_modifier_mirror_active = bool(report[0])
                primary_write(primary_modifier_report(report))
                if report == bytes(8):
                    return
            elif primary_modifier_mirror_active:
                primary_modifier_mirror_active = bool(report[0])
                primary_write(primary_modifier_report(report))
            primary_key_active = False
            us_sub_write(report)
            return
        if _report_has_split_keyboard_switch_key(report):
            us_sub_key_active = True
            us_sub_write(report)
            return
        if report == bytes(8) and us_sub_key_active:
            us_sub_key_active = False
            us_sub_write(report)
            return
        us_sub_key_active = False
        primary_write(report)

    return write


def make_mode_aware_mouse_write_fn(
    gadget_mouse_write: Callable[[bytes], None],
    get_mode: Callable[[], str],
    bt_mouse_write: Callable[[bytes], None] | None = None,
) -> Callable[[bytes], None]:
    """Return a mouse writer that follows the active keyboard output mode."""
    def write(report: bytes) -> None:
        mode = str(get_mode() or "")
        if mode in {"gadget", "auto"}:
            gadget_mouse_write(report)
            return
        if mode == "bt" and bt_mouse_write is not None:
            bt_mouse_write(report)
            return
        log.debug("mouse report dropped for output mode %s: %s", mode, report.hex())

    return write


def effective_output_mode(runtime: LogicdRuntime, writer: Callable[[bytes], None] | None = None) -> str:
    """Return the concrete output mode for report types that cannot fan out."""
    mode = str(getattr(runtime, "current_hid_mode", "") or "")
    if mode != "auto":
        return mode
    writer_mode = getattr(writer, "current_mode", None)
    if isinstance(writer_mode, str) and writer_mode:
        return writer_mode
    return mode


def make_mode_aware_consumer_write_fn(
    gadget_consumer_write: Callable[[int, bool], None],
    get_mode: Callable[[], str],
    bt_consumer_write: Callable[[int, bool], None] | None = None,
) -> Callable[[int, bool], None]:
    """Return a Consumer Control writer that follows the active output mode."""
    def write(usage_id: int, is_press: bool) -> None:
        mode = str(get_mode() or "")
        if mode in {"gadget", "auto", "uinput"}:
            gadget_consumer_write(usage_id, is_press)
            return
        if mode == "bt" and bt_consumer_write is not None:
            bt_consumer_write(usage_id, is_press)
            return
        log.debug("consumer report dropped for output mode %s: usage=0x%04X press=%s", mode, usage_id, is_press)

    return write


def _build_output_router(
    targets: tuple[str, ...],
    *,
    hidg_path: str,
    cfg: dict,
    runtime: LogicdRuntime,
    push_ledd_mode: Callable[[str], None],
    push_i2cd_mode: Callable[[str], None],
) -> Callable[[bytes], None]:
    """Build one writer callable backed by multiple enabled output backends.

    Common backend interface:
    - ``name``: stable backend name such as ``gadget`` or ``debug``
    - ``enabled``: connection-style on/off flag
    - ``write(report: bytes)``: consume the same 8-byte keyboard HID report
    - ``check()``: optional connection refresh/probe hook
    - ``set_enabled(bool)``: toggle output without changing key processing

    The rest of logicd intentionally sees only a ``Callable[[bytes], None]``.
    That keeps MacroExecutor / key_event_pipeline independent of the number of
    physical or virtual outputs attached behind the router.

    `bt` is always registered, even when not initially enabled, so a key action
    such as KC_BT can switch the output target without requiring a daemon reload.
    """
    def on_bt_disabled() -> None:
        if not _bt_disconnect_on_output_disable(cfg):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            log.debug("BT output disabled outside running event loop; skip disconnect")
            return
        loop.create_task(runtime.bt_manager.disconnect_connected_devices())

    btd_sender = BtdReportSender(socket_path=_btd_socket_path(cfg))
    runtime.bt_manager.btd_sender = btd_sender
    use_usbd_broker = _usbd_hid_report_broker_enabled(cfg)
    usbd_socket_path = _usbd_hid_report_socket_path(cfg)
    if use_usbd_broker:
        gadget_keyboard_write = create_usbd_hid_report_writer(KIND_KEYBOARD, usbd_socket_path)
        if _usb_split_keyboard_enabled(cfg):
            gadget_keyboard_write = _with_usb_split_keyboard_switch(
                gadget_keyboard_write,
                create_usbd_hid_report_writer(KIND_US_SUB_KEYBOARD, usbd_socket_path),
                route=_usb_split_keyboard_route(cfg),
            )
    else:
        gadget_keyboard_write = with_hid_report_id(
            new_hid_write_fn(hidg_path, None, nonblocking=True),
            HID_REPORT_ID_KEYBOARD,
        )

    def on_target_changed(target: str) -> None:
        runtime.current_output_target = target
        if target != "auto":
            push_ledd_mode(target)
            push_i2cd_mode(target)
        btd_sender.set_reconnect_advertising(target == "bt")

    router = OutputRouter(on_bt_disabled=on_bt_disabled, on_target_changed=on_target_changed)

    # Register all backends regardless of initial target state. This keeps
    # gadget/uinput/bt/debug as peer fan-out targets and lets output key actions
    # select a backend without a daemon reload.
    def btd_available() -> bool:
        return os.path.exists(btd_sender.socket_path)

    router.register(
        CallableOutputBackend(
            "gadget",
            gadget_keyboard_write,
            enabled="gadget" in targets,
        )
    )
    router.register(
        CallableOutputBackend(
            "uinput",
            create_uinput_write_fn(cfg, runtime.uinput_shared_ref),
            enabled="uinput" in targets,
        )
    )
    router.register(DebugOutputBackend(enabled="debug" in targets))
    router.register(
        BluetoothHidOutputBackend(
            sender=btd_sender,
            enabled="bt" in targets,
        )
    )

    if "auto" in targets:
        # ``auto`` is a single active output selected in priority order:
        # USB gadget, Bluetooth HID, then uinput fallback.
        auto_fn = create_dynamic_write_fn(
            hidg_path,
            cfg,
            get_state=runtime.state.build,
            release_all=runtime.state.release_all,
            uinput_factory=lambda current_cfg: create_uinput_write_fn(current_cfg, runtime.uinput_shared_ref),
            bt_writer=btd_sender,
            bt_available=btd_available,
            allow_bt_fallback=_auto_bt_fallback_enabled(cfg),
            on_bt_disabled=on_bt_disabled,
            push_ledd_mode=push_ledd_mode,
            push_i2cd_mode=push_i2cd_mode,
            gadget_transform=(
                (lambda data: data)
                if use_usbd_broker
                else (lambda data: add_hid_report_id(HID_REPORT_ID_KEYBOARD, data))
            ),
            gadget_write_fn=gadget_keyboard_write if use_usbd_broker else None,
        )
        router.register(CallableOutputBackend("auto", auto_fn, enabled=True))

    router.set_targets(targets)
    runtime.current_output_target = targets[0] if targets else ""
    log.info("Keyboard output targets enabled: %s", ",".join(router.enabled_names()) or "none")
    if use_usbd_broker:
        log.info("usbd HID report broker output enabled: %s", usbd_socket_path)
        if _usb_split_keyboard_enabled(cfg):
            log.info("usbd USB split keyboard switch enabled route=%s", _usb_split_keyboard_route(cfg))
    if native_outputd_control_enabled():
        log.info("native outputd target control enabled: %s", outputd_ctrl_socket_from_env())
        return NativeOutputdSwitchWriter(
            router,
            socket_path=outputd_ctrl_socket_from_env(),
            on_target_changed=on_target_changed,
        )
    return router


def apply_runtime_config(
    cfg: dict,
    runtime: LogicdRuntime,
    *,
    default_script_dir: str,
    fallback_script_dir: str,
    matrix_in_range: Callable[[int, int], bool],
    push_ledd_mode: Callable[[str], None],
    push_i2cd_mode: Callable[[str], None],
    broadcast_key_event: Callable[[int, int, bool], None],
    push_i2cd_script_exit: Callable[[str, int], None],
) -> None:
    boot_started = time.monotonic()
    runtime.text_send_settings = dict(cfg.get("settings", {})) if isinstance(cfg.get("settings"), dict) else {}
    hidg_path = cfg["settings"].get("hidg", "/dev/hidg0")
    mouse_path = cfg["settings"].get("mouse_hidg", hidg_path)
    consumer_path = cfg["settings"].get("consumer_hidg", hidg_path)
    console_fallback = cfg["settings"].get("console_fallback", True)
    script_dirs = script_dirs_from_config(cfg, default_script_dir, fallback_script_dir)
    interaction = _interaction_settings(cfg, matrix_in_range=matrix_in_range)
    runtime.host_led_output = _host_led_output_config(cfg)
    use_usbd_broker = _usbd_hid_report_broker_enabled(cfg)
    usbd_socket_path = _usbd_hid_report_socket_path(cfg)
    log.info("logicd boot marker: runtime config prep duration=%.3fs", time.monotonic() - boot_started)
    started = time.monotonic()

    log.info("Initialize HID device")

    if runtime.hid_fd is not None:
        try:
            os.close(runtime.hid_fd)
        except OSError:
            pass
        runtime.hid_fd = None

    if runtime.mouse_fd is not None:
        try:
            os.close(runtime.mouse_fd)
        except OSError:
            pass
        runtime.mouse_fd = None

    if runtime.consumer_fd is not None:
        try:
            os.close(runtime.consumer_fd)
        except OSError:
            pass
        runtime.consumer_fd = None

    if mouse_path != hidg_path:
        try:
            runtime.mouse_fd = os.open(mouse_path, os.O_WRONLY | os.O_NONBLOCK)
            log.info("Opened mouse HID device: %s", mouse_path)
        except OSError as exc:
            log.info("Mouse HID not available (%s): %s", mouse_path, exc)

    runtime.state.release_all()
    if use_usbd_broker:
        gadget_mouse_write = create_usbd_hid_report_writer(KIND_MOUSE, usbd_socket_path)
        gadget_consumer_fn = make_consumer_report_fn(
            create_usbd_hid_report_writer(KIND_CONSUMER, usbd_socket_path),
            runtime.uinput_shared_ref,
        )
    else:
        gadget_mouse_write = (
            with_hid_report_id(
                new_hid_write_fn(mouse_path, None, nonblocking=True),
                HID_REPORT_ID_MOUSE,
            )
            if mouse_path == hidg_path
            else new_hid_write_fn(mouse_path, runtime.mouse_fd, nonblocking=True)
        )
        gadget_consumer_fn = make_consumer_fn(
            consumer_path,
            runtime.uinput_shared_ref,
            report_id=HID_REPORT_ID_CONSUMER if consumer_path == hidg_path else None,
        )
    consumer_fn = gadget_consumer_fn

    output_targets = _configured_output_targets(cfg)
    runtime.current_output_target = output_targets[0] if output_targets else ""
    if output_targets == ("auto",) and not console_fallback:
        # Legacy fixed gadget writer for deployments that explicitly disable
        # console fallback.  It intentionally does not expose dynamic target
        # switching keys.
        if use_usbd_broker:
            write_fn = create_usbd_hid_report_writer(KIND_KEYBOARD, usbd_socket_path)
            if _usb_split_keyboard_enabled(cfg):
                write_fn = _with_usb_split_keyboard_switch(
                    write_fn,
                    create_usbd_hid_report_writer(KIND_US_SUB_KEYBOARD, usbd_socket_path),
                    route=_usb_split_keyboard_route(cfg),
                )
            log.info("Using usbd HID report broker for fixed gadget output: %s", usbd_socket_path)
            if _usb_split_keyboard_enabled(cfg):
                log.info("Using usbd USB split keyboard switch for fixed gadget output route=%s", _usb_split_keyboard_route(cfg))
        else:
            try:
                runtime.hid_fd = os.open(hidg_path, os.O_WRONLY)
                log.info("Opened HID device: %s", hidg_path)
            except OSError as exc:
                log.error("Cannot open %s: %s – reports will be discarded", hidg_path, exc)
            write_fn = with_hid_report_id(new_hid_write_fn(hidg_path, runtime.hid_fd), HID_REPORT_ID_KEYBOARD)
        runtime.mouse_write_fn = make_mode_aware_mouse_write_fn(
            gadget_mouse_write,
            lambda: effective_output_mode(runtime, write_fn),
        )
        if use_usbd_broker:
            write_fn(bytes(8))
        elif runtime.hid_fd is not None:
            from .output import async_hid_init

            asyncio.create_task(async_hid_init(runtime.hid_fd, write_fn))
    else:
        # Use OutputRouter even for the default auto path.  This preserves the
        # existing auto path while also allowing KC_USB/KC_CONSOLE/KC_BT to
        # select explicit peer backends at runtime.
        write_fn = _build_output_router(
            output_targets,
            hidg_path=hidg_path,
            cfg=cfg,
            runtime=runtime,
            push_ledd_mode=push_ledd_mode,
            push_i2cd_mode=push_i2cd_mode,
        )
        runtime.mouse_write_fn = make_mode_aware_mouse_write_fn(
            gadget_mouse_write,
            lambda: effective_output_mode(runtime, write_fn),
            BtdReportSender(socket_path=_btd_socket_path(cfg)).send_mouse,
        )
        consumer_fn = make_mode_aware_consumer_write_fn(
            gadget_consumer_fn,
            lambda: effective_output_mode(runtime, write_fn),
            BtdReportSender(socket_path=_btd_socket_path(cfg)).send_consumer_usage,
        )
        log.info("output router enabled")
    log.info("logicd boot marker: output setup duration=%.3fs", time.monotonic() - started)
    started = time.monotonic()

    runtime.layers = LayerManager()
    runtime.layers.load(cfg["layers"])
    runtime.layers.set_conditional_rules(interaction.get("conditional_layers", []))
    runtime.interactions = InteractionEngine(
        runtime.layers,
        tapping_term=float(interaction.get("tapping_term", 0.200)),
        hold_on_other_key_press=bool(interaction.get("hold_on_other_key_press", True)),
        combo_term=float(interaction.get("combo_term", 0.050)),
        combos=interaction.get("combos", []),
        tap_dance_term=float(interaction.get("tap_dance_term", 0.200)),
        tap_dances=interaction.get("tap_dances", {}),
        morse_behaviors=interaction.get("morse_behaviors", {}),
        key_overrides=interaction.get("key_overrides", []),
        caps_word=interaction.get("caps_word", {}),
        repeat_key=interaction.get("repeat_key", {}),
        mod_morphs=interaction.get("mod_morphs", {}),
    )
    runtime.encoders = EncoderManager(load_encoder_bindings(cfg.get("encoders", []), matrix_in_range))
    runtime.joysticks = JoystickManager(load_joystick_bindings(cfg.get("joysticks", []), matrix_in_range))

    runtime.macros = MacroExecutor(
        runtime.state,
        write_fn,
        cfg["macros"],
        mouse_write_fn=runtime.mouse_write_fn,
        consumer_write_fn=consumer_fn,
        key_event_broadcast=broadcast_key_event,
        script_dir=script_dirs,
        script_exit_notify=push_i2cd_script_exit,
    )
    log.info("logicd boot marker: layer interaction macro setup duration=%.3fs", time.monotonic() - started)
