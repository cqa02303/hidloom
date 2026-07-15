"""Bluetooth pairing passkey input state for logicd."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PAIRING_PASSKEY_FILE = "/tmp/btd_pairing_passkey.txt"

_DIGIT_ACTIONS = {
    "KC_1": "1",
    "KC_2": "2",
    "KC_3": "3",
    "KC_4": "4",
    "KC_5": "5",
    "KC_6": "6",
    "KC_7": "7",
    "KC_8": "8",
    "KC_9": "9",
    "KC_0": "0",
}
_ENTER_ACTIONS = {"KC_ENT", "KC_ENTER", "KC_RETURN"}
_BACKSPACE_ACTIONS = {"KC_BSPC", "KC_BACKSPACE"}
_CANCEL_ACTIONS = {"KC_ESC", "KC_ESCAPE"}


@dataclass(frozen=True)
class BtPasskeyActionResult:
    consumed: bool = False
    phase: str = ""
    digits: str = ""
    submitted: bool = False
    canceled: bool = False


@dataclass
class BtPasskeyInput:
    passkey_file: str = DEFAULT_PAIRING_PASSKEY_FILE
    max_digits: int = 6
    manual_input_enabled: bool = True
    active: bool = False
    digits: str = ""

    def begin(self) -> BtPasskeyActionResult:
        self.digits = ""
        self.active = bool(self.manual_input_enabled)
        return BtPasskeyActionResult(consumed=False, phase="pairing", digits="")

    def cancel(self) -> BtPasskeyActionResult:
        self.active = False
        self.digits = ""
        return BtPasskeyActionResult(consumed=True, phase="off", digits="", canceled=True)

    def handle_action(self, action: str, is_press: bool) -> BtPasskeyActionResult:
        if not self.active:
            return BtPasskeyActionResult()
        if action.startswith("BT_"):
            return BtPasskeyActionResult()
        if not is_press:
            if self._is_passkey_key(action):
                return BtPasskeyActionResult(consumed=True, phase="passkey", digits=self.digits)
            return BtPasskeyActionResult()

        digit = _DIGIT_ACTIONS.get(action)
        if digit is not None:
            if len(self.digits) < self.max_digits:
                self.digits += digit
            return BtPasskeyActionResult(consumed=True, phase="passkey", digits=self.digits)
        if action in _BACKSPACE_ACTIONS:
            self.digits = self.digits[:-1]
            return BtPasskeyActionResult(consumed=True, phase="passkey", digits=self.digits)
        if action in _CANCEL_ACTIONS:
            return self.cancel()
        if action in _ENTER_ACTIONS:
            if self.digits:
                self._write_passkey()
                submitted_digits = self.digits
                self.active = False
                self.digits = ""
                return BtPasskeyActionResult(
                    consumed=True,
                    phase="submitted",
                    digits=submitted_digits,
                    submitted=True,
                )
            return BtPasskeyActionResult(consumed=True, phase="passkey", digits=self.digits)
        return BtPasskeyActionResult()

    def _write_passkey(self) -> None:
        path = Path(self.passkey_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.digits)

    @staticmethod
    def _is_passkey_key(action: str) -> bool:
        return (
            action in _DIGIT_ACTIONS
            or action in _ENTER_ACTIONS
            or action in _BACKSPACE_ACTIONS
            or action in _CANCEL_ACTIONS
        )


def build_bt_passkey_input() -> BtPasskeyInput:
    raw_enabled = os.environ.get("BT_PAIRING_PASSKEY_INPUT", "0").strip().lower()
    manual_input_enabled = raw_enabled in {"1", "true", "yes", "on"}
    return BtPasskeyInput(
        passkey_file=os.environ.get("BTD_PAIRING_PASSKEY_FILE", DEFAULT_PAIRING_PASSKEY_FILE),
        manual_input_enabled=manual_input_enabled,
    )
