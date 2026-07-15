from __future__ import annotations

import os
import socket
import tempfile
import unittest

from logicd.native_outputd import create_outputd_report_writer
from usbd.hid_report_broker import KIND_MOUSE, decode_hid_report_request


class NativeOutputdReportWriterTest(unittest.TestCase):
    def test_writer_sends_mouse_frame_to_outputd_socket(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "reports.sock")
            server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            try:
                server.bind(socket_path)
                server.settimeout(1)

                writer = create_outputd_report_writer(KIND_MOUSE, socket_path=socket_path)
                try:
                    writer(bytes([0x00, 0x04, 0xFE, 0x00]))
                finally:
                    writer.close()

                frame = server.recv(64)
            finally:
                server.close()

        request = decode_hid_report_request(frame)
        self.assertEqual(request.kind, KIND_MOUSE)
        self.assertEqual(request.payload, bytes([0x00, 0x04, 0xFE, 0x00]))


if __name__ == "__main__":
    unittest.main()
