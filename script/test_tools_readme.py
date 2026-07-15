#!/usr/bin/env python3
"""Ensure tools/README.md lists the manual helper scripts."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
README = TOOLS / "README.md"


def main() -> None:
    readme = README.read_text(encoding="utf-8")
    tool_files = sorted(
        str(path.relative_to(TOOLS))
        for path in TOOLS.rglob("*.py")
        if path.is_file() and not path.name.startswith("_") and "__pycache__" not in path.parts
    )
    assert tool_files, "no tools found"
    for name in tool_files:
        assert name in readme or Path(name).name in readme, f"missing tools/README.md entry: {name}"
    assert "`script/` は自動回帰テスト" in readme
    assert "`tools/` は実機" in readme
    print("ok: tools README lists manual helpers")


if __name__ == "__main__":
    main()
