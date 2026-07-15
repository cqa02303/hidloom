"""Runtime setup helpers for logicd."""
from __future__ import annotations

import logging
import os


def setup_logging_from_env() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    handlers: list[logging.Handler] = []
    if os.environ.get("LOG_SYSLOG", "0") == "1":
        from logging.handlers import SysLogHandler

        syslog_h = SysLogHandler(address="/dev/log", facility=SysLogHandler.LOG_DAEMON)
        syslog_h.setFormatter(logging.Formatter("logicd[%(process)d]: %(levelname)s %(name)s: %(message)s"))
        handlers.append(syslog_h)

    if os.environ.get("LOG_SYSLOG", "0") != "1" or os.environ.get("LOG_STDERR", "0") == "1":
        stderr_h = logging.StreamHandler()
        stderr_h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        handlers.append(stderr_h)

    logging.basicConfig(level=level, handlers=handlers)
