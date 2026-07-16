#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        temp = Path(tmp)
        generated_json = temp / "inventory.json"
        generated_markdown = temp / "notices.md"
        subprocess.run(
            [
                "python3",
                str(ROOT / "tools/generate_third_party_inventory.py"),
                "--json",
                str(generated_json),
                "--markdown",
                str(generated_markdown),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        assert generated_json.read_bytes() == (ROOT / "docs/ops/third-party-inventory.json").read_bytes()
        assert generated_markdown.read_bytes() == (ROOT / "THIRD_PARTY_NOTICES.md").read_bytes()
        inventory = json.loads(generated_json.read_text(encoding="utf-8"))
        assert inventory["schema"] == "hidloom.third-party-inventory.v2"
        assert inventory["summary"]["total"] == 56
        assert inventory["summary"]["complete"] == 31
        assert inventory["summary"]["not_redistributed"] == 25
        assert inventory["summary"]["review_required"] == 0
        assert inventory["summary"]["redistributed_review_required"] == 0
        assert any(
            item["name"] == "serde"
            and item["review"] == "complete"
            and item["distribution_scope"] == "linked-binary"
            for item in inventory["components"]
        )
        assert any(
            item["name"] == "rpi-firmware"
            and item["version"] == "063bcab6c8a90efb0d19f69d88cbbc7ec79cab68"
            and item["license"] == "BSD-3-Clause"
            and item["review"] == "complete"
            for item in inventory["components"]
        )
        assert any(
            item["name"] == "build-essential"
            and item["review"] == "not-redistributed"
            and item["distribution_scope"] == "external-install-dependency"
            for item in inventory["components"]
        )
        assert any(
            item["name"] == "toolchain-external-bootlin"
            and item["license_evidence"] == "bootlin-official-summary"
            for item in inventory["components"]
        )
        assert any(
            item["name"] == "actions/checkout"
            and item["version"] == "7.0.0"
            and item["commit_sha"] == "9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
            and item["license"] == "MIT"
            and item["distribution_scope"] == "ci-action-reference"
            for item in inventory["components"]
        )
        assert any(
            item["name"] == "actions/cache"
            and item["version"] == "6.1.0"
            and item["commit_sha"] == "55cc8345863c7cc4c66a329aec7e433d2d1c52a9"
            and item["license"] == "MIT"
            and item["distribution_scope"] == "ci-action-reference"
            for item in inventory["components"]
        )

    print("ok: third-party inventory is deterministic and preserves review boundaries")


if __name__ == "__main__":
    main()
