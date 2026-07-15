"""Small response helpers for HTTP .vil import/export routes."""
from __future__ import annotations

import re


def safe_header_filename_part(value: object, fallback: str = "layout") -> str:
    text = str(value or fallback)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._-")
    return (safe or fallback)[:80]


def attachment_content_disposition(filename: str) -> str:
    safe = safe_header_filename_part(filename, "layout.vil")
    if not safe.endswith(".vil"):
        safe = f"{safe}.vil"
    return f'attachment; filename="{safe}"'
