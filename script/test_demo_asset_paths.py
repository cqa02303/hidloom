#!/usr/bin/env python3
"""Keep demo asset preparation and KC_SH2 playback paths aligned."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from demo import prepare_led_video  # noqa: E402
from demo.prepare_led_video import DEFAULT_ASSETS_DIR, DEMO_SOURCES  # noqa: E402
from tools.demo.play_led_video import DEFAULT_VIDEO  # noqa: E402


def assert_local_input_does_not_require_ytdlp() -> None:
    required: list[str] = []
    commands: list[list[str]] = []
    old_argv = sys.argv
    old_require_command = prepare_led_video.require_command
    old_run = prepare_led_video.run
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "source.mp4"
            source.write_bytes(b"not a real mp4; command execution is mocked")
            assets = tmp_path / "assets"
            sys.argv = [
                "prepare_led_video.py",
                "--input",
                str(source),
                "--assets-dir",
                str(assets),
            ]
            prepare_led_video.require_command = required.append
            prepare_led_video.run = commands.append
            prepare_led_video.main()
            assert source.exists()
    finally:
        sys.argv = old_argv
        prepare_led_video.require_command = old_require_command
        prepare_led_video.run = old_run

    assert required == ["ffmpeg"]
    assert len(commands) == 1
    assert commands[0][0] == "ffmpeg"
    assert "yt-dlp" not in commands[0]


def main() -> None:
    output_name = DEMO_SOURCES["default"]["output"]
    expected = ROOT / "demo" / "assets" / output_name
    kc_sh1 = (ROOT / "config" / "default" / "script" / "KC_SH1.sh").read_text(encoding="utf-8")
    kc_sh2 = (ROOT / "config" / "default" / "script" / "KC_SH2.sh").read_text(encoding="utf-8")
    readme = (ROOT / "demo" / "README.md").read_text(encoding="utf-8")

    assert DEFAULT_ASSETS_DIR == ROOT / "demo" / "assets"
    assert DEFAULT_VIDEO == expected
    assert f'demo/assets/{output_name}' in readme
    assert f'VIDEO="${{REPO_DIR}}/demo/assets/{output_name}"' in kc_sh2
    assert 'if [ -n "${HIDLOOM_REPO_ROOT:-}" ]; then' in kc_sh1
    assert 'if [ -n "${HIDLOOM_REPO_ROOT:-}" ]; then' in kc_sh2
    assert 'REPO_DIR="$HIDLOOM_REPO_ROOT"' in kc_sh1
    assert 'REPO_DIR="$HIDLOOM_REPO_ROOT"' in kc_sh2
    assert "${HIDLOOM_REPO_ROOT:-${HIDLOOM_REPO_ROOT" not in kc_sh1
    assert "${HIDLOOM_REPO_ROOT:-${HIDLOOM_REPO_ROOT" not in kc_sh2
    assert "/home/USERNAME/hidloom" not in kc_sh1
    assert "/home/USERNAME/hidloom" not in kc_sh2
    assert "--backend ledd-direct" in kc_sh2
    assert "--max-brightness" in kc_sh2
    assert "PREVIOUS_LED_STATE_FILE" in kc_sh1
    assert "PREVIOUS_LED_STATE_FILE" in kc_sh2
    assert 'SAVED_LED_STATE_FILE="${LED_VIDEO_SAVED_STATE_FILE:-/mnt/p3/led_state.json}"' in kc_sh2
    assert "restore_previous_led_state" in kc_sh1
    assert "restore_previous_led_state" in kc_sh2
    assert "vialrgb_reset" in kc_sh1
    assert "vialrgb_reset" in kc_sh2
    assert '"op": "vialrgb"' in kc_sh1
    assert '"op": "vialrgb"' in kc_sh2
    assert '"mode": mode' in kc_sh1
    assert '"mode": mode' in kc_sh2
    assert 'DIRECT_MULTISPLASH_MODE="${LED_VIDEO_VIALRGB_MODE:-1002}"' in kc_sh2
    assert 'if int(saved.get("mode", -1)) == mode:' in kc_sh2
    assert '"speed": byte_env("LED_VIDEO_VIALRGB_SPEED", speed)' in kc_sh2
    assert '"save": False' in kc_sh2
    assert "LED_VIDEO_LOG:-/tmp/hidloom_led_video_demo.log" in kc_sh2
    assert 'command -v hidloom-notify' in kc_sh2
    notify_lines = [line.strip() for line in kc_sh2.splitlines() if line.strip().startswith("notify ")]
    assert notify_lines == [
        'notify alert "LED DEMO STOP" 2',
        'notify warning "LED PLAYER MISSING" 4',
        'notify warning "DIRECT MODE FAILED" 3',
        'notify alert "LED VIDEO START" 2',
        'notify alert "LED PATTERN START" 2',
    ]
    assert all(line.isascii() for line in notify_lines)
    assert 'notify warning "LED RESTORE FAILED" 3' in kc_sh2
    assert 'command -v hidloom-ctrl' in kc_sh2
    assert 'bin/hidloom-notify' not in kc_sh2
    assert "play_led_(video|pattern)" in kc_sh1
    assert "play_led_pattern.py" in kc_sh2
    assert "LED_DEMO_PROC" in kc_sh1
    assert "LED_DEMO_PROC" in kc_sh2
    assert "video unavailable; starting procedural pattern" in kc_sh2
    assert 'import cv2, numpy' in kc_sh2
    assert 'if [ "${DEMO_KIND}" = "video" ]; then' in kc_sh2
    assert "exit 0" in kc_sh2.split('pkill -TERM -f "${LED_DEMO_PROC}"', 1)[1].split("fi", 1)[0]
    assert "--backend direct" not in kc_sh2
    assert "python3 demo/prepare_led_video.py" in readme
    assert "python3 demo/prepare_led_video.py --input /path/to/source.mp4" in readme
    assert "外部動画がなければ依存なしの内蔵 pattern" in kc_sh2
    assert_local_input_does_not_require_ytdlp()
    print("ok: demo asset paths match KC_SH2")


if __name__ == "__main__":
    main()
