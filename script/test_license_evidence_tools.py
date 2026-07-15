#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from buildroot_legal_info import write_legal_checksums  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "evidence"
        subprocess.run(
            ["python3", str(ROOT / "tools/collect_license_evidence.py"), str(output)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        evidence = json.loads((output / "LICENSE_EVIDENCE.json").read_text(encoding="utf-8"))
        assert evidence["schema"] == "hidloom.license-evidence.v1"
        assert evidence["scope"] == "host-observed-only"
        assert evidence["summary"]["debian_total"] == 21
        assert evidence["summary"]["python_total"] == 2

        plan = subprocess.run(
            [
                "python3",
                str(ROOT / "tools/buildroot_legal_info.py"),
                "--output",
                str(Path(tmp) / "buildroot-output"),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(plan.stdout)
        assert payload["execute"] is False
        assert payload["prepare_source"] is False
        assert payload["command"][-1] == "legal-info"
        assert not (Path(tmp) / "buildroot-output").exists()

        legal = Path(tmp) / "legal-info"
        (legal / "sources" / "fixture").mkdir(parents=True)
        payload_file = legal / "sources" / "fixture" / "source.tar.xz"
        payload_file.write_bytes(b"fixture source\n")
        (legal / "hidloom-summary.json").write_text("{}\n", encoding="utf-8")
        checksum = write_legal_checksums(legal)
        text = checksum.read_text(encoding="utf-8")
        assert "sources/fixture/source.tar.xz" in text
        assert "hidloom-summary.json" not in text
        assert "legal-info.sha256" not in text

    print("ok: license evidence collection and Buildroot legal-info planning")


if __name__ == "__main__":
    main()
