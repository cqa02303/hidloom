"""Small editable 1-bit OLED icon definitions for i2cd.

Connection and daemon status icons share the same editable 0/1 bitmap file so
they can be tuned by eye without touching Python code.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path

from .oled_customization import icon_payload as serialize_icon_payload
from .oled_customization import load_effective_document

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class OledIcon:
    name: str
    width: int
    height: int
    rows: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.rows) != self.height:
            raise ValueError(f"{self.name}: expected {self.height} rows, got {len(self.rows)}")
        for row in self.rows:
            if len(row) != self.width:
                raise ValueError(f"{self.name}: expected row width {self.width}, got {len(row)}")
            if any(ch not in {"0", "1"} for ch in row):
                raise ValueError(f"{self.name}: icon rows must contain only 0/1")

    def pixels(self) -> tuple[tuple[int, int], ...]:
        result: list[tuple[int, int]] = []
        for y, row in enumerate(self.rows):
            for x, ch in enumerate(row):
                if ch == "1":
                    result.append((x, y))
        return tuple(result)


BITMAP_FILE = Path(__file__).with_name("connectivity_icon_bitmaps.txt")
_ICON_BITMAPS_MTIME_NS = -1
_ICON_BITMAPS_SOURCE = BITMAP_FILE


def _load_icon_bitmaps(path: Path = BITMAP_FILE) -> dict[str, OledIcon]:
    icons: dict[str, OledIcon] = {}
    current_name: str | None = None
    rows: list[str] = []

    def flush() -> None:
        nonlocal current_name, rows
        if current_name is None:
            return
        if not rows:
            raise ValueError(f"{path}: empty icon: {current_name}")
        width = len(rows[0])
        icons[current_name] = OledIcon(
            name=f"{current_name}-{width}x{len(rows)}",
            width=width,
            height=len(rows),
            rows=tuple(rows),
        )
        current_name = None
        rows = []

    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith(":"):
            flush()
            current_name = line[:-1].strip()
            if not current_name:
                raise ValueError(f"{path}:{lineno}: empty icon name")
            if current_name in icons:
                raise ValueError(f"{path}:{lineno}: duplicate icon name: {current_name}")
            continue
        if current_name is None:
            raise ValueError(f"{path}:{lineno}: bitmap row before icon name")
        rows.append(line)
    flush()
    return icons


def _file_mtime_ns(path: Path) -> int:
    return path.stat().st_mtime_ns


def reload_icon_bitmaps(path: Path = BITMAP_FILE) -> None:
    """Reload editable OLED icon bitmaps from disk."""

    global _ICON_BITMAPS, _ICON_BITMAPS_MTIME_NS, _ICON_BITMAPS_SOURCE, _RUNTIME_ICON_SIGNATURE

    icons = _load_icon_bitmaps(path)
    _ICON_BITMAPS = icons
    _ICON_BITMAPS_MTIME_NS = _file_mtime_ns(path)
    _ICON_BITMAPS_SOURCE = path
    _RUNTIME_ICON_SIGNATURE = None
    _publish_icon_bitmaps(icons)


def _refresh_icon_bitmaps_if_changed() -> None:
    global _ICON_BITMAPS_MTIME_NS

    try:
        mtime_ns = _file_mtime_ns(_ICON_BITMAPS_SOURCE)
    except OSError as exc:
        log.warning("failed to stat OLED icon bitmap file %s: %s", _ICON_BITMAPS_SOURCE, exc)
        return

    if mtime_ns == _ICON_BITMAPS_MTIME_NS:
        return

    try:
        reload_icon_bitmaps(_ICON_BITMAPS_SOURCE)
    except (OSError, ValueError) as exc:
        log.warning("failed to reload OLED icon bitmap file %s: %s", _ICON_BITMAPS_SOURCE, exc)
        _ICON_BITMAPS_MTIME_NS = mtime_ns


_ICON_BITMAPS = _load_icon_bitmaps()
_ICON_BITMAPS_MTIME_NS = _file_mtime_ns(BITMAP_FILE)

BT_ICON_8X8 = _ICON_BITMAPS["bt"]
USB_ICON_8X8 = _ICON_BITMAPS["usb"]
PI_ICON_8X8 = _ICON_BITMAPS["pi"]
AUTO_ICON_8X8 = _ICON_BITMAPS["auto"]
WIFI_LEVEL_0_8X8 = _ICON_BITMAPS["wifi0"]
WIFI_LEVEL_3_8X8 = _ICON_BITMAPS["wifi3"]
MATRIXD_ICON_8X8 = _ICON_BITMAPS["mtx"]
LOGICD_CORE_ICON_8X8 = _ICON_BITMAPS["core"]
LOGICD_COMPANION_ICON_8X8 = _ICON_BITMAPS["cmp"]
LOGICD_ICON_8X8 = _ICON_BITMAPS["lgc"]
LEDD_ICON_8X8 = _ICON_BITMAPS["led"]
OUTPUTD_ICON_8X8 = _ICON_BITMAPS["out"]
UIDD_ICON_8X8 = _ICON_BITMAPS["uid"]
BTD_ICON_8X8 = _ICON_BITMAPS["btd"]
HTTPD_ICON_8X8 = _ICON_BITMAPS["web"]
HIDD_ICON_8X8 = _ICON_BITMAPS["hid"]
USBD_ICON_8X8 = HIDD_ICON_8X8
VIALD_ICON_8X8 = _ICON_BITMAPS["vial"]

CONNECTIVITY_ICONS: dict[str, OledIcon] = {}
OLED_ICONS = CONNECTIVITY_ICONS
_RUNTIME_ICON_SIGNATURE: tuple | None = None


def _publish_icon_bitmaps(icons: dict[str, OledIcon]) -> None:
    published = dict(icons)
    published["http"] = icons["web"]
    published["usbd"] = icons["hid"]
    CONNECTIVITY_ICONS.clear()
    CONNECTIVITY_ICONS.update(published)


def default_icon_payload() -> dict[str, dict]:
    return serialize_icon_payload(_ICON_BITMAPS)


def _refresh_runtime_icon_bitmaps() -> None:
    global _RUNTIME_ICON_SIGNATURE

    document, source, errors = load_effective_document(_ICON_BITMAPS)
    signature = (
        source,
        tuple(errors),
        tuple(
            (name, icon["width"], icon["height"], tuple(icon["rows"]))
            for name, icon in document["icons"].items()
        ),
    )
    if signature == _RUNTIME_ICON_SIGNATURE:
        return
    effective: dict[str, OledIcon] = {}
    for name, payload in document["icons"].items():
        base = _ICON_BITMAPS[name]
        rows = tuple(payload["rows"])
        if base.width == payload["width"] and base.height == payload["height"] and base.rows == rows:
            effective[name] = base
        else:
            effective[name] = OledIcon(
                name=f"{name}-{payload['width']}x{payload['height']}",
                width=payload["width"],
                height=payload["height"],
                rows=rows,
            )
    _publish_icon_bitmaps(effective)
    _RUNTIME_ICON_SIGNATURE = signature
    if errors:
        log.warning("invalid OLED customization; using packaged icons: %s", "; ".join(errors))


_publish_icon_bitmaps(_ICON_BITMAPS)


def icon_bitmap(name: str) -> OledIcon:
    _refresh_icon_bitmaps_if_changed()
    _refresh_runtime_icon_bitmaps()
    try:
        return CONNECTIVITY_ICONS[name]
    except KeyError as exc:
        raise KeyError(f"unknown OLED icon: {name}") from exc


def draw_icon_pixels(draw, icon: OledIcon, x: int, y: int, *, fill="white") -> None:
    """Draw an OledIcon on a luma/PIL draw object using single pixels."""

    for dx, dy in icon.pixels():
        draw.point((x + dx, y + dy), fill=fill)
