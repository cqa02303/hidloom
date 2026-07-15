#!/usr/bin/env python3
"""Regression checks for logicd -> ledd semantic role snapshot push."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.runtime_notifications import LogicdNotifier  # noqa: E402
from logicd.state import LogicdRuntime  # noqa: E402


class DummyWriter:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    def write(self, data: bytes) -> None:
        self.messages.append(json.loads(data.decode("utf-8")))


def main() -> None:
    old_default = os.environ.get("HIDLOOM_DEFAULT_CONFIG_DIR")
    old_runtime = os.environ.get("HIDLOOM_RUNTIME_DIR")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        default_dir = root / "default"
        runtime_dir = root / "runtime"
        default_dir.mkdir()
        runtime_dir.mkdir()
        (default_dir / "ledd.json").write_text(
            json.dumps({
                "semantic_roles": {
                    "roles": {"KC_A": "function"},
                    "reactive": {"exclude_roles": ["function"]},
                },
            }),
            encoding="utf-8",
        )
        os.environ["HIDLOOM_DEFAULT_CONFIG_DIR"] = str(default_dir)
        os.environ["HIDLOOM_RUNTIME_DIR"] = str(runtime_dir)
        try:
            writer = DummyWriter()
            runtime = LogicdRuntime(ledd_writers=[writer])
            LogicdNotifier(runtime).push_ledd_semantic_roles()
        finally:
            if old_default is None:
                os.environ.pop("HIDLOOM_DEFAULT_CONFIG_DIR", None)
            else:
                os.environ["HIDLOOM_DEFAULT_CONFIG_DIR"] = old_default
            if old_runtime is None:
                os.environ.pop("HIDLOOM_RUNTIME_DIR", None)
            else:
                os.environ["HIDLOOM_RUNTIME_DIR"] = old_runtime

    assert writer.messages
    payload = writer.messages[-1]
    assert payload["t"] == "semantic_roles"
    assert payload["semantic_roles"]["roles"] == {"KC_A": "function"}
    assert payload["semantic_roles"]["reactive"] == {"exclude_roles": ["function"]}
    assert payload["source"].endswith("ledd.json")

    print("ok: logicd ledd semantic roles snapshot")


if __name__ == "__main__":
    main()
