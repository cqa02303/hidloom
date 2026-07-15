#!/usr/bin/env python3
"""Smoke-test KC_SH opt-in report metadata helpers."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.script_report import parse_script_report_metadata, sanitize_report_text  # noqa: E402


def main() -> None:
    default = parse_script_report_metadata("#!/bin/sh\necho hidden\n")
    assert not default.enabled
    assert default.sinks == ()
    assert default.max_bytes == 2048
    assert default.ansi == "strip"

    meta = parse_script_report_metadata(
        "#!/bin/sh\n"
        "# @report hid_text\n"
        "# @report debug\n"
        "# @report hid_text\n"
        "# @report-max-bytes 8\n"
        "# @report-ansi visible\n"
        "printf '\\033[31mred\\033[0m'\n"
    )
    assert meta.enabled
    assert meta.sinks == ("hid_text", "debug")
    assert meta.has_sink("hid_text")
    assert meta.max_bytes == 8
    assert meta.ansi == "visible"

    text, truncated = sanitize_report_text(b"abc\x1b[31mred\x1b[0m\n", meta)
    assert truncated
    assert "^[" in text
    assert "[truncated to 8 bytes]" in text

    strip_meta = parse_script_report_metadata("# @report hid_text\n# @report-ansi strip\n")
    text, truncated = sanitize_report_text(b"\x1b[31mred\x1b[0m\n", strip_meta)
    assert text == "red\n"
    assert not truncated

    invalid = parse_script_report_metadata("# @report hid_text\n# @report-ansi terminal\n# @report-max-bytes 999999\n")
    assert invalid.ansi == "strip"
    assert invalid.max_bytes == 65536

    passthrough = parse_script_report_metadata("# @report hid_text\n# @report-ansi passthrough\n")
    text, _ = sanitize_report_text(b"\x1b[2J", passthrough)
    assert text == "\x1b[2J"

    print("ok: KC_SH report metadata is opt-in and sanitizes ANSI text")


if __name__ == "__main__":
    main()
