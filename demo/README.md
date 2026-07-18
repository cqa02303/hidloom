# LED video demo assets

`demo/assets/` is for local video files used by LED playback demos.  Downloaded
videos are intentionally not tracked in git because they may be copyrighted.

`yt-dlp` and `ffmpeg` are required to prepare the local mp4:

```bash
sudo apt install yt-dlp ffmpeg
```

Prepare the default demo asset with:

```bash
python3 demo/prepare_led_video.py
```

This downloads the configured Bad Apple sample URL, shrinks it for LED
playback, and writes the local asset to:

```text
demo/assets/led_video_demo.mp4
```

To keep the original downloaded mp4 for inspection, pass `--keep-source`:

```bash
python3 demo/prepare_led_video.py --keep-source
```

If the URL cannot be downloaded without browser cookies, shrink a local mp4
instead:

```bash
python3 demo/prepare_led_video.py --input /path/to/source.mp4
```

Then play it with:

```bash
python3 tools/demo/play_led_video.py --backend ledd-direct --max-brightness 64
```

`--max-brightness` caps the brightest RGB channel of each sampled LED after
video scaling.  Lower values reduce peak LED current during bright video
frames; `KC_SH2.sh` uses `64` by default and can be overridden with
`LED_VIDEO_MAX_BRIGHTNESS`.

When launched through `KC_SH2.sh` (F2), playback first selects VialRGB mode
`1002` (`Direct Multisplash`) with `save:false`, then streams the video through
the `ledd-direct` socket.  If `/mnt/p3/led_state.json` currently stores mode
`1002`, its `speed` / `h` / `s` / `v` values are reused; environment variables
such as `LED_VIDEO_VIALRGB_SPEED` can still override them.  This keeps the
video as the base frame and overlays key-triggered multisplash without changing
the saved lighting preset.

If the local video or its OpenCV/NumPy dependencies are unavailable, `KC_SH2.sh`
automatically starts the tracked procedural player in `tools/demo/play_led_pattern.py`.
The fallback uses only the Python standard library and the packaged HIDloom
direct-frame protocol, so a clean package installation still provides a visible
LED demo. Press `KC_SH2` again to stop either player and restore the previous
lighting state.

Known source URLs live in `demo/prepare_led_video.py`.  Add new demo
sources there instead of committing mp4 files.
