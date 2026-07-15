#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BUILDROOT = ROOT / "build" / "artifacts" / "buildroot-upstream"


def main() -> None:
    source = json.loads((ROOT / "config" / "buildroot-source.json").read_text(encoding="utf-8"))
    assert source["schema"] == "hidloom.buildroot-source.v1"
    assert source["repository"] == "https://gitlab.com/buildroot.org/buildroot.git"
    assert len(source["commit"]) == 40

    with tempfile.TemporaryDirectory() as tmp:
        fixture = Path(tmp)
        repository = fixture / "repository"
        destination = fixture / "checkout"
        repository.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
        subprocess.run(["git", "config", "user.name", "HIDloom Test"], cwd=repository, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@localhost"], cwd=repository, check=True
        )
        (repository / "README").write_text("fixture\n", encoding="utf-8")
        subprocess.run(["git", "add", "README"], cwd=repository, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repository, check=True)
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip()
        config = fixture / "source.json"
        config.write_text(
            json.dumps(
                {
                    "schema": "hidloom.buildroot-source.v1",
                    "repository": str(repository),
                    "commit": commit,
                }
            ),
            encoding="utf-8",
        )
        subprocess.run(
            [
                "python3",
                str(ROOT / "tools" / "buildroot_source_prepare.py"),
                "--config",
                str(config),
                "--destination",
                str(destination),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        assert subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=destination, text=True
        ).strip() == commit

    prepare_command = [
        "python3",
        str(ROOT / "tools" / "buildroot_source_prepare.py"),
        "--destination",
        str(BUILDROOT),
    ]
    if (BUILDROOT / ".git").is_dir():
        prepare_command.append("--check-only")
    subprocess.run(
        prepare_command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        export = workspace / "export"
        output = workspace / "output"
        subprocess.run(
            ["python3", str(ROOT / "tools" / "public_export.py"), str(export), "--draft"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        environment = os.environ.copy()
        environment.update(
            {
                "BUILDROOT_DIR": str(BUILDROOT),
                "BUILDROOT_OUTPUT": str(output),
                "HIDLOOM_BUILD_HOSTBIN": str(workspace / "hostbin"),
            }
        )
        subprocess.run(
            [str(export / "tools" / "buildroot_m6_build.sh"), "--configure-only"],
            cwd=export,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        config = (output / ".config").read_text(encoding="utf-8")
        assert "BR2_PACKAGE_HIDLOOM_MATRIXD=y" in config
        assert "BR2_PACKAGE_PYTHON_LUMA_OLED=y" in config
        assert "BR2_PACKAGE_SUDO=y" in config
        assert str(export / "build/buildroot/hidloom-external") in config
        provenance = workspace / "PUBLIC_BUILD_PROVENANCE.json"
        subprocess.run(
            [
                "python3",
                str(export / "tools/public_build_provenance.py"),
                "collect",
                "--source",
                str(export),
                "--mode",
                "buildroot-configure",
                "--buildroot-source",
                str(BUILDROOT),
                "--buildroot-output",
                str(output),
                "--output",
                str(provenance),
            ],
            cwd=export,
            check=True,
            capture_output=True,
            text=True,
        )
        evidence = json.loads(provenance.read_text(encoding="utf-8"))
        assert evidence["ready"] is True
        assert evidence["buildroot"]["source"]["commit"] == source["commit"]
        assert evidence["buildroot"]["configuration"]["external_source_match"] is True
        verify_command = [
            "python3",
            str(export / "tools/public_build_provenance.py"),
            "verify",
            str(provenance),
            "--source",
            str(export),
            "--buildroot-source",
            str(BUILDROOT),
            "--buildroot-output",
            str(output),
        ]
        subprocess.run(
            verify_command,
            cwd=export,
            check=True,
            capture_output=True,
            text=True,
        )
        config_path = output / ".config"
        original_config = config_path.read_bytes()
        config_path.write_bytes(original_config + b"\n# provenance tamper\n")
        tampered = subprocess.run(verify_command, cwd=export, capture_output=True, text=True)
        assert tampered.returncode != 0
        assert "does not match" in tampered.stderr
        config_path.write_bytes(original_config)

    print("ok: public export expands and provenance-verifies pinned Buildroot M6 config")


if __name__ == "__main__":
    main()
