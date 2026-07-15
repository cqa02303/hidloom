#!/usr/bin/env python3
"""Download or shrink demo videos for LED playback.

The repository intentionally does not track downloaded video files.  This tool
keeps only source URLs and creates local assets under demo/assets/.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ASSETS_DIR = ROOT / "demo" / "assets"

DEMO_SOURCES = {
    "default": {
        "url": "https://www.youtube.com/watch?v=FtutLA63Cp8",
        "output": "led_video_demo.mp4",
    },
}


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def require_command(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f"missing required command: {name}; install it before preparing demo assets")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare local LED video demo assets")
    parser.add_argument("source", nargs="?", default="default", help="known source name, or use --url")
    parser.add_argument("--input", type=Path, help="local source mp4 to shrink instead of downloading")
    parser.add_argument("--url", help="download URL; overrides the known source URL")
    parser.add_argument("--output", help="output mp4 filename under --assets-dir")
    parser.add_argument("--assets-dir", type=Path, default=DEFAULT_ASSETS_DIR)
    parser.add_argument("--width", type=int, default=180)
    parser.add_argument("--fps", type=float, default=24.0)
    parser.add_argument("--crf", type=int, default=23)
    parser.add_argument("--keep-source", action="store_true", help="keep the downloaded source mp4")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    require_command("ffmpeg")

    known = DEMO_SOURCES.get(args.source, {})
    url = args.url or known.get("url")
    if args.input is None and not url:
        choices = ", ".join(sorted(DEMO_SOURCES))
        raise SystemExit(f"unknown source {args.source!r}; known sources: {choices}; or pass --url")

    output_name = args.output or known.get("output") or f"{args.source}_led.mp4"
    assets_dir = args.assets_dir
    assets_dir.mkdir(parents=True, exist_ok=True)
    output_path = assets_dir / output_name
    downloaded_source_path: Path | None = None

    if args.input is not None:
        source_path = args.input
        if not source_path.is_file():
            raise SystemExit(f"input mp4 not found: {source_path}")
    else:
        require_command("yt-dlp")
        source_path = assets_dir / f"{Path(output_name).stem}.source.mp4"
        downloaded_source_path = source_path

        run([
            "yt-dlp",
            "-f",
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4",
            "--merge-output-format",
            "mp4",
            "-o",
            str(source_path),
            url,
        ])
    vf = (
        f"scale={args.width}:-2:flags=bicubic,"
        "eq=contrast=1.3:saturation=1.6:brightness=0.02,"
        "curves=preset=strong_contrast"
    )
    run([
        "ffmpeg",
        "-y",
        "-i",
        str(source_path),
        "-vf",
        vf,
        "-r",
        str(args.fps),
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        str(args.crf),
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-colorspace",
        "bt709",
        str(output_path),
    ])
    if downloaded_source_path is not None and not args.keep_source:
        downloaded_source_path.unlink(missing_ok=True)
    print(f"prepared: {output_path}")


if __name__ == "__main__":
    main()
