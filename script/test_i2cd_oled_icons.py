#!/usr/bin/env python3
"""Static tests for small OLED connectivity icons."""
from __future__ import annotations

from pathlib import Path
import os
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from i2cd.icons import (  # noqa: E402
    AUTO_ICON_8X8,
    BITMAP_FILE,
    BT_ICON_8X8,
    CONNECTIVITY_ICONS,
    HIDD_ICON_8X8,
    OLED_ICONS,
    BTD_ICON_8X8,
    HTTPD_ICON_8X8,
    LEDD_ICON_8X8,
    LOGICD_COMPANION_ICON_8X8,
    LOGICD_CORE_ICON_8X8,
    LOGICD_ICON_8X8,
    MATRIXD_ICON_8X8,
    OUTPUTD_ICON_8X8,
    PI_ICON_8X8,
    USB_ICON_8X8,
    UIDD_ICON_8X8,
    VIALD_ICON_8X8,
    WIFI_LEVEL_0_8X8,
    WIFI_LEVEL_3_8X8,
    OledIcon,
    icon_bitmap,
    reload_icon_bitmaps,
)


def main() -> None:
    expected = {
        "bt",
        "usb",
        "pi",
        "auto",
        "wifi0",
        "wifi3",
        "mtx",
        "core",
        "cmp",
        "lgc",
        "led",
        "out",
        "uid",
        "btd",
        "http",
        "web",
        "usbd",
        "hid",
        "vial",
    }
    assert set(CONNECTIVITY_ICONS) == expected, sorted(CONNECTIVITY_ICONS)
    assert OLED_ICONS is CONNECTIVITY_ICONS

    for name, icon in CONNECTIVITY_ICONS.items():
        assert isinstance(icon, OledIcon), name
        assert icon.height == 8, name
        assert len(icon.rows) == 8, name
        assert 1 <= icon.width <= 8, name
        assert all(len(row) == icon.width for row in icon.rows), name
        assert all(ch in {"0", "1"} for row in icon.rows for ch in row), name
        assert icon.pixels(), f"empty icon: {name}"

    assert icon_bitmap("bt") is BT_ICON_8X8
    assert icon_bitmap("usb") is USB_ICON_8X8
    assert icon_bitmap("pi") is PI_ICON_8X8
    assert icon_bitmap("auto") is AUTO_ICON_8X8
    assert icon_bitmap("wifi0") is WIFI_LEVEL_0_8X8
    assert icon_bitmap("wifi3") is WIFI_LEVEL_3_8X8
    assert icon_bitmap("mtx") is MATRIXD_ICON_8X8
    assert icon_bitmap("core") is LOGICD_CORE_ICON_8X8
    assert icon_bitmap("cmp") is LOGICD_COMPANION_ICON_8X8
    assert icon_bitmap("lgc") is LOGICD_ICON_8X8
    assert icon_bitmap("led") is LEDD_ICON_8X8
    assert icon_bitmap("out") is OUTPUTD_ICON_8X8
    assert icon_bitmap("uid") is UIDD_ICON_8X8
    assert icon_bitmap("btd") is BTD_ICON_8X8
    assert icon_bitmap("http") is HTTPD_ICON_8X8
    assert icon_bitmap("web") is HTTPD_ICON_8X8
    assert icon_bitmap("usbd") is HIDD_ICON_8X8
    assert icon_bitmap("hid") is HIDD_ICON_8X8
    assert icon_bitmap("vial") is VIALD_ICON_8X8

    widths = {name: icon.width for name, icon in CONNECTIVITY_ICONS.items()}
    assert widths == {
        "bt": 6,
        "usb": 7,
        "pi": 5,
        "auto": 7,
        "wifi0": 6,
        "wifi3": 6,
        "mtx": 8,
        "core": 8,
        "cmp": 8,
        "lgc": 8,
        "led": 8,
        "out": 8,
        "uid": 8,
        "btd": 8,
        "http": 8,
        "web": 8,
        "usbd": 8,
        "hid": 8,
        "vial": 8,
    }, widths
    daemon_icon_names = {"mtx", "core", "cmp", "out", "uid", "led", "btd", "web", "hid", "vial"}
    assert {name: widths[name] for name in daemon_icon_names} == {name: 8 for name in daemon_icon_names}

    original_bt_rows = BT_ICON_8X8.rows

    bitmap_source = BITMAP_FILE.read_text(encoding="utf-8")
    bitmap_names = expected - {"http", "usbd"}
    for name in bitmap_names:
        assert f"# {name}:" in bitmap_source, name
        assert f"{name}:" in bitmap_source, name
    assert "connection and daemon status rows" in bitmap_source
    assert "1 = lit pixel, 0 = off pixel" in bitmap_source

    assert len(WIFI_LEVEL_0_8X8.pixels()) < len(WIFI_LEVEL_3_8X8.pixels())

    try:
        OledIcon("bad", 2, 1, ("101",))
    except ValueError:
        pass
    else:
        raise AssertionError("expected invalid row width to fail")

    try:
        icon_bitmap("missing")
    except KeyError:
        pass
    else:
        raise AssertionError("expected missing icon to fail")

    with tempfile.TemporaryDirectory() as tmpdir:
        bitmap_copy = Path(tmpdir) / "connectivity_icon_bitmaps.txt"
        bitmap_copy.write_text(bitmap_source, encoding="utf-8")
        reload_icon_bitmaps(bitmap_copy)
        assert icon_bitmap("bt").rows == original_bt_rows

        changed_source = bitmap_source.replace("bt:\n001000", "bt:\n111111", 1)
        changed_source = changed_source.replace("btd:\n00011000", "btd:\n11111111", 1)
        bitmap_copy.write_text(changed_source, encoding="utf-8")
        mtime = time.time() + 1.0
        os.utime(bitmap_copy, (mtime, mtime))
        assert icon_bitmap("bt").rows[0] == "111111"
        assert icon_bitmap("btd").rows[0] == "11111111"

    reload_icon_bitmaps(BITMAP_FILE)
    assert icon_bitmap("bt").rows == original_bt_rows

    print("ok: OLED connectivity icons")


if __name__ == "__main__":
    main()
