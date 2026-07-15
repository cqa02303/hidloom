#!/usr/bin/env python3
"""Regression checks for packaged command and daemon ``--help`` surfaces."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _help_env() -> dict[str, str]:
    env = os.environ.copy()
    pythonpath = [str(ROOT / "daemon"), str(ROOT)]
    if env.get("PYTHONPATH"):
        pythonpath.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath)
    return env


def _run_help(command: list[str], *, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        [*command, "--help"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=15,
    )
    assert completed.returncode == 0, (
        f"{command!r} --help failed with {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )
    assert "usage:" in completed.stdout.lower(), completed.stdout
    assert "--help" in completed.stdout, completed.stdout
    return completed.stdout


def test_python_daemon_help_exits_before_runtime_start() -> None:
    env = _help_env()
    module_commands = [
        [sys.executable, "-m", "logicd.logicd"],
        [sys.executable, "-m", "usbd.usbd"],
        [sys.executable, "-m", "viald.viald"],
        [sys.executable, "-m", "i2cd.i2cd"],
        [sys.executable, "-m", "ledd.ledd"],
        [sys.executable, "-m", "ledd.shutdown"],
        [sys.executable, "-m", "btd.btd"],
        [sys.executable, "-m", "spid.spid"],
        [sys.executable, "-m", "sessiond.sessiond"],
    ]
    for command in module_commands:
        _run_help(command, env=env)

    _run_help([sys.executable, "daemon/http/httpd.py"], env=env)


def test_native_and_helper_command_help_surfaces() -> None:
    subprocess.run(["make", "-C", str(ROOT / "daemon" / "matrixd")], cwd=ROOT, check=True)
    matrix_help = _run_help([str(ROOT / "daemon" / "matrixd" / "matrixd")])
    assert "CONFIG_JSON" in matrix_help

    subprocess.run(["make", "-C", str(ROOT / "tools" / "hidloom_send")], cwd=ROOT, check=True)
    for name in ["hidloom-key", "hidloom-keytext", "hidloom-oled", "hidloom-notify", "hidloom-ctrl"]:
        _run_help([str(ROOT / "tools" / "hidloom_send" / ".build" / name)])


def test_rust_release_commands_keep_help_entrypoints() -> None:
    rust_sources = {
        "tools/hidloom_hidd/src/main.rs": "usage: hidloom-hidd",
        "tools/hidloom_uidd/src/main.rs": "usage: hidloom-uidd",
        "tools/hidloom_outputd/src/main.rs": "usage: hidloom-outputd",
        "tools/hidloom_logicd_core/src/main.rs": "usage: hidloom-logicd-core",
    }
    for rel, usage in rust_sources.items():
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "--help" in text, rel
        assert usage in text, rel


if __name__ == "__main__":
    test_python_daemon_help_exits_before_runtime_start()
    test_native_and_helper_command_help_surfaces()
    test_rust_release_commands_keep_help_entrypoints()
    print("ok: command help surfaces are available")
