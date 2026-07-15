#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def host_os() -> dict[str, str]:
    values = {}
    for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip('"')
    return {key: values.get(key, "") for key in ("ID", "VERSION_ID", "PRETTY_NAME")}


def debian_evidence(names: list[str], output: Path) -> list[dict[str, Any]]:
    results = []
    target = output / "debian"
    target.mkdir(parents=True, exist_ok=True)
    for name in names:
        query = subprocess.run(
            ["dpkg-query", "-W", "-f=${binary:Package}\t${Version}", name],
            capture_output=True,
            text=True,
        )
        item: dict[str, Any] = {"name": name, "observed": query.returncode == 0}
        if query.returncode == 0:
            package, version = query.stdout.split("\t", 1)
            item.update({"package": package, "version": version})
            copyright_path = Path("/usr/share/doc") / package.split(":", 1)[0] / "copyright"
            if copyright_path.is_file():
                copied = target / f"{name}.copyright"
                shutil.copy2(copyright_path, copied)
                item.update(
                    {
                        "copyright_file": copied.relative_to(output).as_posix(),
                        "copyright_sha256": sha256(copied),
                    }
                )
            else:
                item["copyright_missing"] = True
        results.append(item)
    return results


def python_evidence(names: list[str], output: Path) -> list[dict[str, Any]]:
    results = []
    target = output / "python"
    target.mkdir(parents=True, exist_ok=True)
    for name in names:
        item: dict[str, Any] = {"name": name, "observed": False}
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            results.append(item)
            continue
        item.update(
            {
                "observed": True,
                "version": dist.version,
                "declared_license": dist.metadata.get("License") or "",
                "license_expression": dist.metadata.get("License-Expression") or "",
                "classifiers": [
                    value
                    for value in dist.metadata.get_all("Classifier", [])
                    if value.startswith("License ::")
                ],
            }
        )
        copied_files = []
        for relative in dist.files or []:
            if not any(token in relative.name.upper() for token in ("LICENSE", "COPYING", "NOTICE")):
                continue
            source = Path(dist.locate_file(relative))
            if not source.is_file():
                continue
            copied = target / f"{name}-{relative.name}"
            shutil.copy2(source, copied)
            copied_files.append(
                {"path": copied.relative_to(output).as_posix(), "sha256": sha256(copied)}
            )
        item["license_files"] = copied_files
        results.append(item)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect host-observed license evidence for HIDloom dependencies")
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--inventory",
        type=Path,
        default=ROOT / "docs/ops/third-party-inventory.json",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    inventory = load_json(args.inventory)
    debian = [item["name"] for item in inventory["components"] if item["ecosystem"] == "debian"]
    pypi = [item["name"] for item in inventory["components"] if item["ecosystem"] == "pypi"]
    payload = {
        "schema": "hidloom.license-evidence.v1",
        "scope": "host-observed-only",
        "host": host_os(),
        "debian": debian_evidence(debian, output),
        "python": python_evidence(pypi, output),
    }
    payload["summary"] = {
        "debian_total": len(payload["debian"]),
        "debian_observed": sum(item["observed"] for item in payload["debian"]),
        "python_total": len(payload["python"]),
        "python_observed": sum(item["observed"] for item in payload["python"]),
    }
    (output / "LICENSE_EVIDENCE.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
