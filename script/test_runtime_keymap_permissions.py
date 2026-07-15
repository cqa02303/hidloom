#!/usr/bin/env python3
"""Runtime keymap persistence permissions."""
from __future__ import annotations

import stat
import sys
import tempfile
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "daemon"))

from logicd import config_loader  # noqa: E402
from logicd.keymap_store import save_runtime_keymap  # noqa: E402


def main() -> None:
    default_keymap = ROOT / "config" / "default" / "keymap.json"
    layers = config_loader.keymap_json_to_layers(json.loads(default_keymap.read_text(encoding="utf-8")))

    with tempfile.TemporaryDirectory() as tmp:
        runtime_keymap = Path(tmp) / "keymap.json"
        saved = save_runtime_keymap(
            layers,
            preferred=str(runtime_keymap),
            fallback=str(default_keymap),
        )
        mode = stat.S_IMODE(Path(saved).stat().st_mode)
        assert mode == 0o644, oct(mode)

    print("ok: runtime keymap persistence keeps read-only diagnostics readable")


if __name__ == "__main__":
    main()
