from __future__ import annotations

import unittest

from logicd.output_router import (
    BluetoothHidOutputBackend,
    CallableOutputBackend,
    DebugOutputBackend,
    OutputRouter,
    parse_output_targets,
)


class OutputRouterTest(unittest.TestCase):
    def test_parse_output_targets_accepts_comma_plus_space_and_aliases(self) -> None:
        self.assertEqual(
            parse_output_targets("gadget,uinput+bt debug log dummy"),
            ("gadget", "uinput", "bt", "debug"),
        )

    def test_router_fans_out_to_all_enabled_targets(self) -> None:
        calls: list[tuple[str, bytes]] = []

        router = OutputRouter()
        router.register(CallableOutputBackend("gadget", lambda report: calls.append(("gadget", report))))
        router.register(CallableOutputBackend("uinput", lambda report: calls.append(("uinput", report))))
        router.set_targets(("gadget", "uinput"))

        report = bytes([0x00, 0x00, 0x04, 0, 0, 0, 0, 0])
        result = router.send(report)

        self.assertEqual(result, {"gadget": True, "uinput": True})
        self.assertEqual(calls, [("gadget", report), ("uinput", report)])

    def test_router_can_disable_one_backend_without_changing_others(self) -> None:
        calls: list[str] = []

        router = OutputRouter()
        router.register(CallableOutputBackend("gadget", lambda report: calls.append("gadget")))
        router.register(CallableOutputBackend("debug", lambda report: calls.append("debug")))
        router.set_targets(("gadget", "debug"))

        self.assertTrue(router.set_enabled("debug", False))
        router.write(bytes(8))

        self.assertEqual(router.enabled_names(), ("gadget",))
        self.assertEqual(calls, ["gadget"])

    def test_one_backend_failure_does_not_stop_other_backends(self) -> None:
        calls: list[str] = []

        def broken(report: bytes) -> None:
            raise RuntimeError("boom")

        router = OutputRouter()
        router.register(CallableOutputBackend("broken", broken))
        router.register(CallableOutputBackend("debug", lambda report: calls.append("debug")))
        router.set_targets(("broken", "debug"))

        result = router.send(bytes(8))

        self.assertEqual(result, {"broken": False, "debug": True})
        self.assertEqual(calls, ["debug"])

    def test_bt_backend_without_sender_is_safe_noop(self) -> None:
        backend = BluetoothHidOutputBackend(enabled=True)
        backend.write(bytes(8))
        self.assertTrue(backend.enabled)

    def test_bt_backend_uses_sender_when_configured(self) -> None:
        sent: list[bytes] = []
        report = bytes([0x00, 0x00, 0x04, 0, 0, 0, 0, 0])
        backend = BluetoothHidOutputBackend(sender=sent.append, enabled=True)

        backend.write(report)

        self.assertEqual(sent, [report])

    def test_debug_backend_has_common_interface(self) -> None:
        backend = DebugOutputBackend(enabled=True)
        backend.check()
        backend.set_enabled(False)
        backend.write(bytes(8))
        self.assertFalse(backend.enabled)


if __name__ == "__main__":
    unittest.main()
