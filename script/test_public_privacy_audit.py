#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import struct
import subprocess
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[1]


def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def metadata_png() -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    text = chunk(b"tEXt", b"Author\x00Private Person")
    image = chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00"))
    return signature + ihdr + text + image + chunk(b"IEND", b"")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "safe.txt").write_text("public fixture\n", encoding="utf-8")
        safe = subprocess.run(
            ["python3", str(ROOT / "tools/public_privacy_audit.py"), str(root)],
            check=True,
            capture_output=True,
            text=True,
        )
        assert json.loads(safe.stdout)["blockers"] == 0

        (root / "photo.png").write_bytes(metadata_png())
        (root / "id_ed25519").write_text(
            "-----BEGIN " + "OPENSSH PRIVATE KEY-----\nfixture\n",
            encoding="utf-8",
        )
        private_hostname = "cqa02303v5" + "-02"
        (root / "device.txt").write_text(f"ssh pi@{private_hostname}\n", encoding="utf-8")
        blocked = subprocess.run(
            ["python3", str(ROOT / "tools/public_privacy_audit.py"), str(root)],
            capture_output=True,
            text=True,
        )
        assert blocked.returncode == 2
        report = json.loads((root / "PUBLIC_PRIVACY_AUDIT.json").read_text(encoding="utf-8"))
        kinds = {item["kind"] for item in report["findings"]}
        assert {
            "suspicious_file",
            "private_key",
            "embedded_image_metadata",
            "private_device_hostname",
        } <= kinds

    print("ok: privacy audit blocks secret files and embedded image metadata")


if __name__ == "__main__":
    main()
