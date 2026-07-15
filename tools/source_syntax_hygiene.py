#!/usr/bin/env python3
"""Validate syntax for every supported tracked text source format."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
import warnings
import xml.etree.ElementTree as ElementTree

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from repository_hygiene import tracked_files  # noqa: E402


@dataclass(frozen=True, order=True)
class Finding:
    kind: str
    path: str
    detail: str


def concise_error(value: object) -> str:
    return " ".join(str(value).split())[:500]


def load_yaml_module() -> object:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to validate tracked YAML") from exc
    return yaml


def first_line(content: bytes) -> str:
    if not content:
        return ""
    return content.splitlines()[0].decode("utf-8", errors="replace")


def shell_parser(relative: str, content: bytes) -> str | None:
    shebang = first_line(content)
    if "bash" in shebang:
        return "bash"
    if shebang in {"#!/bin/sh", "#!/usr/bin/env sh"}:
        return "sh"
    if relative.endswith(".sh"):
        return "sh"
    return None


def run_parser(command: list[str], root: Path) -> str | None:
    completed = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode == 0:
        return None
    return concise_error(completed.stderr or completed.stdout or f"exit {completed.returncode}")


def scan(root: Path, paths: list[str]) -> tuple[list[Finding], Counter[str]]:
    findings: list[Finding] = []
    counts: Counter[str] = Counter()
    yaml_module = None
    node = shutil.which("node")
    shell_tools = {name: shutil.which(name) for name in ("bash", "sh")}

    for relative in paths:
        path = root / relative
        if path.is_symlink() or not path.is_file():
            continue
        content = path.read_bytes()
        suffix = path.suffix.lower()

        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            continue

        if suffix == ".py":
            counts["python"] += 1
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", SyntaxWarning)
                    compile(text, relative, "exec", dont_inherit=True)
            except (SyntaxError, SyntaxWarning) as exc:
                findings.append(Finding("python_syntax", relative, concise_error(exc)))

        if suffix == ".json" or suffix == ".json_v5rpi" or relative.endswith(".json.sample"):
            counts["json"] += 1
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                findings.append(Finding("json_syntax", relative, concise_error(exc)))

        if suffix == ".toml":
            counts["toml"] += 1
            try:
                tomllib.loads(text)
            except tomllib.TOMLDecodeError as exc:
                findings.append(Finding("toml_syntax", relative, concise_error(exc)))

        if suffix in {".yml", ".yaml"}:
            counts["yaml"] += 1
            if yaml_module is None:
                try:
                    yaml_module = load_yaml_module()
                except RuntimeError as exc:
                    findings.append(Finding("missing_parser", "*.yml", concise_error(exc)))
                    yaml_module = False
            if yaml_module:
                try:
                    list(yaml_module.safe_load_all(text))
                except yaml_module.YAMLError as exc:
                    findings.append(Finding("yaml_syntax", relative, concise_error(exc)))

        parser = shell_parser(relative, content)
        if parser is not None:
            counts["shell"] += 1
            executable = shell_tools[parser]
            if executable is None:
                findings.append(Finding("missing_parser", relative, f"{parser} not found"))
            elif error := run_parser([executable, "-n", str(path)], root):
                findings.append(Finding("shell_syntax", relative, error))

        if suffix == ".js":
            counts["javascript"] += 1
            if node is None:
                findings.append(Finding("missing_parser", relative, "node not found"))
            elif error := run_parser([node, "--check", str(path)], root):
                findings.append(Finding("javascript_syntax", relative, error))

        if suffix == ".svg":
            counts["svg"] += 1
            try:
                ElementTree.fromstring(text)
            except ElementTree.ParseError as exc:
                findings.append(Finding("svg_syntax", relative, concise_error(exc)))

    return sorted(set(findings)), counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    root = args.root.resolve()
    paths, _modes, inventory = tracked_files(root)
    findings, counts = scan(root, paths)
    if findings:
        for finding in findings:
            print(f"{finding.kind}: {finding.path}: {finding.detail}", file=sys.stderr)
        print(
            f"source syntax hygiene failed: {len(findings)} finding(s), "
            f"{len(paths)} files from {inventory}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    summary = ", ".join(f"{name}={counts[name]}" for name in sorted(counts))
    print(f"ok: source syntax hygiene ({len(paths)} files from {inventory}; {summary})")


if __name__ == "__main__":
    main()
