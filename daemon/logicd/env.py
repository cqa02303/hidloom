"""Environment parsing helpers for logicd."""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)


def env_int(name: str, default: int, *, min_value: int | None = None, max_value: int | None = None) -> int:
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


def env_float(name: str, default: float, *, min_value: float | None = None) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        log.warning("invalid %s=%r; using default %.3f", name, raw, default)
        return default
    if min_value is not None and value < min_value:
        log.warning("invalid %s=%.3f below minimum %.3f; using default %.3f", name, value, min_value, default)
        return default
    return value
