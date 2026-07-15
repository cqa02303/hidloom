#!/usr/bin/env python3
"""Small helper for script/test_* suite entrypoints."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]


def test_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    environment = dict(os.environ if source is None else source)
    environment.pop("CARGO_TARGET_DIR", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def run_suite(name: str, tests: Iterable[str], *, stop_on_failure: bool = False) -> None:
    failed: list[str] = []
    environment = test_environment()
    for rel in tests:
        path = ROOT / rel
        print(f"== {rel}", flush=True)
        result = subprocess.run([sys.executable, str(path)], cwd=ROOT, env=environment)
        if result.returncode == 0:
            continue
        if stop_on_failure:
            result.check_returncode()
        failed.append(rel)

    if failed:
        print(f"FAILED {name}:")
        for rel in failed:
            print(f"- {rel}")
        raise SystemExit(1)
    print(f"ok: {name}")
