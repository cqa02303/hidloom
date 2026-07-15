#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_legal_checksums(legal_info: Path) -> Path:
    checksum = legal_info / "legal-info.sha256"
    excluded = {"legal-info.sha256", "hidloom-summary.json"}
    symlinks = [path for path in legal_info.rglob("*") if path.is_symlink()]
    if symlinks:
        raise SystemExit(f"Buildroot legal-info contains symlinks: {symlinks}")
    files = sorted(
        path
        for path in legal_info.rglob("*")
        if path.is_file() and path.relative_to(legal_info).as_posix() not in excluded
    )
    checksum.write_text(
        "".join(
            f"{sha256(path)}  {path.relative_to(legal_info).as_posix()}\n" for path in files
        ),
        encoding="utf-8",
    )
    return checksum


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan or run Buildroot legal-info for a HIDloom output tree")
    parser.add_argument("--buildroot", type=Path, default=ROOT / "build/artifacts/buildroot-upstream")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--prepare-source", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--gnu-install", type=Path, default=Path("/usr/bin/gnuinstall"))
    args = parser.parse_args()
    buildroot = args.buildroot.resolve()
    output = args.output.resolve()
    command = ["make", "-C", str(buildroot), f"O={output}", "legal-info"]
    config = output / ".config"
    payload = {
        "schema": "hidloom.buildroot-legal-info-plan.v1",
        "execute": args.execute,
        "buildroot": str(buildroot),
        "output": str(output),
        "config_present": config.is_file(),
        "prepare_source": args.prepare_source,
        "command": command,
    }
    if args.execute:
        if not buildroot.is_dir():
            raise SystemExit(f"Buildroot source missing: {buildroot}")
        if not config.is_file():
            raise SystemExit(f"Buildroot output config missing: {config}")
        environment = os.environ.copy()
        with tempfile.TemporaryDirectory(prefix="hidloom-legal-info-") as tmp:
            wrapper = Path(tmp) / "install"
            if args.gnu_install.is_file():
                wrapper.symlink_to(args.gnu_install.resolve())
                environment["PATH"] = f"{tmp}:{environment['PATH']}"
                payload["gnu_install"] = str(args.gnu_install)
            if args.prepare_source:
                source_command = ["make", "-C", str(buildroot), f"O={output}", "source"]
                payload["source_command"] = source_command
                source_result = subprocess.run(source_command, check=False, env=environment)
                payload["source_returncode"] = source_result.returncode
                if source_result.returncode != 0:
                    completed = source_result
                else:
                    completed = subprocess.run(command, check=False, env=environment)
            else:
                completed = subprocess.run(command, check=False, env=environment)
        payload["returncode"] = completed.returncode
        legal_info = output / "legal-info"
        payload["legal_info_present"] = legal_info.is_dir()
        payload["manifest_present"] = (legal_info / "manifest.csv").is_file()
        if completed.returncode != 0:
            if args.report:
                args.report.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            raise SystemExit(completed.returncode)
        checksum_path = write_legal_checksums(legal_info)
        payload["checksum_manifest"] = str(checksum_path)
        summary_path = legal_info / "hidloom-summary.json"
        subprocess.run(
            [
                "python3",
                str(ROOT / "tools" / "summarize_buildroot_legal_info.py"),
                str(legal_info),
                "--output",
                str(summary_path),
            ],
            check=True,
        )
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        payload["summary"] = str(summary_path)
        payload["source_audit_ready"] = summary["source_audit_ready"]
        payload["binary_release_ready"] = summary["binary_release_ready"]
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
