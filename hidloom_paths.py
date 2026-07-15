"""Canonical repository and runtime path helpers for HIDloom."""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_RUNTIME_DIR = Path("/mnt/p3")


def environment_value(name: str, default: str | None = None) -> str | None:
    return os.environ.get(f"HIDLOOM_{name}") or default


def repo_root() -> Path:
    return REPO_ROOT


def default_config_dir(root: Path | None = None) -> Path:
    override = environment_value("DEFAULT_CONFIG_DIR")
    if override:
        return Path(override)
    return (root or REPO_ROOT) / "config" / "default"


def default_config_file(name: str, root: Path | None = None) -> Path:
    return default_config_dir(root) / name


def board_profiles_dir(root: Path | None = None) -> Path:
    override = environment_value("BOARD_PROFILES_DIR")
    if override:
        return Path(override)
    return (root or REPO_ROOT) / "config" / "boards"


def runtime_dir() -> Path:
    return Path(
        environment_value("RUNTIME_DIR", str(DEFAULT_RUNTIME_DIR))
    )


def runtime_file(name: str) -> Path:
    return runtime_dir() / name


def runtime_script_dir() -> Path:
    return Path(
        environment_value("RUNTIME_SCRIPT_DIR", str(runtime_file("script")))
    )
