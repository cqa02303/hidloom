from __future__ import annotations

import unittest

from logicd.joystick import JoystickBinding, JoystickManager, _scaled


def _resolver(row: int, col: int) -> str:
    actions = {
        (0, 0): "KC_MS_U",
        (1, 1): "KC_MS_L",
        (2, 2): "KC_MS_R",
        (3, 3): "KC_MS_D",
    }
    return actions[(row, col)]


def _legacy_resolver(row: int, col: int) -> str:
    actions = {
        (0, 0): "MS_UP",
        (1, 1): "MS_LEFT",
        (2, 2): "MS_RGHT",
        (3, 3): "MS_DOWN",
    }
    return actions[(row, col)]


class JoystickMouseAccelerationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.binding = JoystickBinding(
            name="stick0",
            up=(0, 0),
            left=(1, 1),
            right=(2, 2),
            down=(3, 3),
            mouse_deadzone=12,
            cursor_max=12,
        )

    def test_cursor_speed_reaches_double_legacy_scale_near_max(self) -> None:
        manager = JoystickManager([self.binding])
        result = manager.process(0, 100, 0, _resolver)

        self.assertIsNotNone(result.mouse_event)
        self.assertEqual(result.mouse_event.dx, _scaled(100, 12, 12) * 2)
        self.assertEqual(result.mouse_event.dy, 0)

    def test_cursor_speed_is_softer_around_mid_throw(self) -> None:
        manager = JoystickManager([self.binding])
        result = manager.process(0, 60, 0, _resolver)

        self.assertIsNotNone(result.mouse_event)
        self.assertEqual(result.mouse_event.dx, 7)
        self.assertLess(result.mouse_event.dx, 9)

    def test_deadzone_stays_still(self) -> None:
        manager = JoystickManager([self.binding])
        result = manager.process(0, 12, 0, _resolver)

        self.assertIsNone(result.mouse_event)

    def test_legacy_mouse_aliases_are_accepted_for_analog_motion(self) -> None:
        manager = JoystickManager([self.binding])
        result = manager.process(0, 100, 0, _legacy_resolver)

        self.assertIsNotNone(result.mouse_event)
        self.assertEqual(result.mouse_event.dx, 24)
        self.assertEqual(result.key_events, [])


if __name__ == "__main__":
    unittest.main()
