#!/usr/bin/env python3
"""Keep OLED alert producers compatible with the ASCII-only font."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))

from oled_text import ascii_oled_text  # noqa: E402


def main() -> None:
    assert ascii_oled_text("ASCII\nOK") == "ASCII\nOK"
    assert ascii_oled_text("Wi-Fi 日本\t") == "Wi-Fi ???"

    scripts = sorted((ROOT / "config/default/script").glob("KC_SH*.sh"))
    notify_lines: list[tuple[Path, int, str]] = []
    for path in scripts:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if "hidloom-notify" in line or stripped.startswith(("notify alert ", "notify warning ")):
                notify_lines.append((path, line_number, line))
    assert notify_lines
    assert all(line.isascii() for _path, _line_number, line in notify_lines), notify_lines

    producer_files = (
        ROOT / "daemon/logicd/input_events.py",
        ROOT / "daemon/logicd/lighting.py",
        ROOT / "daemon/logicd/logicd.py",
        ROOT / "daemon/ledd/ledd.py",
    )
    for path in producer_files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function_name = ""
            if isinstance(node.func, ast.Name):
                function_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                function_name = node.func.attr
            if function_name not in {"push_i2cd_alert", "push_alert"}:
                continue
            for argument in node.args:
                values: list[str] = []
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    values.append(argument.value)
                elif isinstance(argument, ast.JoinedStr):
                    values.extend(
                        part.value
                        for part in argument.values
                        if isinstance(part, ast.Constant) and isinstance(part.value, str)
                    )
                assert all(value.isascii() for value in values), (path, node.lineno, values)

    runtime_notifications = (ROOT / "daemon/logicd/runtime_notifications.py").read_text(encoding="utf-8")
    i2cd = (ROOT / "daemon/i2cd/i2cd.py").read_text(encoding="utf-8")
    assert "message = ascii_oled_text(message)" in runtime_notifications
    assert "incoming_alert = ascii_oled_text(raw_alert)" in i2cd
    print("ok: OLED alert producers are ASCII-safe")


if __name__ == "__main__":
    main()
