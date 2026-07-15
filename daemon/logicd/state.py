"""Mutable runtime state container for logicd."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

from .hid_report import HidState

DEFAULT_LED_STATE = {"mode": 40, "speed": 128, "h": 175, "s": 77, "v": 160}


def _default_layer_manager() -> Any:
    from .keymap import LayerManager

    return LayerManager()


def _default_bt_manager() -> Any:
    from .bt_manager import BtManager

    return BtManager()


def _default_bt_passkey() -> Any:
    from .bt_passkey import build_bt_passkey_input

    return build_bt_passkey_input()


def _default_encoder_manager() -> Any:
    from .encoder import EncoderManager

    return EncoderManager()


def _default_joystick_manager() -> Any:
    from .joystick import JoystickManager

    return JoystickManager()


def _default_host_led_output_config() -> Any:
    from .host_led_output import DEFAULT_HOST_LED_OUTPUT_CONFIG

    return DEFAULT_HOST_LED_OUTPUT_CONFIG


def _default_text_send_state() -> Any:
    from .text_send_safety import TextSendRuntimeState

    return TextSendRuntimeState()


def _default_pty_mirror() -> Any:
    from .pty_mirror_runtime import PtyMirrorRuntime

    return PtyMirrorRuntime()


@dataclass
class LogicdRuntime:
    hid_fd: Optional[int] = None
    mouse_fd: Optional[int] = None
    consumer_fd: Optional[int] = None
    uinput_shared_ref: list = field(default_factory=lambda: [None])
    state: HidState = field(default_factory=HidState)
    layers: Any = field(default_factory=_default_layer_manager)
    interactions: Any = None
    macros: Any = None
    bt_manager: Any = field(default_factory=_default_bt_manager)
    bt_passkey: Any = field(default_factory=_default_bt_passkey)
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    key_event_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    ledd_writers: list = field(default_factory=list)
    i2cd_writer: Optional[asyncio.StreamWriter] = None
    key_event_writers: list = field(default_factory=list)
    current_hid_mode: str = "uinput"
    current_i2cd_mode: str = "uinput"
    current_output_target: str = "auto"
    pressed_matrix: set[tuple[int, int]] = field(default_factory=set)
    observed_pressed_matrix: set[tuple[int, int]] = field(default_factory=set)
    encoders: Any = field(default_factory=_default_encoder_manager)
    joysticks: Any = field(default_factory=_default_joystick_manager)
    mouse_write_fn: Any = lambda b: None
    led_state: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_LED_STATE))
    led_state_path: str = "/mnt/p3/led_state.json"
    led_save_task: Optional[asyncio.Task] = None
    led_last_nonzero_mode: int = 40
    led_overlay_states: dict[str, bool] = field(default_factory=dict)
    host_led_output: Any = field(default_factory=_default_host_led_output_config)
    text_send: Any = field(default_factory=_default_text_send_state)
    text_send_settings: dict[str, Any] = field(default_factory=dict)
    pty_mirror: Any = field(default_factory=_default_pty_mirror)

    def __post_init__(self) -> None:
        if self.interactions is None:
            from .interaction_engine import InteractionEngine

            self.interactions = InteractionEngine(self.layers)
        if self.macros is None:
            from .macro import MacroExecutor

            self.macros = MacroExecutor(self.state, lambda b: None, {})
