"""KC_SH opt-in report metadata and text sanitizing helpers.

KC_SH scripts default to no report output.  A script must explicitly opt in with
metadata such as ``# @report hid_text`` before stdout/stderr is routed to a
report sink.  This keeps helper scripts useful for normal keyboard operation
without unexpectedly typing command output into the host.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_REPORT_LINE_RE = re.compile(
    r"^[ \t]*#[ \t]*@report[ \t]+([A-Za-z0-9_.:-]+)(?:[ \t]+([^\r\n]*))?[ \t]*$",
    re.MULTILINE,
)
_REPORT_MAX_BYTES_RE = re.compile(r"^[ \t]*#[ \t]*@report-max-bytes[ \t]+(\d+)[ \t]*$", re.MULTILINE)
_REPORT_ANSI_RE = re.compile(
    r"^[ \t]*#[ \t]*@report-ansi[ \t]+([A-Za-z0-9_.:-]+)[ \t]*$",
    re.MULTILINE,
)
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_DEFAULT_MAX_BYTES = 2048
_MAX_MAX_BYTES = 65536
_ALLOWED_ANSI_POLICIES = {"strip", "visible", "passthrough"}


@dataclass(frozen=True)
class ScriptReportMetadata:
    """Explicit KC_SH report request parsed from script comments."""

    sinks: tuple[str, ...]
    max_bytes: int = _DEFAULT_MAX_BYTES
    ansi: str = "strip"

    @property
    def enabled(self) -> bool:
        return bool(self.sinks)

    def has_sink(self, sink: str) -> bool:
        return sink in self.sinks


def parse_script_report_metadata(script_text: str) -> ScriptReportMetadata:
    """Parse opt-in report metadata from a KC_SH script.

    Supported comments:
    - ``# @report hid_text`` requests a report sink.
    - ``# @report-max-bytes 4096`` caps captured output.
    - ``# @report-ansi strip|visible|passthrough`` controls ANSI handling.

    The default remains no report output.
    """

    text = script_text or ""
    sinks = tuple(dict.fromkeys(match.group(1).strip() for match in _REPORT_LINE_RE.finditer(text)))
    max_bytes = _DEFAULT_MAX_BYTES
    max_match = _REPORT_MAX_BYTES_RE.search(text)
    if max_match:
        try:
            max_bytes = max(0, min(_MAX_MAX_BYTES, int(max_match.group(1))))
        except ValueError:
            max_bytes = _DEFAULT_MAX_BYTES
    ansi = "strip"
    ansi_match = _REPORT_ANSI_RE.search(text)
    if ansi_match:
        candidate = ansi_match.group(1).strip().lower()
        if candidate in _ALLOWED_ANSI_POLICIES:
            ansi = candidate
    return ScriptReportMetadata(sinks=sinks, max_bytes=max_bytes, ansi=ansi)


def sanitize_report_text(data: bytes, metadata: ScriptReportMetadata) -> tuple[str, bool]:
    """Decode and constrain captured script output for a text report sink.

    ``strip`` removes ANSI escape sequences.
    ``visible`` renders ESC as ``^[`` so terminal control is visible but inert.
    ``passthrough`` keeps ESC characters for explicitly trusted sinks that can
    intentionally emit ESC key sequences.  Callers must reject passthrough when
    their sender cannot type ESC safely.
    """

    max_bytes = metadata.max_bytes
    truncated = max_bytes >= 0 and len(data) > max_bytes
    clipped = data[:max_bytes] if max_bytes >= 0 else data
    text = clipped.decode("utf-8", errors="replace")
    if metadata.ansi == "strip":
        text = _ANSI_ESCAPE_RE.sub("", text)
    elif metadata.ansi == "visible":
        text = text.replace("\x1b", "^[")

    safe_chars: list[str] = []
    for ch in text:
        if ch in "\n\t":
            safe_chars.append(ch)
        elif ch == "\r":
            continue
        elif ch == "\x1b" and metadata.ansi == "passthrough":
            safe_chars.append(ch)
        elif " " <= ch <= "~":
            safe_chars.append(ch)
        else:
            safe_chars.append("?")
    safe = "".join(safe_chars)
    if truncated:
        if safe and not safe.endswith("\n"):
            safe += "\n"
        safe += f"[truncated to {max_bytes} bytes]\n"
    return safe, truncated
