#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import struct
from typing import Any

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SUSPICIOUS_NAMES = {".env", "id_rsa", "id_ed25519", "credentials", "credentials.json"}
SUSPICIOUS_SUFFIXES = {
    ".key",
    ".pem",
    ".p12",
    ".pfx",
    ".kdbx",
    ".sqlite",
    ".sqlite3",
    ".log",
    ".pcap",
    ".pcapng",
    ".har",
    ".evtx",
    ".dmp",
    ".core",
}
EMAIL_RE = re.compile(r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
PRIVATE_KEY_RE = re.compile(rb"-----BEGIN (?:(?:OPENSSH|RSA|EC|DSA|ENCRYPTED) )?PRIVATE KEY-----")
PRIVATE_DEVICE_HOST_RE = re.compile(r"\b" + "cqa02303v5" + r"-(?:00|01|02|40)\b")
ALLOWED_EMAIL_DOMAINS = {"github.com", "example.invalid", "example.local"}
SENSITIVE_PNG_CHUNKS = {b"eXIf", b"tEXt", b"zTXt", b"iTXt"}
PRIVATE_KEY_FIXTURE_PATHS = {
    "PUBLIC_EXPORT_REPORT.json",
    "PUBLIC_EXPORT_REPORT.md",
    "config/public-export-deny-patterns.json",
    "script/test_public_privacy_audit.py",
}


def png_chunks(data: bytes) -> list[str]:
    if not data.startswith(PNG_SIGNATURE):
        return []
    chunks = []
    offset = len(PNG_SIGNATURE)
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(data):
            return chunks + ["TRUNCATED"]
        if chunk_type in SENSITIVE_PNG_CHUNKS:
            chunks.append(chunk_type.decode("ascii", errors="replace"))
        offset = end
        if chunk_type == b"IEND":
            break
    return chunks


def audit(root: Path) -> dict[str, Any]:
    findings = []
    media = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if ".git" in path.relative_to(root).parts or relative.startswith("PUBLIC_PRIVACY_AUDIT."):
            continue
        data = path.read_bytes()
        lower_name = path.name.lower()
        if lower_name in SUSPICIOUS_NAMES or path.suffix.lower() in SUSPICIOUS_SUFFIXES:
            findings.append({"severity": "block", "kind": "suspicious_file", "path": relative})
        if PRIVATE_KEY_RE.search(data) and relative not in PRIVATE_KEY_FIXTURE_PATHS:
            findings.append({"severity": "block", "kind": "private_key", "path": relative})
        if data.startswith(PNG_SIGNATURE):
            chunks = png_chunks(data)
            media.append({"path": relative, "type": "png", "sensitive_metadata_chunks": chunks})
            if chunks:
                findings.append(
                    {
                        "severity": "block",
                        "kind": "embedded_image_metadata",
                        "path": relative,
                        "detail": chunks,
                    }
                )
        elif data.startswith(b"\xff\xd8"):
            has_exif = b"Exif\x00\x00" in data
            media.append({"path": relative, "type": "jpeg", "exif": has_exif})
            if has_exif:
                findings.append({"severity": "block", "kind": "embedded_image_metadata", "path": relative})
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if path.suffix.lower() == ".svg":
            has_metadata = bool(re.search(r"<(?:metadata|rdf:RDF)\b", text, re.IGNORECASE))
            media.append({"path": relative, "type": "svg", "embedded_metadata": has_metadata})
            if has_metadata:
                findings.append({"severity": "block", "kind": "embedded_image_metadata", "path": relative})
        for line_number, line in enumerate(text.splitlines(), 1):
            if PRIVATE_DEVICE_HOST_RE.search(line):
                findings.append(
                    {
                        "severity": "block",
                        "kind": "private_device_hostname",
                        "path": relative,
                        "line": line_number,
                    }
                )
            for match in EMAIL_RE.finditer(line):
                address = match.group(1)
                local, domain = address.rsplit("@", 1)
                if domain in ALLOWED_EMAIL_DOMAINS or local.endswith("getty"):
                    continue
                findings.append(
                    {
                        "severity": "block",
                        "kind": "personal_email",
                        "path": relative,
                        "line": line_number,
                        "detail": address,
                    }
                )
    blockers = [item for item in findings if item["severity"] == "block"]
    return {
        "schema": "hidloom.public-privacy-audit.v1",
        "ready": not blockers,
        "summary": {
            "files_scanned": sum(1 for item in root.rglob("*") if item.is_file()),
            "media_files": len(media),
            "findings": len(findings),
            "blockers": len(blockers),
        },
        "media": media,
        "findings": findings,
    }


def markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# HIDloom Public Privacy Audit",
        "",
        f"- Ready: `{str(payload['ready']).lower()}`",
        f"- Files scanned: {summary['files_scanned']}",
        f"- Media files: {summary['media_files']}",
        f"- Blockers: {summary['blockers']}",
        "",
        "## Media",
        "",
    ]
    lines.extend(f"- `{item['path']}`: {item['type']}" for item in payload["media"])
    lines.extend(["", "## Findings", ""])
    if payload["findings"]:
        lines.extend(
            f"- `{item['severity']}` `{item['kind']}` `{item['path']}`" for item in payload["findings"]
        )
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit a HIDloom public export for privacy-sensitive files")
    parser.add_argument("root", type=Path)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    payload = audit(root)
    json_path = args.json or root / "PUBLIC_PRIVACY_AUDIT.json"
    markdown_path = args.markdown or root / "PUBLIC_PRIVACY_AUDIT.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(markdown(payload), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))
    if not payload["ready"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
