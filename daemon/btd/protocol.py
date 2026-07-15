"""Protocol helpers for the btd daemon.

The legacy protocol accepts raw 8-byte keyboard HID reports.  A small framed
protocol is also supported for additional HID report kinds such as mouse.
"""
from __future__ import annotations

from dataclasses import dataclass

KEYBOARD_REPORT_SIZE = 8
MOUSE_REPORT_SIZE = 4
CONSUMER_REPORT_SIZE = 2
NULL_KEYBOARD_REPORT = bytes(KEYBOARD_REPORT_SIZE)
NULL_MOUSE_REPORT = bytes(MOUSE_REPORT_SIZE)
NULL_CONSUMER_REPORT = bytes(CONSUMER_REPORT_SIZE)
FRAME_MAGIC = b"btd1"
FRAME_TYPE_KEYBOARD = 1
FRAME_TYPE_MOUSE = 2
FRAME_TYPE_CONTROL = 3
FRAME_TYPE_CONSUMER = 4
FRAME_HEADER_SIZE = 6


@dataclass(frozen=True)
class KeyboardReport:
    """A keyboard HID report candidate received by btd."""

    report: bytes

    def __post_init__(self) -> None:
        if len(self.report) != KEYBOARD_REPORT_SIZE:
            raise ValueError(f"keyboard report must be {KEYBOARD_REPORT_SIZE} bytes, got {len(self.report)}")

    @property
    def is_null(self) -> bool:
        return self.report == NULL_KEYBOARD_REPORT

    @property
    def hex(self) -> str:
        return self.report.hex()


@dataclass(frozen=True)
class MouseReport:
    """A mouse HID report candidate received by btd."""

    report: bytes

    def __post_init__(self) -> None:
        if len(self.report) != MOUSE_REPORT_SIZE:
            raise ValueError(f"mouse report must be {MOUSE_REPORT_SIZE} bytes, got {len(self.report)}")

    @property
    def is_null(self) -> bool:
        return self.report == NULL_MOUSE_REPORT

    @property
    def hex(self) -> str:
        return self.report.hex()


@dataclass(frozen=True)
class ConsumerReport:
    """A Consumer Control HID report candidate received by btd."""

    report: bytes

    def __post_init__(self) -> None:
        if len(self.report) != CONSUMER_REPORT_SIZE:
            raise ValueError(f"consumer report must be {CONSUMER_REPORT_SIZE} bytes, got {len(self.report)}")

    @property
    def is_null(self) -> bool:
        return self.report == NULL_CONSUMER_REPORT

    @property
    def hex(self) -> str:
        return self.report.hex()


def parse_raw_keyboard_report(data: bytes) -> KeyboardReport:
    """Parse one raw 8-byte keyboard report."""
    return KeyboardReport(bytes(data))


def parse_raw_mouse_report(data: bytes) -> MouseReport:
    """Parse one raw 4-byte mouse report."""
    return MouseReport(bytes(data))


def parse_raw_consumer_report(data: bytes) -> ConsumerReport:
    """Parse one raw 2-byte Consumer Control report."""
    return ConsumerReport(bytes(data))


def encode_hid_frame(report: KeyboardReport | MouseReport | ConsumerReport) -> bytes:
    """Encode a framed HID report for the logicd -> btd socket."""
    if isinstance(report, KeyboardReport):
        report_type = FRAME_TYPE_KEYBOARD
    elif isinstance(report, MouseReport):
        report_type = FRAME_TYPE_MOUSE
    elif isinstance(report, ConsumerReport):
        report_type = FRAME_TYPE_CONSUMER
    else:
        raise TypeError(f"unsupported report type: {type(report).__name__}")
    return FRAME_MAGIC + bytes([report_type, len(report.report)]) + report.report


def null_keyboard_report() -> KeyboardReport:
    """Return a null keyboard report used for all-key-release."""
    return KeyboardReport(NULL_KEYBOARD_REPORT)


def null_mouse_report() -> MouseReport:
    """Return a null mouse report used for button-release / motion stop."""
    return MouseReport(NULL_MOUSE_REPORT)


def null_consumer_report() -> ConsumerReport:
    """Return a null Consumer Control report used for media-key release."""
    return ConsumerReport(NULL_CONSUMER_REPORT)
