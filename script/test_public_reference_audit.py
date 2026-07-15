#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def run_audit(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(root / "tools/public_reference_audit.py"), str(root)],
        cwd=root,
        capture_output=True,
        text=True,
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        export = Path(temporary) / "public"
        subprocess.run(
            ["python3", str(ROOT / "tools/public_export.py"), str(export), "--draft"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        report = json.loads((export / "PUBLIC_REFERENCE_AUDIT.json").read_text(encoding="utf-8"))
        assert report["ready"] is True
        assert report["summary"]["blockers"] == 0
        assert report["summary"]["public_repository_references"] > 0
        assert report["public_repository"]["slug"] == "cqa02303/hidloom"

        owner = "c" + "qa" + "02303"
        private_slug = owner + "/" + owner + "v5rpi"
        local_remote = "file:" + "///tmp/private-hidloom.git"
        with (export / "README.md").open("a", encoding="utf-8") as stream:
            stream.write(f"\nhttps://github.com/{private_slug}.git\n")
            stream.write(local_remote + "\n")
        blocked = run_audit(export)
        assert blocked.returncode == 2
        blocked_report = json.loads((export / "PUBLIC_REFERENCE_AUDIT.json").read_text(encoding="utf-8"))
        kinds = {item["kind"] for item in blocked_report["findings"]}
        assert "blocked_private_repository_reference" in kinds
        assert "absolute_local_repository_remote" in kinds

    print("ok: public references reject private and local repository remotes")


if __name__ == "__main__":
    main()
