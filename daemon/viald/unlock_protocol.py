"""Vial unlock command handlers."""

from __future__ import annotations

import logging
import os

from .protocol_defs import REPORT_SIZE, UNLOCK_COUNTER_MAX

log = logging.getLogger(__name__)


def _pad(payload: bytes) -> bytes:
    return payload[:REPORT_SIZE].ljust(REPORT_SIZE, b"\x00")


class VialUnlockMixin:
    def _load_unlock_keys(self) -> list[tuple[int, int]]:
        raw = os.environ.get("VIALD_UNLOCK_KEYS")
        if raw:
            items: list[object] = []
            for part in raw.split(";"):
                if not part.strip():
                    continue
                try:
                    row_s, col_s = part.split(",", 1)
                except ValueError:
                    log.warning("unlock key ignored: malformed VIALD_UNLOCK_KEYS entry %r", part)
                    continue
                items.append([row_s, col_s])
        else:
            vial = self._definition.get("vial", {})
            items = []
            if isinstance(vial, dict):
                for key in ("unlockKeys", "unlock_keys", "unlockCombo", "unlock_combo"):
                    candidate = vial.get(key)
                    if candidate is not None:
                        items = candidate
                        break

        keys: list[tuple[int, int]] = []
        if not isinstance(items, list):
            log.warning("unlock keys ignored: expected list, got %r", items)
            return keys
        for item in items[:15]:
            try:
                row, col = int(item[0]), int(item[1])
            except (TypeError, ValueError, IndexError):
                log.warning("unlock key ignored: malformed item %r", item)
                continue
            if not (0 <= row < self.rows and 0 <= col < self.cols):
                log.warning("unlock key ignored: out-of-range row=%d col=%d", row, col)
                continue
            keys.append((row, col))
        if len(items) > 15:
            log.warning("unlock keys truncated: count=%d max=15", len(items))
        if keys:
            log.info("Vial unlock keys configured: %s", keys)
        return keys
    def _get_unlock_status(self) -> bytes:
        payload = bytearray(b"\xff" * REPORT_SIZE)
        payload[0] = 1 if self.unlocked else 0
        payload[1] = 1 if self.unlock_in_progress else 0
        for idx, (row, col) in enumerate(self.unlock_keys[:15]):
            payload[2 + idx * 2] = row
            payload[3 + idx * 2] = col
        return bytes(payload)
    def _unlock_start(self) -> bytes:
        if not self.unlock_keys:
            self.unlocked = True
            return bytes(REPORT_SIZE)
        self.unlock_in_progress = True
        self.unlock_counter = max(1, min(255, UNLOCK_COUNTER_MAX))
        log.info("Vial unlock started: keys=%s counter=%d", self.unlock_keys, self.unlock_counter)
        return bytes(REPORT_SIZE)
    def _unlock_poll(self) -> bytes:
        if not self.unlock_keys:
            self.unlocked = True
            return _pad(bytes([1, 0, 0]))

        if self.unlock_in_progress and not self.unlocked:
            if self._unlock_keys_are_pressed():
                self.unlock_counter = max(0, self.unlock_counter - 1)
                if self.unlock_counter == 0:
                    self.unlocked = True
                    self.unlock_in_progress = False
                    log.info("Vial unlocked")
            else:
                self.unlock_counter = max(1, min(255, UNLOCK_COUNTER_MAX))

        return _pad(bytes([
            1 if self.unlocked else 0,
            1 if self.unlock_in_progress else 0,
            max(0, min(255, self.unlock_counter)),
        ]))
    def _lock(self) -> bytes:
        if self.unlock_keys:
            self.unlocked = False
        self.unlock_in_progress = False
        self.unlock_counter = 0
        log.info("Vial locked")
        return bytes(REPORT_SIZE)
    def _unlock_keys_are_pressed(self) -> bool:
        result = self._send_logicd_message({"t": "K"})
        pressed = result.get("pressed", []) if isinstance(result, dict) else []
        if not isinstance(pressed, list):
            log.warning("unlock poll ignored: malformed pressed field %r", pressed)
            return False
        pressed_set: set[tuple[int, int]] = set()
        for item in pressed:
            try:
                pressed_set.add((int(item[0]), int(item[1])))
            except (TypeError, ValueError, IndexError):
                log.warning("unlock poll ignored: malformed pressed item %r", item)
        return all(key in pressed_set for key in self.unlock_keys)
