#!/usr/bin/env python3
"""Generate a keycode action inventory from config/default/keycodes.json."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KEYCODES = ROOT / "config" / "default" / "keycodes.json"
DEFAULT_DOC = ROOT / "docs" / "keycode" / "action-inventory.md"

MODIFIER_HID = set(range(224, 232))
MOUSE_HID = set(range(512, 528))
LOCAL_HID_MIN = 960


LOCAL_COMMAND_PREFIXES = (
    "KC_SH",
    "BT_",
    "WIFI_",
)
LOCAL_COMMAND_NAMES = {
    "KC_CONNAUTO",
    "KC_CONSOLE",
    "KC_USB",
    "KC_BT",
    "KC_SHUTDOWN",
    "KC_ZKHK",
    "KC_ZENKAKU_HANKAKU",
}


def classify(action: str, entry: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    page = str(entry.get("page") or "keyboard")
    hid = entry.get("hid")
    linux = entry.get("linux")
    hid_int = int(hid) if isinstance(hid, int) else None

    if action in {"KC_NONE", "KC_TRNS"}:
        return ("no-op", "none", "internal", "no", "no", "no")

    if action in LOCAL_COMMAND_NAMES or action.startswith(LOCAL_COMMAND_PREFIXES):
        return ("local_command", "none", "internal", "no", "no", "no")

    if page == "consumer":
        uinput = "yes" if linux is not None else "no"
        return ("consumer", "consumer", "send", "consumer", uinput, "consumer")

    if hid_int in MOUSE_HID:
        return ("mouse", "mouse", "send", "mouse", "partial", "mouse")

    if hid_int in MODIFIER_HID:
        uinput = "yes" if linux is not None else "no"
        return ("modifier", "keyboard", "send", "keyboard", uinput, "keyboard")

    if hid_int is not None and hid_int >= LOCAL_HID_MIN:
        return ("local_command", "none", "internal", "no", "no", "no")

    uinput = "yes" if linux is not None else "no"
    return ("keyboard", "keyboard", "send", "keyboard", uinput, "keyboard")


def markdown_escape(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|")


def canonical_groups(keycodes: dict[str, Any]) -> dict[str, str]:
    canonical_by_group: dict[tuple[object, ...], str] = {}
    canonical_by_action: dict[str, str] = {}
    for action, entry in keycodes.items():
        if action.startswith("_") or not isinstance(entry, dict):
            continue
        category, hid_page, *_ = classify(action, entry)
        if action in {"KC_NONE", "KC_TRNS"}:
            group = ("semantic-no-op", action)
        elif category == "local_command":
            group = (category, entry.get("hid"))
        else:
            group = (category, hid_page, entry.get("page") or "keyboard", entry.get("hid"), entry.get("linux"))
        canonical = canonical_by_group.setdefault(group, action)
        canonical_by_action[action] = canonical
    return canonical_by_action


def iter_rows(keycodes: dict[str, Any]) -> list[list[str]]:
    rows: list[list[str]] = []
    canonical_by_action = canonical_groups(keycodes)
    for action in sorted(k for k in keycodes if not k.startswith("_")):
        entry = keycodes[action]
        if not isinstance(entry, dict):
            continue
        category, hid_page, logicd, usb, uinput, bt = classify(action, entry)
        logicd_core = "keyboard_page" if category in {"keyboard", "modifier"} else "not_in_m0"
        canonical = canonical_by_action.get(action, action)
        rows.append(
            [
                action,
                "" if canonical == action else canonical,
                category,
                hid_page,
                str(entry.get("hid", "")),
                "null" if entry.get("linux") is None else str(entry.get("linux")),
                logicd,
                logicd_core,
                usb,
                uinput,
                bt,
                "",
            ]
        )
    return rows


def render_markdown(rows: list[list[str]]) -> str:
    header = [
        "action",
        "canonical",
        "category",
        "hid_page",
        "hid_usage",
        "linux_code",
        "logicd",
        "logicd_core_rs",
        "usb",
        "uinput",
        "bt",
        "special_notes",
    ]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(markdown_escape(cell) for cell in row) + " |")
    return "\n".join(lines) + "\n"


def render_document(rows: list[list[str]]) -> str:
    return (
        "# Keycode action inventory\n\n"
        "この文書は `config/default/keycodes.json` から生成した action 完全一覧です。\n"
        "分類と出力先ごとの読み方は [action-routing-matrix.md](action-routing-matrix.md) を参照してください。\n\n"
        "更新する時は次を実行します。\n\n"
        "```bash\n"
        "python3 tools/keycode_action_inventory.py --document --output docs/keycode/action-inventory.md\n"
        "```\n\n"
        + render_markdown(rows)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keycodes", type=Path, default=DEFAULT_KEYCODES)
    parser.add_argument("--output", type=Path, help="write Markdown to this path")
    parser.add_argument("--document", action="store_true", help="include a document header around the table")
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if --output differs from generated content; defaults to docs/keycode/action-inventory.md",
    )
    args = parser.parse_args()

    keycodes = json.loads(args.keycodes.read_text(encoding="utf-8"))
    rows = iter_rows(keycodes)
    content = render_document(rows) if args.document else render_markdown(rows)
    output = args.output or (DEFAULT_DOC if args.check else None)
    if args.check:
        if output is None:
            raise SystemExit("--check requires --output or the default docs path")
        current = output.read_text(encoding="utf-8")
        if current != content:
            raise SystemExit(f"generated inventory is stale: {output}")
    elif output:
        output.write_text(content, encoding="utf-8")
    else:
        print(content, end="")


if __name__ == "__main__":
    main()
