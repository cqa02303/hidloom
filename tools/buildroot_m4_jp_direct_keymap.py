#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    data = json.loads(args.source.read_text(encoding="utf-8"))
    replacements = {
        "LT(1,KC_LANG2)": "KC_LANG2",
        "LT(2,KC_LANG1)": "KC_LANG1",
    }
    changed = 0
    for layer in data.get("layers", []):
        for actions in layer.values():
            if not isinstance(actions, list):
                continue
            for index, action in enumerate(actions):
                if action in replacements:
                    actions[index] = replacements[action]
                    changed += 1
    if changed != len(replacements):
        raise SystemExit(f"expected {len(replacements)} replacements, found {changed}")
    args.destination.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
