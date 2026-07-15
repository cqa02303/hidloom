from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT / "daemon" / "http"))
sys.path.insert(0, str(ROOT))

from system_logs import LOG_ALLOWED_SERVICES, LOG_SERVICE_UNITS
from system_process import _match_process_statuses
from i2cd.status_display import daemon_status_icon_row
from logicd.daemon_status import DAEMON_STATUS_SERVICES


class HttpStatusDisplayTest(unittest.TestCase):
    def test_native_input_path_processes_are_reported(self) -> None:
        statuses = _match_process_statuses([
            "/usr/lib/hidloom/bin/hidloom-logicd-core --serve",
            "/usr/bin/python3 -S -m logicd.logicd",
            "/usr/lib/hidloom/bin/hidloom-outputd",
            "/usr/lib/hidloom/bin/hidloom-uidd",
            "/usr/lib/hidloom/bin/hidloom-hidd",
        ])

        self.assertTrue(statuses["logicd-core"])
        self.assertTrue(statuses["logicd-companion"])
        self.assertTrue(statuses["outputd"])
        self.assertTrue(statuses["uidd"])
        self.assertTrue(statuses["hidd"])

    def test_native_input_path_logs_are_allowlisted(self) -> None:
        for service in ("logicd-core", "logicd-companion", "outputd", "uidd", "hidd"):
            self.assertIn(service, LOG_ALLOWED_SERVICES)
            self.assertIn(service, LOG_SERVICE_UNITS)


class OledStatusDisplayTest(unittest.TestCase):
    def test_oled_daemon_status_includes_native_input_path(self) -> None:
        for service in ("logicd-core", "logicd-companion", "outputd", "uidd", "hidd"):
            self.assertIn(service, DAEMON_STATUS_SERVICES)

    def test_oled_daemon_status_row_accepts_native_input_path(self) -> None:
        row = daemon_status_icon_row({
            "matrixd": True,
            "logicd-core": True,
            "logicd-companion": True,
            "outputd": True,
            "uidd": True,
            "hidd": True,
        })

        self.assertIn(("core", True), row)
        self.assertIn(("cmp", True), row)
        self.assertIn(("out", True), row)
        self.assertIn(("uid", True), row)
        self.assertIn(("hid", True), row)


if __name__ == "__main__":
    unittest.main()
