"""Runtime settings for logicd spid motion handling.

This module keeps spid mode selection small and testable.  It does not open
sockets and does not know SPI details.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

VALID_SPID_MODES = {"mouse", "direction"}


@dataclass(frozen=True)
class SpidRuntimeSettings:
    """Settings controlling how logicd consumes spi_events motion."""

    mode: str = "mouse"
    binding: Any | None = None
    tap_hold_sec: float = 0.010
    tap_gap_sec: float = 0.0


def _coord(value: Any, default: tuple[int, int]) -> tuple[int, int]:
    if value is None:
        return default
    if isinstance(value, str):
        parts = value.split(",")
        if len(parts) != 2:
            raise ValueError(f"invalid coordinate string: {value!r}")
        return (int(parts[0]), int(parts[1]))
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return (int(value[0]), int(value[1]))
    raise ValueError(f"invalid coordinate: {value!r}")


def spid_settings_from_config(cfg: dict[str, Any]) -> SpidRuntimeSettings:
    """Build spid runtime settings from config and environment.

    Config shape:

    ```json
    {
      "settings": {
        "spid": {
          "mode": "mouse",
          "direction": {
            "name": "ball",
            "up": [1, 0],
            "down": [1, 1],
            "left": [1, 2],
            "right": [1, 3],
            "threshold": 24,
            "max_taps_per_flush": 4,
            "tap_hold_sec": 0.010,
            "tap_gap_sec": 0.0
          }
        }
      }
    }
    ```

    Environment overrides:
    - `LOGICD_SPID_MODE=mouse|direction`
    """
    settings = cfg.get("settings", {}) if isinstance(cfg, dict) else {}
    spid = settings.get("spid", {}) if isinstance(settings, dict) else {}
    if not isinstance(spid, dict):
        spid = {}

    mode = str(os.environ.get("LOGICD_SPID_MODE") or spid.get("mode") or "mouse").strip().lower()
    if mode not in VALID_SPID_MODES:
        raise ValueError(f"invalid settings.spid.mode: {mode!r}; expected one of {sorted(VALID_SPID_MODES)}")

    direction_cfg = spid.get("direction", {}) if isinstance(spid, dict) else {}
    if not isinstance(direction_cfg, dict):
        direction_cfg = {}

    binding = None
    if mode == "direction":
        from .spid_direction import SpidDirectionBinding

        binding = SpidDirectionBinding(
            name=str(direction_cfg.get("name") or "spid"),
            up=_coord(direction_cfg.get("up"), (1, 0)),
            down=_coord(direction_cfg.get("down"), (1, 1)),
            left=_coord(direction_cfg.get("left"), (1, 2)),
            right=_coord(direction_cfg.get("right"), (1, 3)),
            threshold=int(direction_cfg.get("threshold", 24)),
            max_taps_per_flush=int(direction_cfg.get("max_taps_per_flush", 4)),
        )
    return SpidRuntimeSettings(
        mode=mode,
        binding=binding,
        tap_hold_sec=float(direction_cfg.get("tap_hold_sec", 0.010)),
        tap_gap_sec=float(direction_cfg.get("tap_gap_sec", 0.0)),
    )
