#!/usr/bin/env python3
"""Select and install a touch-panel keymap profile from the active display size."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hidloom_paths import default_config_dir, runtime_dir as default_runtime_dir  # noqa: E402

PROFILE_ALIASES = {
    "auto": "auto",
    "waveshare-8.8": "waveshare-8.8",
    "waveshare-8.8-1920x480": "waveshare-8.8",
    "8.8": "waveshare-8.8",
    "1920x480": "waveshare-8.8",
    "osoyoo-4.3": "osoyoo-4.3",
    "osoyoo-4.3-800x480": "osoyoo-4.3",
    "4.3": "osoyoo-4.3",
    "800x480": "osoyoo-4.3",
}


def normalize_profile(value: str) -> str:
    key = str(value or "auto").strip().lower()
    try:
        return PROFILE_ALIASES[key]
    except KeyError as exc:
        known = ", ".join(sorted({"auto", "waveshare-8.8", "osoyoo-4.3"}))
        raise ValueError(f"unknown touch panel profile {value!r}; known profiles: {known}") from exc


def parse_size(value: str) -> tuple[int, int] | None:
    match = re.search(r"(\d{3,5})\s*x\s*(\d{3,5})", value)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def env_flag(name: str, default: str = "0") -> bool:
    value = os.environ.get(name, default).strip().lower()
    return value in {"1", "true", "yes", "on", "enabled"}


def display_sizes(sys_root: Path = Path("/sys")) -> list[tuple[int, int, str]]:
    sizes: list[tuple[int, int, str]] = []
    env_size = os.environ.get("HIDLOOM_TOUCH_PANEL_SIZE", "")
    parsed = parse_size(env_size)
    if parsed is not None:
        sizes.append((parsed[0], parsed[1], "env:HIDLOOM_TOUCH_PANEL_SIZE"))

    for path in sorted((sys_root / "class" / "drm").glob("*/modes")):
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                parsed = parse_size(line)
                if parsed is not None:
                    sizes.append((parsed[0], parsed[1], str(path)))
        except OSError:
            continue

    for path in sorted((sys_root / "class" / "graphics").glob("fb*/virtual_size")):
        try:
            text = path.read_text(encoding="utf-8").strip().replace(",", "x")
        except OSError:
            continue
        parsed = parse_size(text)
        if parsed is not None:
            sizes.append((parsed[0], parsed[1], str(path)))

    if sys_root == Path("/sys") and env_flag("HIDLOOM_TOUCH_PANEL_COMMAND_PROBES"):
        for command in (["wlr-randr"], ["kmsprint"]):
            try:
                proc = subprocess.run(
                    command,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    timeout=2.0,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            for line in proc.stdout.splitlines():
                parsed = parse_size(line)
                if parsed is not None:
                    source = command[0]
                    if command[0] == "wlr-randr" and "current" in line.lower():
                        source = "wlr-randr:current"
                    elif command[0] == "kmsprint" and "Crtc" in line:
                        source = "kmsprint:crtc"
                    sizes.append((parsed[0], parsed[1], source))

    return sizes


def profile_from_size(width: int, height: int) -> str:
    w, h = max(width, height), min(width, height)
    if w >= 1600 and h <= 600:
        return "waveshare-8.8"
    if w <= 900 and h <= 600:
        return "osoyoo-4.3"
    return "waveshare-8.8"


def select_profile(requested: str, sizes: list[tuple[int, int, str]]) -> tuple[str, str]:
    requested = normalize_profile(requested)
    if requested != "auto":
        return requested, "explicit"
    if not sizes:
        return "waveshare-8.8", "fallback:no-display-size"
    top_priority = max(source_priority(source) for _width, _height, source in sizes)
    candidates = [item for item in sizes if source_priority(item[2]) == top_priority]
    if top_priority <= 1:
        compact = [item for item in candidates if profile_from_size(item[0], item[1]) == "osoyoo-4.3"]
        if compact:
            candidates = compact
    width, height, source = max(candidates, key=lambda item: item[0] * item[1])
    return profile_from_size(width, height), f"auto:{width}x{height}:{source}"


def source_priority(source: str) -> int:
    if source.startswith("env:"):
        return 3
    if source in {"kmsprint:crtc", "wlr-randr:current"}:
        return 2
    return 1


def profile_dir(repo_root: Path, profile: str) -> Path:
    conf_dir = default_config_dir(repo_root)
    if profile == "waveshare-8.8":
        return conf_dir / "touch-panel"
    if profile == "osoyoo-4.3":
        return conf_dir / "touch-panel" / "osoyoo-4.3"
    raise ValueError(f"unsupported profile: {profile}")


def install_profile(repo_root: Path, runtime_dir: Path, profile: str, reason: str, sizes: list[tuple[int, int, str]]) -> None:
    src = profile_dir(repo_root, profile)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src / "keymap.json", runtime_dir / "keymap.json")
    shutil.copy2(src / "keyboard-layout.json", runtime_dir / "keyboard-layout.json")
    shutil.copy2(src / "vial.json", runtime_dir / "vial.json")
    flick_src = src / "flick.json"
    flick_dst = runtime_dir / "flick.json"
    if flick_src.exists():
        shutil.copy2(flick_src, flick_dst)
        os.chmod(flick_dst, 0o644)
    elif flick_dst.exists():
        flick_dst.unlink()
    os.chmod(runtime_dir / "keymap.json", 0o644)
    os.chmod(runtime_dir / "keyboard-layout.json", 0o644)
    os.chmod(runtime_dir / "vial.json", 0o644)
    metadata = {
        "profile": profile,
        "reason": reason,
        "sizes": [{"width": w, "height": h, "source": source} for w, h, source in sizes],
    }
    (runtime_dir / "touch_panel_profile.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def requested_profile(args: argparse.Namespace) -> str:
    if args.profile != "auto":
        return args.profile
    if args.profile_file is not None:
        try:
            value = args.profile_file.read_text(encoding="utf-8").strip()
            if value:
                return value
        except OSError:
            pass
    return os.environ.get("HIDLOOM_TOUCH_PANEL_PROFILE", "auto")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--runtime-dir", type=Path, default=default_runtime_dir())
    parser.add_argument("--profile", default="auto")
    parser.add_argument("--profile-file", type=Path)
    parser.add_argument("--sys-root", type=Path, default=Path("/sys"))
    args = parser.parse_args()

    sizes = display_sizes(args.sys_root)
    profile, reason = select_profile(requested_profile(args), sizes)
    install_profile(args.repo_root, args.runtime_dir, profile, reason, sizes)
    print(f"touch panel profile: {profile} ({reason})")


if __name__ == "__main__":
    main()
