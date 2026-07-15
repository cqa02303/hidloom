"""Build host-side output commands for PTY terminal mirror text."""
from __future__ import annotations

import base64
import re
from typing import Any

PTY_TERMINAL_TEXT_PLAN_SCHEMA = "pty_terminal.text_plan.v1"
PTY_TERMINAL_SOURCE = "pty_terminal_mirror"
WINDOWS_TEXT_EDITOR_PROFILE = "windows_text_editor_us_sub_keyboard"
WINDOWS_TERMINAL_WSL_CAT_PROFILE = "windows_terminal_wsl_cat_us_sub_keyboard"
DEFAULT_PTY_TERMINAL_HOST_PROFILE = WINDOWS_TEXT_EDITOR_PROFILE
SUPPORTED_PTY_TERMINAL_HOST_PROFILES = {
    WINDOWS_TEXT_EDITOR_PROFILE,
    WINDOWS_TERMINAL_WSL_CAT_PROFILE,
}
DEFAULT_PTY_TERMINAL_MAX_TEXT_CHARS = 256
CHUNKED_PTY_TERMINAL_MAX_TEXT_CHARS = 240
PTY_TERMINAL_RECEIVER_COMMAND = "stty -echo -icanon min 1 time 0; cat; stty sane"
PTY_TERMINAL_RECEIVER_RESTORE_COMMAND = "stty sane"
PTY_TERMINAL_STARTUP_IME_OFF_KEY = "KC_LANG2"
RECEIVER_TAP_HOLD_SEC = 0.006
RECEIVER_TAP_GAP_SEC = 0.020
RECEIVER_STOP_TAP_HOLD_SEC = 0.006
RECEIVER_STOP_TAP_GAP_SEC = 0.020
DIRECT_OUTPUT_TAP_HOLD_SEC = 0.002
DIRECT_OUTPUT_TAP_GAP_SEC = 0.002
DIRECT_OUTPUT_NEWLINE_POST_GAP_SEC = 0.020
CHUNKED_OUTPUT_TAP_HOLD_SEC = 0.002
CHUNKED_OUTPUT_TAP_GAP_SEC = 0.002
CHUNKED_OUTPUT_POST_GAP_SEC = 0.002
ANSI_SPACE_RUN_MIN = 4
_OSC_RE = re.compile(r"\x1b\].*?(?:\x07|\x1b\\)", re.DOTALL)
_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_ESC_RE = re.compile(r"\x1b.")

_US_ASCII_TAPS: dict[str, tuple[str, tuple[str, ...]]] = {
    "a": ("KC_A", ()),
    "b": ("KC_B", ()),
    "c": ("KC_C", ()),
    "d": ("KC_D", ()),
    "e": ("KC_E", ()),
    "f": ("KC_F", ()),
    "g": ("KC_G", ()),
    "h": ("KC_H", ()),
    "i": ("KC_I", ()),
    "j": ("KC_J", ()),
    "k": ("KC_K", ()),
    "l": ("KC_L", ()),
    "m": ("KC_M", ()),
    "n": ("KC_N", ()),
    "o": ("KC_O", ()),
    "p": ("KC_P", ()),
    "q": ("KC_Q", ()),
    "r": ("KC_R", ()),
    "s": ("KC_S", ()),
    "t": ("KC_T", ()),
    "u": ("KC_U", ()),
    "v": ("KC_V", ()),
    "w": ("KC_W", ()),
    "x": ("KC_X", ()),
    "y": ("KC_Y", ()),
    "z": ("KC_Z", ()),
    "A": ("KC_A", ("KC_LSHIFT",)),
    "B": ("KC_B", ("KC_LSHIFT",)),
    "C": ("KC_C", ("KC_LSHIFT",)),
    "D": ("KC_D", ("KC_LSHIFT",)),
    "E": ("KC_E", ("KC_LSHIFT",)),
    "F": ("KC_F", ("KC_LSHIFT",)),
    "G": ("KC_G", ("KC_LSHIFT",)),
    "H": ("KC_H", ("KC_LSHIFT",)),
    "I": ("KC_I", ("KC_LSHIFT",)),
    "J": ("KC_J", ("KC_LSHIFT",)),
    "K": ("KC_K", ("KC_LSHIFT",)),
    "L": ("KC_L", ("KC_LSHIFT",)),
    "M": ("KC_M", ("KC_LSHIFT",)),
    "N": ("KC_N", ("KC_LSHIFT",)),
    "O": ("KC_O", ("KC_LSHIFT",)),
    "P": ("KC_P", ("KC_LSHIFT",)),
    "Q": ("KC_Q", ("KC_LSHIFT",)),
    "R": ("KC_R", ("KC_LSHIFT",)),
    "S": ("KC_S", ("KC_LSHIFT",)),
    "T": ("KC_T", ("KC_LSHIFT",)),
    "U": ("KC_U", ("KC_LSHIFT",)),
    "V": ("KC_V", ("KC_LSHIFT",)),
    "W": ("KC_W", ("KC_LSHIFT",)),
    "X": ("KC_X", ("KC_LSHIFT",)),
    "Y": ("KC_Y", ("KC_LSHIFT",)),
    "Z": ("KC_Z", ("KC_LSHIFT",)),
    "1": ("KC_1", ()),
    "2": ("KC_2", ()),
    "3": ("KC_3", ()),
    "4": ("KC_4", ()),
    "5": ("KC_5", ()),
    "6": ("KC_6", ()),
    "7": ("KC_7", ()),
    "8": ("KC_8", ()),
    "9": ("KC_9", ()),
    "0": ("KC_0", ()),
    " ": ("KC_SPACE", ()),
    "-": ("KC_MINUS", ()),
    "=": ("KC_EQUAL", ()),
    "[": ("KC_LBRACKET", ()),
    "]": ("KC_RBRACKET", ()),
    "\\": ("KC_BSLASH", ()),
    ";": ("KC_SCOLON", ()),
    "'": ("KC_QUOTE", ()),
    "`": ("KC_GRAVE", ()),
    ",": ("KC_COMMA", ()),
    ".": ("KC_DOT", ()),
    "/": ("KC_SLASH", ()),
    "!": ("KC_1", ("KC_LSHIFT",)),
    "@": ("KC_2", ("KC_LSHIFT",)),
    "#": ("KC_3", ("KC_LSHIFT",)),
    "$": ("KC_4", ("KC_LSHIFT",)),
    "%": ("KC_5", ("KC_LSHIFT",)),
    "^": ("KC_6", ("KC_LSHIFT",)),
    "&": ("KC_7", ("KC_LSHIFT",)),
    "*": ("KC_8", ("KC_LSHIFT",)),
    "(": ("KC_9", ("KC_LSHIFT",)),
    ")": ("KC_0", ("KC_LSHIFT",)),
    "_": ("KC_MINUS", ("KC_LSHIFT",)),
    "+": ("KC_EQUAL", ("KC_LSHIFT",)),
    "{": ("KC_LBRACKET", ("KC_LSHIFT",)),
    "}": ("KC_RBRACKET", ("KC_LSHIFT",)),
    "|": ("KC_BSLASH", ("KC_LSHIFT",)),
    ":": ("KC_SCOLON", ("KC_LSHIFT",)),
    '"': ("KC_QUOTE", ("KC_LSHIFT",)),
    "~": ("KC_GRAVE", ("KC_LSHIFT",)),
    "<": ("KC_COMMA", ("KC_LSHIFT",)),
    ">": ("KC_DOT", ("KC_LSHIFT",)),
    "?": ("KC_SLASH", ("KC_LSHIFT",)),
}

_SHIFT_MODIFIER_ALIASES = {
    "KC_LSFT",
    "KC_RSFT",
    "KC_LSHIFT",
    "KC_RSHIFT",
    "LSFT",
    "RSFT",
    "SHIFT",
}
_CTRL_MODIFIER_ALIASES = {
    "KC_LCTL",
    "KC_RCTL",
    "KC_LCTRL",
    "KC_RCTRL",
    "LCTL",
    "RCTL",
    "LCTRL",
    "RCTRL",
    "CTRL",
    "CONTROL",
}

_KEY_ACTION_ALIASES = {
    "KC_SPC": "KC_SPACE",
    "KC_MINS": "KC_MINUS",
    "KC_EQL": "KC_EQUAL",
    "KC_LBRC": "KC_LBRACKET",
    "KC_RBRC": "KC_RBRACKET",
    "KC_BSLS": "KC_BSLASH",
    "KC_SCLN": "KC_SCOLON",
    "KC_QUOT": "KC_QUOTE",
    "KC_GRV": "KC_GRAVE",
    "KC_COMM": "KC_COMMA",
    "KC_SLSH": "KC_SLASH",
}


def key_action_to_text_char(action: str, modifiers: list[str] | tuple[str, ...] | set[str] | None = None) -> str:
    """Return the printable text-editor echo for a PTY key action."""
    normalized = str(action or "").strip()
    normalized = _KEY_ACTION_ALIASES.get(normalized, normalized)
    if not normalized:
        return ""
    if normalized in {"KC_ENTER", "KC_ENT", "KC_RETURN"}:
        return "\r\n"
    if normalized in {"KC_TAB"}:
        return "\t"
    if normalized in {"KC_BSPC", "KC_BSPACE", "KC_BACKSPACE"}:
        return "\x08"
    modifier_set = {str(mod).strip().upper() for mod in (modifiers or [])}
    if modifier_set & _CTRL_MODIFIER_ALIASES:
        return ""
    shifted = bool(modifier_set & _SHIFT_MODIFIER_ALIASES)
    for char, (key, key_modifiers) in _US_ASCII_TAPS.items():
        if key != normalized:
            continue
        key_shifted = bool(set(key_modifiers) & {"KC_LSHIFT", "KC_RSHIFT"})
        if key_shifted == shifted:
            return char
    return ""


def wsl_cat_base64_command(text: str) -> str:
    """Wrap terminal output as a WSL command that writes decoded ANSI to stdout."""
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return f"wsl bash -lc \"printf %s '{encoded}' | base64 -d\""


def strip_unsupported_terminal_sequences(text: str) -> tuple[str, list[str]]:
    blocking: list[str] = []
    stripped = _OSC_RE.sub("", text)
    if stripped != text:
        blocking.append("osc_sequence_stripped")
    return stripped, blocking


def strip_text_editor_terminal_sequences(text: str) -> tuple[str, list[str]]:
    blocking: list[str] = []
    stripped = _OSC_RE.sub("", text)
    if stripped != text:
        blocking.append("osc_sequence_stripped")
    without_csi = _CSI_RE.sub("", stripped)
    if without_csi != stripped:
        blocking.append("csi_sequence_stripped")
    without_esc = _ESC_RE.sub("", without_csi)
    if without_esc != without_csi:
        blocking.append("esc_sequence_stripped")
    return without_esc, blocking


def normalize_pty_terminal_host_profile(host_profile: str | None) -> str:
    profile = str(host_profile or "").strip()
    if not profile:
        return DEFAULT_PTY_TERMINAL_HOST_PROFILE
    return profile


def pty_terminal_profile_uses_receiver(host_profile: str | None) -> bool:
    return normalize_pty_terminal_host_profile(host_profile) == WINDOWS_TERMINAL_WSL_CAT_PROFILE


def us_ascii_tap_sequence(text: str, *, append_enter: bool = False) -> tuple[list[dict[str, Any]], list[str]]:
    taps: list[dict[str, Any]] = []
    blocking: list[str] = []
    for index, char in enumerate(text):
        mapped = _US_ASCII_TAPS.get(char)
        if mapped is None:
            blocking.append(f"unsupported_us_ascii_char_at_{index}")
            continue
        key, modifiers = mapped
        taps.append({"type": "tap", "key": key, "modifiers": list(modifiers), "char": char})
    if append_enter:
        taps.append({"type": "tap", "key": "KC_ENTER", "modifiers": [], "char": "\n"})
    return taps, blocking


def terminal_text_tap_sequence(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    taps: list[dict[str, Any]] = []
    blocking: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\x08":
            taps.append({"type": "tap", "key": "KC_H", "modifiers": ["KC_LCTRL"], "char": "\\x08"})
            index += 1
            continue
        if char == " ":
            run_end = index + 1
            while run_end < len(text) and text[run_end] == " ":
                run_end += 1
            run_len = run_end - index
            if run_len >= ANSI_SPACE_RUN_MIN:
                cursor_taps, cursor_blocking = us_ascii_tap_sequence(f"[{run_len}C")
                taps.append({"type": "tap", "key": "KC_ESC", "modifiers": [], "char": "\\x1b"})
                taps.extend(cursor_taps)
                blocking.extend(cursor_blocking)
                index = run_end
                continue
            for _ in range(run_len):
                taps.append({"type": "tap", "key": "KC_SPACE", "modifiers": [], "char": " "})
            index = run_end
            continue
        if char == "\r" and index + 1 < len(text) and text[index + 1] == "\n":
            taps.append(
                {
                    "type": "tap",
                    "key": "KC_ENTER",
                    "modifiers": [],
                    "char": "\r\n",
                    "post_gap_sec": DIRECT_OUTPUT_NEWLINE_POST_GAP_SEC,
                }
            )
            index += 2
            continue
        if char == "\x1b":
            taps.append({"type": "tap", "key": "KC_ESC", "modifiers": [], "char": "\\x1b"})
            index += 1
            continue
        if char in {"\n", "\r"}:
            taps.append(
                {
                    "type": "tap",
                    "key": "KC_ENTER",
                    "modifiers": [],
                    "char": char,
                    "post_gap_sec": DIRECT_OUTPUT_NEWLINE_POST_GAP_SEC,
                }
            )
            index += 1
            continue
        if char == "\t":
            taps.append({"type": "tap", "key": "KC_TAB", "modifiers": [], "char": char})
            index += 1
            continue
        mapped = _US_ASCII_TAPS.get(char)
        if mapped is None:
            blocking.append(f"unsupported_terminal_char_at_{index}")
            index += 1
            continue
        key, modifiers = mapped
        taps.append({"type": "tap", "key": key, "modifiers": list(modifiers), "char": char})
        index += 1
    return taps, blocking


def text_editor_tap_sequence(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    taps: list[dict[str, Any]] = []
    blocking: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\x08":
            taps.append({"type": "tap", "key": "KC_BACKSPACE", "modifiers": [], "char": "\\x08"})
            index += 1
            continue
        if char == "\r" and index + 1 < len(text) and text[index + 1] == "\n":
            taps.append(
                {
                    "type": "tap",
                    "key": "KC_ENTER",
                    "modifiers": [],
                    "char": "\r\n",
                    "post_gap_sec": DIRECT_OUTPUT_NEWLINE_POST_GAP_SEC,
                }
            )
            index += 2
            continue
        if char in {"\n", "\r"}:
            taps.append(
                {
                    "type": "tap",
                    "key": "KC_ENTER",
                    "modifiers": [],
                    "char": char,
                    "post_gap_sec": DIRECT_OUTPUT_NEWLINE_POST_GAP_SEC,
                }
            )
            index += 1
            continue
        if char == "\t":
            taps.append({"type": "tap", "key": "KC_TAB", "modifiers": [], "char": char})
            index += 1
            continue
        mapped = _US_ASCII_TAPS.get(char)
        if mapped is None:
            blocking.append(f"unsupported_text_editor_char_at_{index}")
            index += 1
            continue
        key, modifiers = mapped
        taps.append({"type": "tap", "key": key, "modifiers": list(modifiers), "char": char})
        index += 1
    return taps, blocking


def build_pty_terminal_receiver_plan(
    *,
    host_profile: str = DEFAULT_PTY_TERMINAL_HOST_PROFILE,
    source: str = PTY_TERMINAL_SOURCE,
) -> dict[str, Any]:
    blocking: list[str] = []
    host_profile = normalize_pty_terminal_host_profile(host_profile)
    if source != PTY_TERMINAL_SOURCE:
        blocking.append("invalid_pty_terminal_source")
    if host_profile not in SUPPORTED_PTY_TERMINAL_HOST_PROFILES:
        blocking.append("unsupported_pty_terminal_host_profile")
    if host_profile == WINDOWS_TEXT_EDITOR_PROFILE:
        blocking.append("pty_receiver_not_required")
        return {
            "schema": PTY_TERMINAL_TEXT_PLAN_SCHEMA,
            "read_only": True,
            "source": source,
            "host_profile": host_profile,
            "transport": "keyboard_tap_sequence",
            "route": "us_sub_keyboard",
            "wrapper": "text_editor_direct_input_no_receiver",
            "receiver": False,
            "command": "",
            "tap_count": 0,
            "taps": [],
            "tap_hold_sec": RECEIVER_TAP_HOLD_SEC,
            "tap_gap_sec": RECEIVER_TAP_GAP_SEC,
            "post_gap_sec": 0.0,
            "available": False,
            "blocking_reasons": list(dict.fromkeys(blocking)),
            "loop_guard": {
                "synthetic_source": PTY_TERMINAL_SOURCE,
                "macro_recording_allowed": False,
                "interaction_input_allowed": False,
                "pty_input_routing_allowed": False,
            },
            "notes": [
                "Text editor mode sends PTY output directly to the focused editor.",
                "No host-side cat receiver is started for this profile.",
            ],
        }
    taps, tap_blocking = us_ascii_tap_sequence(PTY_TERMINAL_RECEIVER_COMMAND, append_enter=True)
    blocking.extend(tap_blocking)
    return {
        "schema": PTY_TERMINAL_TEXT_PLAN_SCHEMA,
        "read_only": True,
        "source": source,
        "host_profile": host_profile,
        "transport": "keyboard_tap_sequence",
        "route": "us_sub_keyboard",
        "wrapper": "wsl_cat_echo_off_receiver",
        "receiver": True,
        "command": PTY_TERMINAL_RECEIVER_COMMAND,
        "tap_count": len(taps),
        "taps": taps,
        "tap_hold_sec": RECEIVER_TAP_HOLD_SEC,
        "tap_gap_sec": RECEIVER_TAP_GAP_SEC,
        "post_gap_sec": 0.250,
        "available": not blocking,
        "blocking_reasons": list(dict.fromkeys(blocking)),
        "loop_guard": {
            "synthetic_source": PTY_TERMINAL_SOURCE,
            "macro_recording_allowed": False,
            "interaction_input_allowed": False,
            "pty_input_routing_allowed": False,
        },
        "notes": [
            "Starts a WSL cat receiver with terminal echo disabled.",
            "The EXIT/INT/TERM trap restores terminal echo when the receiver exits normally.",
        ],
    }


def build_pty_terminal_receiver_stop_plan(
    *,
    host_profile: str = DEFAULT_PTY_TERMINAL_HOST_PROFILE,
    source: str = PTY_TERMINAL_SOURCE,
) -> dict[str, Any]:
    blocking: list[str] = []
    host_profile = normalize_pty_terminal_host_profile(host_profile)
    if source != PTY_TERMINAL_SOURCE:
        blocking.append("invalid_pty_terminal_source")
    if host_profile not in SUPPORTED_PTY_TERMINAL_HOST_PROFILES:
        blocking.append("unsupported_pty_terminal_host_profile")
    if host_profile == WINDOWS_TEXT_EDITOR_PROFILE:
        blocking.append("pty_receiver_not_required")
        return {
            "schema": PTY_TERMINAL_TEXT_PLAN_SCHEMA,
            "read_only": True,
            "source": source,
            "host_profile": host_profile,
            "transport": "keyboard_tap_sequence",
            "route": "us_sub_keyboard",
            "wrapper": "text_editor_direct_input_no_receiver_stop",
            "receiver": False,
            "receiver_stop": True,
            "command": "",
            "tap_count": 0,
            "taps": [],
            "tap_hold_sec": RECEIVER_STOP_TAP_HOLD_SEC,
            "tap_gap_sec": RECEIVER_STOP_TAP_GAP_SEC,
            "available": False,
            "blocking_reasons": list(dict.fromkeys(blocking)),
            "loop_guard": {
                "synthetic_source": PTY_TERMINAL_SOURCE,
                "macro_recording_allowed": False,
                "interaction_input_allowed": False,
                "pty_input_routing_allowed": False,
            },
            "notes": [
                "Text editor mode does not start a host receiver, so there is nothing to stop.",
            ],
        }
    restore_taps, tap_blocking = us_ascii_tap_sequence(PTY_TERMINAL_RECEIVER_RESTORE_COMMAND, append_enter=True)
    blocking.extend(tap_blocking)
    taps = [
        {"type": "tap", "key": "KC_C", "modifiers": ["KC_LCTRL"], "char": "\x03", "post_gap_sec": 0.350},
        {"type": "tap", "key": "KC_C", "modifiers": ["KC_LCTRL"], "char": "\x03", "post_gap_sec": 0.350},
        {"type": "tap", "key": "KC_ENTER", "modifiers": [], "char": "\r", "post_gap_sec": 0.350},
        *restore_taps,
    ]
    return {
        "schema": PTY_TERMINAL_TEXT_PLAN_SCHEMA,
        "read_only": True,
        "source": source,
        "host_profile": host_profile,
        "transport": "keyboard_tap_sequence",
        "route": "us_sub_keyboard",
        "wrapper": "wsl_cat_echo_off_receiver_stop",
        "receiver": True,
        "receiver_stop": True,
        "command": PTY_TERMINAL_RECEIVER_RESTORE_COMMAND,
        "tap_count": len(taps),
        "taps": taps,
        "tap_hold_sec": RECEIVER_STOP_TAP_HOLD_SEC,
        "tap_gap_sec": RECEIVER_STOP_TAP_GAP_SEC,
        "available": not blocking,
        "blocking_reasons": list(dict.fromkeys(blocking)),
        "loop_guard": {
            "synthetic_source": PTY_TERMINAL_SOURCE,
            "macro_recording_allowed": False,
            "interaction_input_allowed": False,
            "pty_input_routing_allowed": False,
        },
        "notes": [
            "Sends Ctrl-C to the host-side echo-off cat receiver when PTY mirror mode exits.",
            "Then sends stty sane as a defensive terminal restore command.",
        ],
    }


def build_pty_terminal_startup_plan(
    *,
    host_profile: str = DEFAULT_PTY_TERMINAL_HOST_PROFILE,
    source: str = PTY_TERMINAL_SOURCE,
) -> dict[str, Any]:
    blocking: list[str] = []
    host_profile = normalize_pty_terminal_host_profile(host_profile)
    if source != PTY_TERMINAL_SOURCE:
        blocking.append("invalid_pty_terminal_source")
    if host_profile not in SUPPORTED_PTY_TERMINAL_HOST_PROFILES:
        blocking.append("unsupported_pty_terminal_host_profile")
    if host_profile != WINDOWS_TEXT_EDITOR_PROFILE:
        blocking.append("startup_ime_off_not_required")
    taps = [
        {
            "type": "tap",
            "key": PTY_TERMINAL_STARTUP_IME_OFF_KEY,
            "modifiers": [],
            "char": "",
            "purpose": "ime_off",
            "post_gap_sec": 0.050,
        }
    ]
    return {
        "schema": PTY_TERMINAL_TEXT_PLAN_SCHEMA,
        "read_only": True,
        "source": source,
        "host_profile": host_profile,
        "transport": "keyboard_tap_sequence",
        "route": "us_sub_keyboard",
        "wrapper": "text_editor_startup_ime_off",
        "receiver": False,
        "startup": True,
        "ime_off": True,
        "tap_count": len(taps),
        "taps": taps,
        "tap_hold_sec": RECEIVER_TAP_HOLD_SEC,
        "tap_gap_sec": RECEIVER_TAP_GAP_SEC,
        "post_gap_sec": 0.050,
        "available": not blocking,
        "blocking_reasons": list(dict.fromkeys(blocking)),
        "loop_guard": {
            "synthetic_source": PTY_TERMINAL_SOURCE,
            "macro_recording_allowed": False,
            "interaction_input_allowed": False,
            "pty_input_routing_allowed": False,
        },
        "notes": [
            "Sends KC_LANG2 before PTY text so Windows IME starts in direct input mode.",
        ],
    }


def build_pty_terminal_text_plan(
    text: str,
    *,
    host_profile: str = DEFAULT_PTY_TERMINAL_HOST_PROFILE,
    source: str = PTY_TERMINAL_SOURCE,
    max_text_chars: int = DEFAULT_PTY_TERMINAL_MAX_TEXT_CHARS,
    chunk_index: int = 0,
    chunk_count: int = 1,
) -> dict[str, Any]:
    """Return a read-only tap plan for writing ANSI text through the receiver."""
    raw_text = str(text or "")
    safe_max = max(16, int(max_text_chars or DEFAULT_PTY_TERMINAL_MAX_TEXT_CHARS))
    host_profile = normalize_pty_terminal_host_profile(host_profile)
    if host_profile == WINDOWS_TEXT_EDITOR_PROFILE:
        output_text, stripped_reasons = strip_text_editor_terminal_sequences(raw_text)
        taps, tap_blocking = text_editor_tap_sequence(output_text)
        wrapper = "text_editor_direct_input"
        notes = [
            "Sends PTY output as plain text to the focused host text editor.",
            "Terminal control sequences are stripped because text editors do not interpret ANSI.",
        ]
    else:
        output_text, stripped_reasons = strip_unsupported_terminal_sequences(raw_text)
        taps, tap_blocking = terminal_text_tap_sequence(output_text)
        wrapper = "direct_hid_ansi"
        notes = [
            "Windows Terminal interprets ANSI sequences from the echo-off cat receiver output.",
            "M0 sends direct HID key sequences after the receiver bootstrap plan.",
        ]
    blocking: list[str] = []
    blocking.extend(tap_blocking)
    if source != PTY_TERMINAL_SOURCE:
        blocking.append("invalid_pty_terminal_source")
    if host_profile not in SUPPORTED_PTY_TERMINAL_HOST_PROFILES:
        blocking.append("unsupported_pty_terminal_host_profile")
    chunked = max(1, int(chunk_count)) > 1
    return {
        "schema": PTY_TERMINAL_TEXT_PLAN_SCHEMA,
        "read_only": True,
        "source": source,
        "host_profile": host_profile,
        "transport": "keyboard_tap_sequence",
        "route": "us_sub_keyboard",
        "wrapper": wrapper,
        "receiver": False,
        "text_length": len(output_text),
        "original_text_length": len(raw_text),
        "truncated": False,
        "max_text_chars": safe_max,
        "chunk_index": max(0, int(chunk_index)),
        "chunk_count": max(1, int(chunk_count)),
        "stripped_reasons": list(dict.fromkeys(stripped_reasons)),
        "tap_count": len(taps),
        "taps": taps,
        "tap_hold_sec": CHUNKED_OUTPUT_TAP_HOLD_SEC if chunked else DIRECT_OUTPUT_TAP_HOLD_SEC,
        "tap_gap_sec": CHUNKED_OUTPUT_TAP_GAP_SEC if chunked else DIRECT_OUTPUT_TAP_GAP_SEC,
        "post_gap_sec": CHUNKED_OUTPUT_POST_GAP_SEC if chunked else DIRECT_OUTPUT_TAP_GAP_SEC,
        "available": not blocking,
        "blocking_reasons": list(dict.fromkeys(blocking)),
        "loop_guard": {
            "synthetic_source": PTY_TERMINAL_SOURCE,
            "macro_recording_allowed": False,
            "interaction_input_allowed": False,
            "pty_input_routing_allowed": False,
        },
        "notes": notes,
    }


def _split_pty_terminal_text_chunks(raw_text: str, *, max_text_chars: int) -> list[str]:
    """Split text for HID pacing without separating CRLF terminal newlines."""
    if not raw_text:
        return [raw_text]
    safe_max = max(16, int(max_text_chars))
    chunks: list[str] = []
    start = 0
    while start < len(raw_text):
        end = min(start + safe_max, len(raw_text))
        if end < len(raw_text):
            if raw_text[end - 1] == "\r" and raw_text[end] == "\n":
                end += 1
            else:
                newline_end = raw_text.rfind("\n", start + 1, end + 1)
                if newline_end >= start and newline_end + 1 < len(raw_text):
                    candidate_end = newline_end + 1
                    if candidate_end - start >= safe_max // 2:
                        end = candidate_end
        chunks.append(raw_text[start:end])
        start = end
    return chunks


def build_pty_terminal_text_plans(
    text: str,
    *,
    host_profile: str = DEFAULT_PTY_TERMINAL_HOST_PROFILE,
    source: str = PTY_TERMINAL_SOURCE,
    max_text_chars: int = DEFAULT_PTY_TERMINAL_MAX_TEXT_CHARS,
) -> list[dict[str, Any]]:
    """Split PTY output into ordered HID plans without dropping output bytes."""
    raw_text = str(text or "")
    requested_max = max(16, int(max_text_chars or DEFAULT_PTY_TERMINAL_MAX_TEXT_CHARS))
    safe_max = requested_max
    if len(raw_text) > requested_max:
        safe_max = min(requested_max, CHUNKED_PTY_TERMINAL_MAX_TEXT_CHARS)
    if not raw_text:
        return [
            build_pty_terminal_text_plan(
                raw_text,
                host_profile=host_profile,
                source=source,
                max_text_chars=safe_max,
                chunk_index=0,
                chunk_count=1,
            )
        ]
    chunks = _split_pty_terminal_text_chunks(raw_text, max_text_chars=safe_max)
    chunk_count = len(chunks)
    return [
        build_pty_terminal_text_plan(
            chunk,
            host_profile=host_profile,
            source=source,
            max_text_chars=safe_max,
            chunk_index=index,
            chunk_count=chunk_count,
        )
        for index, chunk in enumerate(chunks)
    ]
