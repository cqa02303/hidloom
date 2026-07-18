#!/usr/bin/env python3
"""Regression checks for safe runtime script migration."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile

from migrate_runtime_scripts import file_sha256, migrate_runtime_scripts

ROOT = Path(__file__).resolve().parents[1]
REAL_DEFAULTS = ROOT / "config" / "default" / "script"
REAL_MANIFEST = ROOT / "config" / "default" / "script-migrations.json"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> None:
    legacy = b"#!/bin/sh\n" + b"c" + b"qa-notify alert legacy 1\n"
    current = b"#!/bin/sh\nhidloom-notify alert current 1\n"
    custom = b"#!/bin/sh\necho operator-custom\n"
    manifest_payload = {
        "schema": "hidloom.runtime-script-migrations.v1",
        "scripts": {
            "KC_SH2.sh": {"legacy_sha256": [sha256_bytes(legacy)]},
        },
    }

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        defaults = root / "defaults"
        runtime = root / "runtime"
        defaults.mkdir()
        runtime.mkdir()
        (defaults / "KC_SH2.sh").write_bytes(current)
        (defaults / "KC_SH3.sh").write_bytes(current)
        (defaults / "KC_SH4.sh").write_bytes(current)
        (defaults / "KC_SH5.sh").write_bytes(current)
        (runtime / "KC_SH2.sh").write_bytes(legacy)
        (runtime / "KC_SH3.sh").write_bytes(custom)
        (runtime / "KC_SH4.sh").symlink_to(defaults / "KC_SH4.sh")
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")

        dry_actions = migrate_runtime_scripts(
            defaults_dir=defaults,
            runtime_dir=runtime,
            manifest_path=manifest,
            dry_run=True,
            timestamp="TEST",
        )
        assert dry_actions == {
            "KC_SH2.sh": "migrate",
            "KC_SH3.sh": "preserve-custom",
            "KC_SH4.sh": "preserve-symlink",
            "KC_SH5.sh": "seed",
        }
        assert (runtime / "KC_SH2.sh").read_bytes() == legacy
        assert not list(runtime.glob("*.bak.*"))
        assert not (runtime / "KC_SH5.sh").exists()

        actions = migrate_runtime_scripts(
            defaults_dir=defaults,
            runtime_dir=runtime,
            manifest_path=manifest,
            timestamp="TEST",
        )
        assert actions == dry_actions
        assert (runtime / "KC_SH2.sh").read_bytes() == current
        assert (runtime / "KC_SH2.sh.bak.TEST").read_bytes() == legacy
        assert (runtime / "KC_SH3.sh").read_bytes() == custom
        assert (runtime / "KC_SH4.sh").is_symlink()
        assert (runtime / "KC_SH5.sh").read_bytes() == current

        second_actions = migrate_runtime_scripts(
            defaults_dir=defaults,
            runtime_dir=runtime,
            manifest_path=manifest,
            timestamp="TEST2",
        )
        assert second_actions["KC_SH2.sh"] == "current"
        assert not (runtime / "KC_SH2.sh.bak.TEST2").exists()

    real_manifest = json.loads(REAL_MANIFEST.read_text(encoding="utf-8"))
    assert real_manifest["schema"] == "hidloom.runtime-script-migrations.v1"
    migrations = real_manifest["scripts"]
    observed_legacy = {
        "KC_SH1.sh": "fb8b88edc6994b0c83f00b0f760b2ba643c781aa7f53179af490df248b7a5153",
        "KC_SH2.sh": "3f5ee303c54a38b587fe0fced49d0803649a0e0382c20e1821ce8e52470924ea",
        "KC_SH3.sh": "62b87a8ae9b6ad73aba330b47819190ad9972f8b0f2d074f5276d951bc2e693b",
        "KC_SH4.sh": "5363b20ab607aa4275cd1ad20a64d9eea3518471a89618808d85997d4db6ba94",
        "KC_SH7.sh": "0ff29685a19954659d6dd87dda7bff9217d5d98570cbbacabf5d754c0f939340",
        "KC_SH8.sh": "f438d216fe35af31915a426a96710cb51b15ae9de7897a32dcfd03b7b8b28de4",
        "KC_SH10.sh": "b6c871648f55adf37df48bd37780385584ae043515f08ed479d4a7ba4f3bb3c4",
    }
    for name, legacy_hash in observed_legacy.items():
        assert legacy_hash in migrations[name]["legacy_sha256"]
        assert file_sha256(REAL_DEFAULTS / name) not in migrations[name]["legacy_sha256"]

    print("ok: runtime script migration")


if __name__ == "__main__":
    main()
