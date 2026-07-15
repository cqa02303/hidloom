#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from hidloom_name_audit import audit


def initialize(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)


def main() -> None:
    assert audit(ROOT) == []
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        owner = "c" + "qa" + "02303"
        (root / "active.txt").write_text(
            f"HIDloom\nhttps://github.com/{owner}/hidloom\n{owner}v5-02\n",
            encoding="utf-8",
        )
        initialize(root)
        assert audit(root) == []
        (root / "retired.txt").write_text("c" + "qa-hidd\n", encoding="utf-8")
        subprocess.run(["git", "add", "retired.txt"], cwd=root, check=True)
        assert any(item.startswith("content:retired.txt:1:") for item in audit(root))

        (root / "retired.txt").write_text(
            f"{owner}-keyboard\n/com/{owner}/btd\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "retired.txt"], cwd=root, check=True)
        violations = audit(root)
        assert any(item.startswith("content:retired.txt:1:") for item in violations)
        assert any(item.startswith("content:retired.txt:2:") for item in violations)

        archive = root / "docs" / "archive"
        archive.mkdir(parents=True)
        (archive / "history.txt").write_text("c" + "qa-hidd\n", encoding="utf-8")
        subprocess.run(["git", "add", "docs/archive/history.txt"], cwd=root, check=True)
        (root / "retired.txt").unlink()
        subprocess.run(["git", "add", "-u"], cwd=root, check=True)
        assert audit(root) == []

        report = root / "PUBLIC_EXPORT_REPORT.json"
        report.write_text('{"finding": "c' + 'qa-hidd"}\n', encoding="utf-8")
        subprocess.run(["git", "add", report.name], cwd=root, check=True)
        assert audit(root) == []

    print("ok: HIDloom retired-name audit covers content, paths, and exclusions")


if __name__ == "__main__":
    main()
