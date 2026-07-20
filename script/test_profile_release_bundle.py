#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
PROFILE = "touch-waveshare-8.8"


def make_package(
    path: Path,
    package: str,
    version: str,
    source: Path,
    depends: str | None = None,
) -> None:
    root = path.parent / f"root-{package}"
    control = root / "DEBIAN/control"
    control.parent.mkdir(parents=True)
    lines = [
        f"Package: {package}",
        f"Version: {version}",
        "Architecture: arm64",
        "Maintainer: HIDloom Test <test@localhost>",
        "Description: HIDloom profile release fixture",
    ]
    if depends:
        lines.insert(4, f"Depends: {depends}")
    control.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if package == "hidloom-core":
        report = json.loads((source / "PUBLIC_EXPORT_REPORT.json").read_text(encoding="utf-8"))
        provenance = report["source_provenance"]
        manifest = {
            "source_mode": "public-export",
            "git_sha": provenance["base_commit"][:12],
            "git_describe": provenance["base_commit"],
            "git_rev_count": provenance["base_revision_count"],
            "public_export_manifest_sha256": hashlib.sha256(
                (source / "PUBLIC_EXPORT_MANIFEST.json").read_bytes()
            ).hexdigest(),
            "dirty_worktree_ignored": False,
        }
        destination = root / "var/lib/hidloom/package-manifest.json"
        destination.parent.mkdir(parents=True)
        destination.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    else:
        destination = root / f"usr/share/hidloom/profiles/{PROFILE}/profile.json"
        destination.parent.mkdir(parents=True)
        destination.write_text(json.dumps({"id": PROFILE}) + "\n", encoding="utf-8")
    for directory in (item for item in root.rglob("*") if item.is_dir()):
        directory.chmod(0o755)
    root.chmod(0o755)
    control.chmod(0o644)
    subprocess.run(["dpkg-deb", "--build", str(root), str(path)], check=True, capture_output=True)


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary)
        export = workspace / "export"
        packages = workspace / "packages"
        release = workspace / "release"
        subprocess.run(
            [
                "python3",
                str(ROOT / "tools/public_export.py"),
                str(export),
                "--draft",
                "--allow-dirty-source",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        packages.mkdir()
        report = json.loads((export / "PUBLIC_EXPORT_REPORT.json").read_text(encoding="utf-8"))
        provenance = report["source_provenance"]
        version = f"0.0.{provenance['base_revision_count']}+git{provenance['base_commit'][:12]}"
        core = packages / f"hidloom-core_{version}_arm64.deb"
        profile = packages / f"hidloom-profile-{PROFILE}_{version}_arm64.deb"
        make_package(core, "hidloom-core", version, export)
        make_package(
            profile,
            f"hidloom-profile-{PROFILE}",
            version,
            export,
            f"hidloom-core (= {version})",
        )

        command = [
            "python3",
            str(export / "tools/package/build_profile_release_bundle.py"),
            "build",
            "--source",
            str(export),
            "--core-package",
            str(core),
            "--profile-package",
            str(profile),
            "--profile",
            PROFILE,
            "--guide",
            str(export / "docs/hardware/raspberry-pi-4-touch-panel-package.md"),
            "--output",
            str(release),
        ]
        created = subprocess.run(command, cwd=export, capture_output=True, text=True)
        assert created.returncode == 0, created.stdout + created.stderr
        manifest = json.loads((release / "PACKAGE_RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
        assert manifest["schema"] == "hidloom.profile-package-release.v1"
        assert manifest["profile"]["id"] == PROFILE
        assert manifest["packages"]["version"] == version
        assert manifest["hardware_smoke"]["status"] == "pending"
        assert manifest["publication"]["ready"] is False
        assert "public-build-provenance-missing" in manifest["publication"]["blockers"]
        subprocess.run(
            [
                "python3",
                str(export / "tools/package/build_profile_release_bundle.py"),
                "verify",
                str(release),
            ],
            cwd=export,
            check=True,
            capture_output=True,
            text=True,
        )
        blocked = subprocess.run(
            [
                "python3",
                str(export / "tools/package/build_profile_release_bundle.py"),
                "verify",
                str(release),
                "--require-publication-ready",
            ],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert blocked.returncode != 0
        assert "not publishable" in blocked.stderr
        with (release / "QUICKSTART.md").open("a", encoding="utf-8") as stream:
            stream.write("tampered\n")
        tampered = subprocess.run(
            [
                "python3",
                str(export / "tools/package/build_profile_release_bundle.py"),
                "verify",
                str(release),
            ],
            cwd=export,
            capture_output=True,
            text=True,
        )
        assert tampered.returncode != 0
        assert "asset mismatch" in tampered.stderr

    print("ok: touch-panel profile package release bundle and publication guard")


if __name__ == "__main__":
    main()
