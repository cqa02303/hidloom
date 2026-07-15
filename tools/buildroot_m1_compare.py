#!/usr/bin/env python3
"""Render a compact Raspberry Pi OS vs Buildroot M1 boot comparison."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re


UNIT_ROW_RE = re.compile(
    r"^\|\s*(?P<unit>[^|]+?)\s*\|\s*(?P<active>[^|]+?)\s*\|\s*(?P<sub>[^|]+?)\s*\|"
    r"\s*(?P<exec>[0-9.]+)?\s*\|\s*(?P<enter>[0-9.]+)?\s*\|$"
)
USB_EVENT_RE = re.compile(r"\[\+(?P<seconds>[0-9.]+)s\]\s*(?P<line>.+)")

KEY_UNITS = (
    ("usb gadget active", "hidloom-usb-gadget.service"),
    ("hidd active", "hidloom-hidd.service"),
    ("logicd-core active", "hidloom-logicd-core.service"),
    ("matrixd active", "matrixd.service"),
    ("ledd active", "ledd.service"),
    ("logicd-companion active", "logicd-companion.service"),
    ("viald active", "viald.service"),
    ("httpd active", "httpd.service"),
)


@dataclass(frozen=True)
class UnitTiming:
    unit: str
    active: str
    sub: str
    exec_start_sec: float | None
    active_enter_sec: float | None


def _float_or_none(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_unit_timings(text: str) -> dict[str, UnitTiming]:
    timings: dict[str, UnitTiming] = {}
    for line in text.splitlines():
        match = UNIT_ROW_RE.match(line.strip())
        if match is None:
            continue
        unit = match.group("unit").strip()
        if unit == "unit":
            continue
        timings[unit] = UnitTiming(
            unit=unit,
            active=match.group("active").strip(),
            sub=match.group("sub").strip(),
            exec_start_sec=_float_or_none(match.group("exec")),
            active_enter_sec=_float_or_none(match.group("enter")),
        )
    return timings


def parse_usb_first_event_sec(text: str) -> float | None:
    candidates: list[float] = []
    for match in USB_EVENT_RE.finditer(text):
        line = match.group("line").lower()
        if any(token in line for token in ("hid", "usb", "cqa02303v5", "1d6b:0105")):
            candidates.append(float(match.group("seconds")))
    return min(candidates) if candidates else None


def format_seconds(value: float | None) -> str:
    return "" if value is None else f"{value:.3f}"


def render_report(
    *,
    rpi_os_text: str,
    m1_boot_text: str | None,
    m1_usb_text: str | None,
    rpi_os_label: str,
    m1_label: str,
) -> str:
    rpi = parse_unit_timings(rpi_os_text)
    m1 = parse_unit_timings(m1_boot_text or "")
    usb_enum = parse_usb_first_event_sec(m1_usb_text or "") if m1_usb_text is not None else None
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    lines = [
        "# Buildroot M1 Boot Comparison",
        "",
        f"- collected_at: `{now}`",
        f"- rpi_os_label: `{rpi_os_label}`",
        f"- m1_label: `{m1_label}`",
        "",
        "## Key Markers",
        "",
        "| marker | Raspberry Pi OS sec | Buildroot M1 sec | delta sec |",
        "| --- | ---: | ---: | ---: |",
    ]
    for marker, unit in KEY_UNITS:
        rpi_sec = rpi.get(unit).active_enter_sec if unit in rpi else None
        m1_sec = m1.get(unit).active_enter_sec if unit in m1 else None
        delta = None if rpi_sec is None or m1_sec is None else m1_sec - rpi_sec
        lines.append(f"| {marker} | {format_seconds(rpi_sec)} | {format_seconds(m1_sec)} | {format_seconds(delta)} |")

    lines.extend(
        [
            f"| host USB first matching event |  | {format_seconds(usb_enum)} |  |",
            "",
            "## Notes",
            "",
            "- Empty Buildroot M1 cells mean the M1 report did not contain the corresponding systemd unit marker.",
            "- `host USB first matching event` is the earliest `+seconds` line in the USB watch report mentioning USB/HID/HIDloom.",
            "- For M1/M2, USB enumerate and `/dev/hidg0` readiness are more important than full system startup.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpi-os", required=True, type=Path, help="Raspberry Pi OS boot_marker_baseline report")
    parser.add_argument("--m1-boot", type=Path, help="Buildroot M1 boot_marker_baseline report, if available")
    parser.add_argument("--m1-usb-watch", type=Path, help="Buildroot M1 usb_enumeration_watch report, if available")
    parser.add_argument("--rpi-os-label", default="<keyboard-host> native owner")
    parser.add_argument("--m1-label", default="Buildroot M1")
    parser.add_argument("--output", type=Path, help="write Markdown report to this path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rpi_os_text = args.rpi_os.read_text(encoding="utf-8")
    m1_boot_text = args.m1_boot.read_text(encoding="utf-8") if args.m1_boot else None
    m1_usb_text = args.m1_usb_watch.read_text(encoding="utf-8") if args.m1_usb_watch else None
    report = render_report(
        rpi_os_text=rpi_os_text,
        m1_boot_text=m1_boot_text,
        m1_usb_text=m1_usb_text,
        rpi_os_label=args.rpi_os_label,
        m1_label=args.m1_label,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report + "\n", encoding="utf-8")
        print(args.output)
    else:
        print(report)


if __name__ == "__main__":
    main()
