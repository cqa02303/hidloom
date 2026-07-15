"""VIA/Vial protocol constants and runtime defaults."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from hidloom_paths import default_config_file, runtime_file

REPORT_SIZE = 32
log = logging.getLogger(__name__)

# VIA commands
CMD_VIA_GET_PROTOCOL_VERSION = 0x01
CMD_VIA_GET_KEYBOARD_VALUE = 0x02
CMD_VIA_SET_KEYCODE = 0x05
CMD_VIA_LIGHTING_SET_VALUE = 0x07
CMD_VIA_LIGHTING_GET_VALUE = 0x08
CMD_VIA_LIGHTING_SAVE = 0x09
CMD_VIA_MACRO_GET_COUNT = 0x0C
CMD_VIA_MACRO_GET_BUFFER_SIZE = 0x0D
CMD_VIA_MACRO_GET_BUFFER = 0x0E
CMD_VIA_MACRO_SET_BUFFER = 0x0F
CMD_VIA_GET_LAYER_COUNT = 0x11
CMD_VIA_KEYMAP_GET_BUFFER = 0x12
CMD_VIA_KEYMAP_SET_BUFFER = 0x13
CMD_VIA_VIAL_PREFIX = 0xFE
VIA_SWITCH_MATRIX_STATE = 0x03

# Vial subcommands
CMD_VIAL_GET_KEYBOARD_ID = 0x00
CMD_VIAL_GET_SIZE = 0x01
CMD_VIAL_GET_DEFINITION = 0x02
CMD_VIAL_GET_ENCODER = 0x03
CMD_VIAL_SET_ENCODER = 0x04
CMD_VIAL_GET_UNLOCK_STATUS = 0x05
CMD_VIAL_UNLOCK_START = 0x06
CMD_VIAL_UNLOCK_POLL = 0x07
CMD_VIAL_LOCK = 0x08
CMD_VIAL_QMK_SETTINGS_QUERY = 0x09
CMD_VIAL_QMK_SETTINGS_GET = 0x0A
CMD_VIAL_QMK_SETTINGS_SET = 0x0B
CMD_VIAL_QMK_SETTINGS_RESET = 0x0C
CMD_VIAL_DYNAMIC_ENTRY_OP = 0x0D

DYNAMIC_VIAL_GET_NUMBER_OF_ENTRIES = 0x00
DYNAMIC_VIAL_TAP_DANCE_GET = 0x01
DYNAMIC_VIAL_TAP_DANCE_SET = 0x02
DYNAMIC_VIAL_COMBO_GET = 0x03
DYNAMIC_VIAL_COMBO_SET = 0x04
DYNAMIC_VIAL_KEY_OVERRIDE_GET = 0x05
DYNAMIC_VIAL_KEY_OVERRIDE_SET = 0x06
DYNAMIC_VIAL_ALT_REPEAT_KEY_GET = 0x07
DYNAMIC_VIAL_ALT_REPEAT_KEY_SET = 0x08

# VialRGB subcommands
VIALRGB_GET_INFO = 0x40
VIALRGB_GET_MODE = 0x41
VIALRGB_GET_SUPPORTED = 0x42
VIALRGB_GET_NUMBER_LEDS = 0x43
VIALRGB_GET_LED_INFO = 0x44
VIALRGB_SET_MODE = 0x41
VIALRGB_DIRECT_FASTSET = 0x42

VIA_PROTOCOL_VERSION = 9
VIAL_PROTOCOL_VERSION = 5


def _env_int(name: str, default: int, *, min_value: int | None = None, max_value: int | None = None) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw, 0)
    except ValueError:
        log.warning("invalid %s=%r; using default %d", name, raw, default)
        return default
    if min_value is not None and value < min_value:
        log.warning("invalid %s=%d below minimum %d; using default %d", name, value, min_value, default)
        return default
    if max_value is not None and value > max_value:
        log.warning("invalid %s=%d above maximum %d; using default %d", name, value, max_value, default)
        return default
    return value


DEFAULT_LAYER_COUNT = _env_int("VIALD_LAYER_COUNT", 1, min_value=1, max_value=32)
DEFAULT_TAP_DANCE_COUNT = _env_int("VIALD_TAP_DANCE_COUNT", 4, min_value=0, max_value=128)
DEFAULT_COMBO_COUNT = _env_int("VIALD_COMBO_COUNT", 4, min_value=0, max_value=128)
DEFAULT_KEY_OVERRIDE_COUNT = _env_int("VIALD_KEY_OVERRIDE_COUNT", 4, min_value=0, max_value=128)
DEFAULT_MACRO_COUNT = _env_int("VIALD_MACRO_COUNT", 8, min_value=0, max_value=32)
DEFAULT_MACRO_BUFFER_SIZE = _env_int("VIALD_MACRO_BUFFER_SIZE", 512, min_value=0, max_value=4096)
VIAL_JSON_PATH = Path(os.environ.get(
    "VIALD_JSON_PATH",
    str(runtime_file("vial.json") if runtime_file("vial.json").exists() else default_config_file("vial.json")),
))
LEDD_JSON_PATH = Path(os.environ.get("VIALD_LEDD_JSON_PATH", str(default_config_file("ledd.json"))))
CTRLD_SOCKET_PATH = os.environ.get("VIALD_CTRL_SOCK", "/tmp/ctrl_events.sock")
SAVE_ON_SET = os.environ.get("VIALD_SAVE_ON_SET", "1") not in {"0", "false", "False"}
UNLOCK_COUNTER_MAX = _env_int("VIALD_UNLOCK_COUNTER_MAX", 25, min_value=1, max_value=255)
