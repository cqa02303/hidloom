"""
HID keyboard usage codes (USB HID Usage Page 0x07) and 8-byte report builder.

Report format: [Modifier, Reserved=0x00, Key1, Key2, Key3, Key4, Key5, Key6]
Modifier bits: bit0=LCtrl bit1=LShift bit2=LAlt bit3=LWin
               bit4=RCtrl bit5=RShift bit6=RAlt bit7=RWin

Consumer Control (USB HID Usage Page 0x0C) report: 2-byte little-endian Usage ID
  Send Usage ID on press, 0x0000 on release.
"""
from __future__ import annotations

import os
import struct
from typing import Dict, List

HID_REPORT_ID_KEYBOARD = 0x01
HID_REPORT_ID_MOUSE = 0x02
HID_REPORT_ID_CONSUMER = 0x03


def add_hid_report_id(report_id: int, payload: bytes) -> bytes:
    """Prefix a HID payload with its multi-report Report ID."""
    if report_id < 1 or report_id > 255:
        raise ValueError(f"invalid HID report ID: {report_id}")
    return bytes([report_id]) + bytes(payload)

# ---------------------------------------------------------------------------
# Modifier bit masks  (HID レポートの modifier byte ビットフラグ定数)
# HID modifier keycode 0xE0-0xE7 とビットフラグの対応:
#   keycode 0xE0 (LCtrl)  → bit 1<<0 = 0x01  = MOD_LCTRL
#   keycode 0xE1 (LShift) → bit 1<<1 = 0x02  = MOD_LSHIFT
#   keycode 0xE2 (LAlt)   → bit 1<<2 = 0x04  = MOD_LALT
#   keycode 0xE3 (LWin)   → bit 1<<3 = 0x08  = MOD_LWIN
#   keycode 0xE4 (RCtrl)  → bit 1<<4 = 0x10  = MOD_RCTRL
#   keycode 0xE5 (RShift) → bit 1<<5 = 0x20  = MOD_RSHIFT
#   keycode 0xE6 (RAlt)   → bit 1<<6 = 0x40  = MOD_RALT
#   keycode 0xE7 (RWin)   → bit 1<<7 = 0x80  = MOD_RWIN
# 算術式: bit = 1 << (hid_keycode - 0xE0)
# ---------------------------------------------------------------------------
MOD_LCTRL  = 0x01
MOD_LSHIFT = 0x02
MOD_LALT   = 0x04
MOD_LWIN   = 0x08
MOD_RCTRL  = 0x10
MOD_RSHIFT = 0x20
MOD_RALT   = 0x40
MOD_RWIN   = 0x80

# ---------------------------------------------------------------------------
# HID keycode table — config/default/keycodes.json から動的にロード
# ---------------------------------------------------------------------------
import json as _json
import pathlib as _pathlib
from hidloom_paths import default_config_file as _default_config_file, runtime_file as _runtime_file

_KEYCODES_SEARCH_PATHS = [
    str(_runtime_file("keycodes.json")),
    str(_default_config_file("keycodes.json")),
]

def _load_keycodes_all() -> "tuple[Dict[str, int], Dict[int, int], Dict[str, int], Dict[int, int]]":
    """keycodes.json を1回読み、(KEYCODE, HID_TO_LINUX, CONSUMER_KEYCODE, HID_CONSUMER_TO_LINUX) を返す。"""
    for _p in _KEYCODES_SEARCH_PATHS:
        if _pathlib.Path(_p).exists():
            raw = _json.loads(_pathlib.Path(_p).read_text(encoding="utf-8"))
            kc: Dict[str, int] = {}    # keyboard keycodes (page 0x07)
            h2l: Dict[int, int] = {}   # hid → linux (keyboard)
            ckc: Dict[str, int] = {}   # consumer keycodes (page 0x0C)
            ch2l: Dict[int, int] = {}  # hid → linux (consumer)
            for k, v in raw.items():
                if k.startswith("_"):
                    continue
                if isinstance(v, dict):
                    hid = int(v["hid"])
                    linux = v.get("linux")
                    if v.get("page") == "consumer":
                        ckc[k] = hid
                        if linux is not None:
                            ch2l[hid] = int(linux)
                    else:
                        kc[k] = hid
                        if linux is not None:
                            h2l[hid] = int(linux)
                elif isinstance(v, (int, float)):  # 旧フォーマット互換
                    kc[k] = int(v)
            return kc, h2l, ckc, ch2l
    raise FileNotFoundError(f"keycodes.json not found in {_KEYCODES_SEARCH_PATHS}")


KEYCODE, HID_TO_LINUX, CONSUMER_KEYCODE, HID_CONSUMER_TO_LINUX = _load_keycodes_all()

# HID modifier byte のビットフラグ → Linux input event code
# keycodes.json の modifier エントリ (hid 0xE0-0xE7) から算術導出:
#   ビットフラグ = 1 << (hid_keycode - 0xE0)
# HidState.press() も同式で keycode → modifier bit を計算するため一貫している
MODIFIER_BIT_TO_LINUX: Dict[int, int] = {
    1 << (hid - 0xE0): linux
    for hid, linux in HID_TO_LINUX.items()
    if 0xE0 <= hid <= 0xE7
}


_MOD_MIN = 0xE0
_MOD_MAX = 0xE7
_MOUSE_MIN = 0x200  # マウス/ホイール系コードの下限 (キーボードレポートでは無視)


def _is_modifier(code: int) -> bool:
    return _MOD_MIN <= code <= _MOD_MAX


def _is_keyboard_key(code: int) -> bool:
    """キーボード HID レポートに含めるべき通常キーかどうかを判定する。"""
    return 0 < code < _MOD_MIN and code < _MOUSE_MIN


class HidState:
    """Tracks pressed keys and builds 8-byte HID keyboard reports."""

    def __init__(self) -> None:
        self._mod = 0
        self._keys: List[int] = []

    def press(self, code: int) -> None:
        if code == 0:
            return
        if _is_modifier(code):
            # modifier keycode 0xE0-0xE7 → modifier byte のビット位置
            # bit = 1 << (code - 0xE0)  ← MOD_LCTRL 等の定数と同じ算術関係
            self._mod |= 1 << (code - _MOD_MIN)
        elif _is_keyboard_key(code) and code not in self._keys and len(self._keys) < 6:
            self._keys.append(code)
        # マウス/ホイール系 (code >= _MOUSE_MIN) はキーボードレポートでは無視

    def release(self, code: int) -> None:
        if code == 0:
            return
        if _is_modifier(code):
            self._mod &= ~(1 << (code - _MOD_MIN)) & 0xFF
        elif _is_keyboard_key(code) and code in self._keys:
            self._keys.remove(code)

    def set_mod_bits(self, bits: int) -> None:
        self._mod |= bits

    def clear_mod_bits(self, bits: int) -> None:
        self._mod &= ~bits & 0xFF

    @property
    def mod(self) -> int:
        """現在のモディファイアビットを取得する。"""
        return self._mod

    def release_all(self) -> None:
        self._mod = 0
        self._keys.clear()

    def build(self) -> bytes:
        keys = (self._keys + [0, 0, 0, 0, 0, 0])[:6]
        return bytes([self._mod, 0x00] + keys)

    def write(self, fd: int) -> None:
        """Write 8-byte report to /dev/hidg0 file descriptor."""
        try:
            os.write(fd, self.build())
        except OSError:
            pass

    @staticmethod
    def null_report() -> bytes:
        return bytes(8)


# ---------------------------------------------------------------------------
# マウス HID レポートビルダー (6バイト)
# レポート形式: [buttons(1B), X(1B signed), Y(1B signed), Wheel(1B signed), pad(2B)]
# ---------------------------------------------------------------------------

# マウスコード定数 (keycodes.json の値と対応)
MOUSE_BTN1 = 0x200
MOUSE_BTN2 = 0x201
MOUSE_BTN3 = 0x202
MOUSE_BTN4 = 0x203
MOUSE_BTN5 = 0x204
MOUSE_MS_U = 0x208  # カーソル上
MOUSE_MS_D = 0x209  # カーソル下
MOUSE_MS_L = 0x20A  # カーソル左
MOUSE_MS_R = 0x20B  # カーソル右
MOUSE_WH_U = 0x20C  # ホイール上
MOUSE_WH_D = 0x20D  # ホイール下
MOUSE_WH_L = 0x20E  # ホイール左
MOUSE_WH_R = 0x20F  # ホイール右
MOUSE_ACL0 = 0x210  # 低速 profile
MOUSE_ACL1 = 0x211  # 標準 profile
MOUSE_ACL2 = 0x212  # 高速 profile

# カーソル移動量 (1回のイベントで移動するピクセル数)
MOUSE_MOVE_STEP  = 5
MOUSE_WHEEL_STEP = 3


def _is_mouse_code(code: int) -> bool:
    return code >= _MOUSE_MIN


class MouseState:
    """マウスボタン状態を管理し、6バイトの HID マウスレポートを生成する。"""

    def __init__(self) -> None:
        self._buttons = 0  # ビットマスク: bit0=BTN1, bit1=BTN2, bit2=BTN3, ...

    @property
    def buttons(self) -> int:
        return self._buttons & 0xFF

    def press(self, code: int) -> None:
        btn_bit = self._btn_bit(code)
        if btn_bit is not None:
            self._buttons |= btn_bit

    def release(self, code: int) -> None:
        btn_bit = self._btn_bit(code)
        if btn_bit is not None:
            self._buttons &= ~btn_bit & 0xFF

    def build_move(self, dx: int = 0, dy: int = 0, dw: int = 0) -> bytes:
        """移動イベント用レポートを生成する。dx/dy/dw は -127〜127。"""
        dx = max(-127, min(127, dx))
        dy = max(-127, min(127, dy))
        dw = max(-127, min(127, dw))
        return bytes([
            self._buttons & 0xFF,
            dx & 0xFF,
            dy & 0xFF,
            dw & 0xFF,
        ])

    def null_report(self) -> bytes:
        """ボタン状態を保持したまま移動なしのレポートを生成する。"""
        return self.build_move()

    @staticmethod
    def merge_buttons(report: bytes, buttons: int) -> bytes:
        """Return a mouse report with additional held button bits preserved."""
        if not report:
            return report
        merged = bytearray(report)
        merged[0] = (int(merged[0]) | int(buttons)) & 0xFF
        return bytes(merged)

    @staticmethod
    def _btn_bit(code: int):
        if code == MOUSE_BTN1:
            return 0x01
        if code == MOUSE_BTN2:
            return 0x02
        if code == MOUSE_BTN3:
            return 0x04
        if code == MOUSE_BTN4:
            return 0x08
        if code == MOUSE_BTN5:
            return 0x10
        return None

    @staticmethod
    def move_delta(code: int, move_step: int = MOUSE_MOVE_STEP, wheel_step: int = MOUSE_WHEEL_STEP):
        """移動コードから (dx, dy, dwheel) を返す。移動コードでなければ None。"""
        if code == MOUSE_MS_U: return (0, -move_step, 0)
        if code == MOUSE_MS_D: return (0,  move_step, 0)
        if code == MOUSE_MS_L: return (-move_step, 0, 0)
        if code == MOUSE_MS_R: return ( move_step, 0, 0)
        if code == MOUSE_WH_U: return (0, 0,  wheel_step)
        if code == MOUSE_WH_D: return (0, 0, -wheel_step)
        if code == MOUSE_WH_L: return (0, 0, -wheel_step)
        if code == MOUSE_WH_R: return (0, 0,  wheel_step)
        return None


# ---------------------------------------------------------------------------
# Consumer Control HID レポートビルダー (2バイト)
# レポート形式: 16bit little-endian Consumer Control Usage ID
#   press:   send Usage ID (e.g. 0x00E2 for Mute)
#   release: send 0x0000
# ---------------------------------------------------------------------------

class HidConsumerState:
    """Consumer Control 2-byte HID report builder.

    USB HID Usage Page 0x0C (Consumer Devices).
    """

    def __init__(self) -> None:
        self._usage: int = 0

    def press(self, usage_id: int) -> None:
        self._usage = usage_id & 0xFFFF

    def release(self) -> None:
        self._usage = 0

    def build(self) -> bytes:
        return struct.pack('<H', self._usage)

    def write(self, fd: int) -> None:
        """Write 2-byte Consumer Control report to a HID file descriptor."""
        try:
            os.write(fd, self.build())
        except OSError:
            pass

    @staticmethod
    def null_report() -> bytes:
        return bytes(2)
