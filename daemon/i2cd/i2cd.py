"""
i2cd.py — SH1107 OLED 表示デーモン

起動シーケンス:
  1. Boot フェーズ: matrixd / logicd の起動状態を systemd で監視して表示
  2. Ready フェーズ: logicd の i2c_events.sock に接続し、
     レイヤー番号・HID出力モード・システム状態をリアルタイム表示

HID出力モード表示:
  - native outputd status を canonical state として定期同期する
  - logicd の {"t":"mode","mode":"gadget"|"bt"|"uinput"|"auto:*"} 通知は fallback にする

表示フォーマット (64×128, SH1107):
  ┌──────────────────────┐
  │ cqa02303v5           │  (node 名、長い場合は2行)
  │ -02                  │
  │ ──────────────────── │
  │ [M][C][P][O][U]      │  (デーモン状態 icon 2段。ready は反転)
  │ [E][B][W][H][V]      │
  │ [USB/BT/Pi/auto/Wi]  │  (接続状態 icon 行。active は反転、off は非表示)
  │ ──────────────────── │
  │ Layer: 0             │  (レイヤー番号)
  │ CPU:12 %             │  (CPU使用率)
  │ T:52 C               │  (CPU温度)
  │ FPS:23.8             │  (direct-frame 実測 FPS)
  │   HH:MM              │  (時刻)
  └──────────────────────┘
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import sys
import signal
import time
import statistics
from pathlib import Path
from typing import Callable, Optional

from hidloom_paths import default_config_file
from oled_text import ascii_oled_text

from .ads1115 import ADS1115Reader, build_ctrl_event, normalize_stick, parse_analog_stick_config, read_stick_volts
from .connectivity import (
    effective_output_display_mode,
    load_outputd_status,
    output_mode_icon_row,
    outputd_display_mode,
    wifi_status,
)
from .icons import default_icon_payload, draw_icon_pixels, icon_bitmap
from .oled_customization import invalidate_cache as invalidate_oled_customization_cache
from .oled_customization import load_effective_document
from .status_display import daemon_status_active, daemon_status_icon_row

# ---------------------------------------------------------------------------
# ログ設定
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s i2cd: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------
_CONF = default_config_file("i2cd.json")

_HELP = f"""usage: python3 -m i2cd.i2cd

OLED/status display daemon.

Options:
  -h, --help    show this help and exit

Configuration:
  default config path: {_CONF}

Environment:
  LOG_LEVEL
"""

if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
    print(_HELP.rstrip())
    raise SystemExit(0)

from luma.core.interface.serial import i2c
from luma.oled.device import sh1107
from luma.core.render import canvas
from luma.core.error import DeviceNotFoundError
from PIL import ImageFont


def _load_conf() -> dict:
    try:
        return json.loads(_CONF.read_text())
    except Exception as e:
        log.warning("設定読み込み失敗 (%s)、デフォルト使用", e)
        return {}

# ---------------------------------------------------------------------------
# OLED 初期化
# ---------------------------------------------------------------------------
class _NullDisplay:
    """OLED が未検出でも i2cd の IPC と状態監視を継続する表示先。"""

    mode = "1"

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.size = (width, height)
        self.bounding_box = (0, 0, width - 1, height - 1)

    def display(self, _image) -> None:
        return

    def cleanup(self) -> None:
        return


class _RecoveringDisplay:
    """OLED display wrapper that retries initialization after display failures."""

    def __init__(
        self,
        device,
        factory: Callable[[], object],
        *,
        cooldown_sec: float = 5.0,
    ) -> None:
        self._device = device
        self._factory = factory
        self._cooldown_sec = max(0.1, float(cooldown_sec))
        self._next_retry_at = 0.0
        self.recovery_count = 0

    def __getattr__(self, name: str):
        return getattr(self._device, name)

    def display(self, image) -> None:
        try:
            self._device.display(image)
            return
        except Exception as exc:
            now = time.monotonic()
            log.warning(
                "OLED display failed; scheduling recovery cooldown=%.1fs count=%d error=%s",
                self._cooldown_sec,
                self.recovery_count + 1,
                exc,
            )
            if now < self._next_retry_at:
                return
            self._next_retry_at = now + self._cooldown_sec
            self._recover(image)

    def _recover(self, image) -> None:
        old_device = self._device
        try:
            self._device = self._factory()
            self.recovery_count += 1
            log.info("OLED display reinitialized after display failure count=%d", self.recovery_count)
            self._device.display(image)
        except Exception as exc:
            log.warning("OLED display recovery attempt failed: %s", exc)
        finally:
            try:
                old_device.cleanup()
            except Exception:
                pass

    def cleanup(self) -> None:
        return self._device.cleanup()


def _open_oled_device(cfg: dict):
    oled = cfg.get("oled", {})
    width = int(oled.get("width", 64))
    height = int(oled.get("height", 128))
    port = int(oled.get("i2c_port", 1))
    address = int(oled.get("address", "0x3C"), 16)
    try:
        serial = i2c(port=port, address=address)
        device = sh1107(
            serial,
            width=width,
            height=height,
            rotate=oled.get("rotate", 0),
        )
        return device
    except (DeviceNotFoundError, OSError) as e:
        log.warning(
            "OLED が見つかりません。Null 表示で継続します: port=%s address=0x%02X (%s)",
            port,
            address,
            e,
        )
        return _NullDisplay(width, height)


def _init_device(cfg: dict):
    oled = cfg.get("oled", {})
    cooldown_sec = float(oled.get("recovery_cooldown_sec", 5.0))
    return _RecoveringDisplay(
        _open_oled_device(cfg),
        lambda: _open_oled_device(cfg),
        cooldown_sec=cooldown_sec,
    )


def _load_font(cfg: dict, size: int = 11) -> ImageFont.ImageFont:
    path = (cfg.get("display") or {}).get("font_path")
    try:
        if path:
            return ImageFont.truetype(path, size)
        for candidate in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
        ]:
            if os.path.exists(candidate):
                return ImageFont.truetype(candidate, size)
    except Exception:
        pass
    return ImageFont.load_default()

# ---------------------------------------------------------------------------
# システム情報取得
# ---------------------------------------------------------------------------
_prev_cpu: tuple[int, int] = (0, 0)
_cpu_samples: list[int] = []
_CPU_SAMPLE_COUNT = 4


def _cpu_percent() -> int:
    """ブロッキングなし: /proc/stat の差分から CPU 使用率を平滑化して返す。"""
    global _prev_cpu, _cpu_samples
    try:
        line = Path("/proc/stat").read_text().splitlines()[0].split()
        vals = [int(x) for x in line[1:]]
        idle = vals[3] + vals[4]
        total = sum(vals)
        if _prev_cpu == (0, 0):
            _prev_cpu = (idle, total)
            return 0
        d_idle = idle - _prev_cpu[0]
        d_total = total - _prev_cpu[1]
        _prev_cpu = (idle, total)
        if d_total == 0:
            sample = _cpu_samples[-1] if _cpu_samples else 0
        else:
            sample = max(0, min(100, int(100 * (1 - d_idle / d_total))))
        _cpu_samples.append(sample)
        if len(_cpu_samples) > _CPU_SAMPLE_COUNT:
            _cpu_samples = _cpu_samples[-_CPU_SAMPLE_COUNT:]
        return int(sum(_cpu_samples) / len(_cpu_samples))
    except Exception:
        return 0


def _cpu_temp() -> float:
    try:
        t = Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()
        return int(t) / 1000.0
    except Exception:
        return 0.0


_svc_cache: dict[str, tuple[bool, float]] = {}
_SVC_TTL = 5.0
_DEFAULT_DIRECT_FRAME_STATUS = "/tmp/ledd_direct_frame_status.json"
_BUSYBOX_SERVICE_PID_FILES = {
    "matrixd": Path("/run/hidloom-matrixd.pid"),
    "logicd-core": Path("/run/hidloom-logicd-core.pid"),
    "logicd-companion": Path("/run/logicd-companion.pid"),
    "outputd": Path("/run/hidloom-outputd.pid"),
    "uidd": Path("/run/hidloom-uidd.pid"),
    "hidd": Path("/run/hidloom-hidd.pid"),
    "i2cd": Path("/run/i2cd.pid"),
    "ledd": Path("/run/ledd.pid"),
}


def _pid_file_active(name: str) -> bool:
    path = _BUSYBOX_SERVICE_PID_FILES.get(name)
    if path is None:
        return False
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
        os.kill(pid, 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


async def _service_active(name: str) -> bool:
    """非同期 + キャッシュ: systemctl is-active をノンブロッキングで呼び出す"""
    now = time.monotonic()
    if name in _svc_cache:
        val, ts = _svc_cache[name]
        if now - ts < _SVC_TTL:
            return val
    try:
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "is-active", name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=2.0)
        result = stdout.decode().strip() == "active"
    except Exception:
        result = _pid_file_active(name)
    _svc_cache[name] = (result, now)
    return result


class _DirectFrameFpsMonitor:
    """Compute a low-rate direct-frame FPS label from ledd's status snapshot."""

    def __init__(self, status_path: str = _DEFAULT_DIRECT_FRAME_STATUS) -> None:
        self.status_path = Path(status_path)
        self._last_applied: int | None = None
        self._last_updated_at: float | None = None
        self._fps: float | None = None

    def label(self) -> str:
        try:
            data = json.loads(self.status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._last_applied = None
            self._last_updated_at = None
            self._fps = None
            return ""

        if not data.get("direct_frame_active"):
            self._last_applied = None
            self._last_updated_at = None
            self._fps = None
            return ""

        try:
            applied = int(data.get("applied_frames", 0))
            updated_at = float(data.get("updated_at", time.time()))
        except (TypeError, ValueError):
            return "FPS:--"

        if self._last_applied is not None and self._last_updated_at is not None:
            d_frames = applied - self._last_applied
            d_time = updated_at - self._last_updated_at
            if d_frames >= 0 and d_time > 0:
                self._fps = d_frames / d_time

        self._last_applied = applied
        self._last_updated_at = updated_at
        if self._fps is None:
            return "FPS:--"
        return f"FPS:{self._fps:4.1f}"

# ---------------------------------------------------------------------------
# 描画
# ---------------------------------------------------------------------------
_HOSTNAME = socket.gethostname()


def _font_line_height(font, fallback: int = 10) -> int:
    try:
        bbox = font.getbbox("Hg")
        return max(1, bbox[3] - bbox[1] + 2)
    except AttributeError:
        return fallback


def _fit_text_to_width(text: str, font, max_width: int) -> str:
    if _text_width(font, text) <= max_width:
        return text
    clipped = ""
    for ch in text:
        if _text_width(font, clipped + ch) > max_width:
            break
        clipped += ch
    return clipped or text[:1]


def _node_name_lines(name: str, font, max_width: int) -> list[str]:
    name = str(name or "").strip() or "node"
    if _text_width(font, name) <= max_width:
        return [name]
    if "-" in name:
        head, tail = name.rsplit("-", 1)
        if head and tail:
            second = f"-{tail}"
            if _text_width(font, head) <= max_width and _text_width(font, second) <= max_width:
                return [head, second]
            first = _fit_text_to_width(head, font, max_width)
            remainder = name[len(first):]
            if first and remainder and _text_width(font, remainder) <= max_width:
                return [first, remainder]
    lines = _wrap_text(name, font, max_width)
    if len(lines) <= 2:
        return lines
    return [lines[0], _fit_text_to_width("".join(lines[1:]), font, max_width)]


def _draw_node_name(draw, font, x: int, y: int, max_width: int) -> int:
    line_h = _font_line_height(font)
    lines = _node_name_lines(_HOSTNAME, font, max_width)[:2]
    for index, line in enumerate(lines):
        draw.text((x, y + index * line_h), line, font=font, fill="white")
    return line_h * len(lines)


def _draw_boot(device, font, matrixd_ok: bool, logicd_ok: bool) -> None:
    """ブート中の状態表示"""
    W, H = device.width, device.height
    with canvas(device) as draw:
        draw.rectangle([(0, 0), (W-1, H-1)], outline="white", fill="black")
        y = 3
        y += _draw_node_name(draw, font, 3, y, W - 6) + 2
        draw.line([(1, y), (W-2, y)], fill="white")
        y += 4

        y += _draw_daemon_status_row(draw, 3, y, {"matrixd": matrixd_ok, "logicd": logicd_ok}, max_width=W - 6)
        draw.line([(1, y), (W-2, y)], fill="black")
        y += 1
        draw.line([(1, y), (W-2, y)], fill="white")
        y += 3

        draw.text((3, y), "Booting...", font=font, fill="white")


def _draw_ready(device, font, layer: int, active: list[int],
                matrixd_ok: bool, logicd_ok: bool, current_mode: str = "",
                fps_label: str = "FPS:--", wifi: dict | None = None,
                daemon_status: dict[str, bool] | None = None,
                system_status: dict | None = None) -> None:
    """通常動作時の状態表示"""
    W, H = device.width, device.height
    if system_status is None:
        system_status = {}
    if daemon_status is None:
        daemon_status = {"matrixd": matrixd_ok, "logicd": logicd_ok}
    ready_items = _ready_layout_items()

    with canvas(device) as draw:
        draw.rectangle([(0, 0), (W-1, H-1)], outline="white", fill="black")
        y = 3
        for item in ready_items:
            if not item["enabled"]:
                continue
            y = _draw_ready_item(
                draw,
                font,
                item["id"],
                x=3,
                y=y,
                max_width=W - 6,
                layer=layer,
                active=active,
                current_mode=current_mode,
                fps_label=fps_label,
                wifi=wifi,
                daemon_status=daemon_status,
                system_status=system_status,
            )
            if item["separator_after"]:
                y = _draw_ready_separator(draw, item["id"], y, W)


_OLED_CUSTOMIZATION_ERROR = ""


def _ready_layout_items() -> list[dict]:
    global _OLED_CUSTOMIZATION_ERROR
    document, _source, errors = load_effective_document(default_icon_payload())
    error = "; ".join(errors)
    if error and error != _OLED_CUSTOMIZATION_ERROR:
        log.warning("invalid OLED customization; using packaged layout: %s", error)
    _OLED_CUSTOMIZATION_ERROR = error
    return document["ready"]["items"]


def _draw_ready_item(
    draw,
    font,
    item_id: str,
    *,
    x: int,
    y: int,
    max_width: int,
    layer: int,
    active: list[int],
    current_mode: str,
    fps_label: str,
    wifi: dict | None,
    daemon_status: dict[str, bool],
    system_status: dict,
) -> int:
    if item_id == "node_name":
        return y + _draw_node_name(draw, font, x, y, max_width) + 2
    if item_id == "daemon_status":
        return y + _draw_daemon_status_row(draw, x, y, daemon_status, max_width=max_width)
    if item_id == "output_mode":
        _draw_output_mode(draw, font, x, y, current_mode, wifi, daemon_status)
        return y + 10
    if item_id == "layer":
        draw.text((x, y), f"Layer: {layer}", font=font, fill="white")
        return y + 12
    if item_id == "active_layers":
        if len(active) > 1:
            draw.text((x, y), f"[{','.join(str(value) for value in active)}]", font=font, fill="white")
            return y + 12
        return y
    if item_id == "cpu":
        draw.text((x, y), f"CPU:{int(system_status.get('cpu_percent', 0))} %", font=font, fill="white")
        return y + 12
    if item_id == "temperature":
        draw.text((x, y), f"T:{float(system_status.get('cpu_temp', 0.0)):.0f} C", font=font, fill="white")
        return y + 12
    if item_id == "fps":
        if fps_label:
            draw.text((x, y), fps_label, font=font, fill="white")
            return y + 12
        return y
    if item_id == "clock":
        draw.text((x, y), time.strftime("  %H:%M"), font=font, fill="white")
        return y + 12
    return y


def _draw_ready_separator(draw, item_id: str, y: int, width: int) -> int:
    if item_id == "daemon_status":
        draw.line([(1, y), (width - 2, y)], fill="black")
        y += 1
        draw.line([(1, y), (width - 2, y)], fill="white")
        return y + 3
    draw.line([(1, y), (width - 2, y)], fill="white")
    return y + (4 if item_id == "node_name" else 3)


def _output_mode_icon_row(
    current_mode: str,
    wifi: dict | None = None,
    daemon_status: dict[str, bool] | None = None,
) -> list[tuple[str, bool]]:
    return output_mode_icon_row(current_mode, wifi, daemon_status)


def _icon_vertical_bounds(icon) -> tuple[int, int]:
    lit_rows = [dy for _dx, dy in icon.pixels()]
    if not lit_rows:
        return 0, icon.height
    return min(lit_rows), max(lit_rows) + 1


def _draw_icon_pixels_cropped(draw, icon, x: int, y: int, *, top: int, bottom: int, fill: str) -> None:
    for dx, dy in icon.pixels():
        if top <= dy < bottom:
            draw.point((x + dx, y + dy - top), fill=fill)


def _draw_icon_badge(draw, icon_name: str, x: int, y: int, *, active: bool = False,
                     trim_vertical: bool = False) -> int:
    icon = icon_bitmap(icon_name)
    top, bottom = _icon_vertical_bounds(icon) if trim_vertical else (0, icon.height)
    height = bottom - top
    if active:
        draw.rectangle([(x, y - 1), (x + icon.width + 1, y + height)], fill="white")
        _draw_icon_pixels_cropped(draw, icon, x + 1, y, top=top, bottom=bottom, fill="black")
        return icon.width + 3
    if trim_vertical:
        _draw_icon_pixels_cropped(draw, icon, x + 1, y, top=top, bottom=bottom, fill="white")
    else:
        draw_icon_pixels(draw, icon, x + 1, y, fill="white")
    return icon.width + 3


def _draw_output_mode(
    draw,
    font,
    x: int,
    y: int,
    current_mode: str,
    wifi: dict | None = None,
    daemon_status: dict[str, bool] | None = None,
) -> None:
    row = _output_mode_icon_row(current_mode, wifi, daemon_status)
    if not row:
        mode = str(current_mode or "").strip()
        draw.text((x, y), _output_mode_display_label(mode), font=font, fill="white")
        return
    cursor = x
    for icon_name, active in row:
        cursor += _draw_icon_badge(draw, icon_name, cursor, y, active=active)


def _daemon_status_icon_row(statuses: dict[str, bool]) -> list[tuple[str, bool]]:
    return daemon_status_icon_row(statuses)


def _daemon_status_active(statuses: dict[str, bool], service: str) -> bool:
    return daemon_status_active(statuses, service) or _pid_file_active(service)


def _merge_busybox_daemon_status(statuses: dict[str, bool]) -> dict[str, bool]:
    merged = dict(statuses)
    for service in _BUSYBOX_SERVICE_PID_FILES:
        if _pid_file_active(service):
            merged[service] = True
    return merged


def _icon_row_width(row: list[tuple[str, bool]]) -> int:
    if not row:
        return 0
    return sum(icon_bitmap(icon_name).width + 3 for icon_name, _ok in row) - 1


def _daemon_status_icon_rows(
    statuses: dict[str, bool],
    *,
    max_width: int = 58,
) -> list[list[tuple[str, bool]]]:
    row = _daemon_status_icon_row(statuses)
    if _icon_row_width(row) <= max_width:
        return [row]
    split_at = (len(row) + 1) // 2
    rows = [row[:split_at], row[split_at:]]
    if any(_icon_row_width(part) > max_width for part in rows):
        raise ValueError("daemon status icons do not fit OLED width")
    return rows


def _draw_daemon_status_row(draw, x: int, y: int, statuses: dict[str, bool], *, max_width: int = 58) -> int:
    row_y = y
    drawn_rows = _daemon_status_icon_rows(statuses, max_width=max_width)
    for row in drawn_rows:
        cursor = x
        row_height = max(
            _icon_vertical_bounds(icon_bitmap(icon_name))[1] - _icon_vertical_bounds(icon_bitmap(icon_name))[0]
            for icon_name, _ok in row
        )
        for icon_name, ok in row:
            cursor += _draw_icon_badge(draw, icon_name, cursor, row_y, active=ok, trim_vertical=True)
        row_y += row_height + 1
    return row_y - y


def _output_mode_display_label(mode: str) -> str:
    if mode == "gadget":
        return "USB"
    if mode == "bt":
        return "BT"
    if mode == "uinput":
        return "Pi"
    return mode


def _draw_shutdown(device, font) -> None:
    """シャットダウンメッセージ表示（warning と同じ反転表示）"""
    W, H = device.width, device.height
    with canvas(device) as draw:
        draw.rectangle([(0, 0), (W-1, H-1)], fill="white")
        draw.text((3, H//2 - 6), "shutdown", font=font, fill="black")

# ---------------------------------------------------------------------------
# アラート表示用ユーティリティ
# ---------------------------------------------------------------------------

def _text_width(font, text: str) -> int:
    """テキストのピクセル幅を返す（フォント種別に対応）"""
    try:
        return int(font.getlength(text))
    except AttributeError:
        pass
    try:
        bbox = font.getbbox(text)
        return bbox[2] - bbox[0]
    except AttributeError:
        return len(text) * 7


def _wrap_text(text: str, font, max_width: int) -> list[str]:
    """テキストを max_width ピクセル内に収まるように折り返す。"""
    lines: list[str] = []

    for paragraph in text.splitlines() or [""]:
        words = paragraph.split(" ")
        current = ""

        for word in words:
            candidate = (current + " " + word).strip() if current else word
            if _text_width(font, candidate) <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                if _text_width(font, word) > max_width:
                    buf = ""
                    for ch in word:
                        if _text_width(font, buf + ch) <= max_width:
                            buf += ch
                        else:
                            if buf:
                                lines.append(buf)
                            buf = ch
                    current = buf
                else:
                    current = word

        if current:
            lines.append(current)
        elif not words:
            lines.append("")

    return lines if lines else [""]


def _draw_alert(device, font, message: str, *, inverted: bool = False) -> None:
    """アラートメッセージを全画面中央揃えで表示。"""
    W, H = device.width, device.height
    margin = 4
    max_w = W - margin * 2
    bg = "white" if inverted else "black"
    fg = "black" if inverted else "white"

    lines = _wrap_text(message, font, max_w)

    try:
        ascent, descent = font.getmetrics()
        line_h = ascent + descent + 1
    except AttributeError:
        line_h = 13

    total_h = line_h * len(lines)
    start_y = max(margin, (H - total_h) // 2)

    with canvas(device) as draw:
        draw.rectangle([(0, 0), (W-1, H-1)], fill=bg)
        for i, line in enumerate(lines):
            y = start_y + i * line_h
            if y + line_h > H - margin:
                break
            lw = _text_width(font, line)
            x = max(margin, (W - lw) // 2)
            draw.text((x, y), line, font=font, fill=fg)


def _alert_is_immediate(msg: dict) -> bool:
    """Return true when an alert/warning should replace the current display."""
    return bool(msg.get("immediate", False))

# ---------------------------------------------------------------------------
# i2c_events.sock サーバー（logicd が接続してくる）
# ---------------------------------------------------------------------------
_msg_queue: asyncio.Queue = asyncio.Queue()
_i2c_client_count: int = 0
_i2c_client_writers: set[asyncio.StreamWriter] = set()


async def _handle_logicd_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """i2c_events.sock への接続を処理するハンドラ。"""
    global _i2c_client_count
    _i2c_client_count += 1
    _i2c_client_writers.add(writer)
    log.info("i2c client 接続 (count=%d)", _i2c_client_count)
    try:
        while True:
            data = await reader.readline()
            if not data:
                break
            await _msg_queue.put(data)
    except Exception as e:
        log.warning("i2c client 接続エラー: %s", e)
    finally:
        _i2c_client_count = max(0, _i2c_client_count - 1)
        _i2c_client_writers.discard(writer)
        log.info("i2c client 切断 (count=%d)", _i2c_client_count)
        try:
            writer.close()
            await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
        except (OSError, asyncio.TimeoutError):
            pass


async def _analog_stick_loop(cfg: dict, shutdown: asyncio.Event) -> None:
    """Poll ADS1115 and forward normalized stick events to logicd ctrl socket."""
    try:
        stick_cfg = parse_analog_stick_config(cfg)
    except (KeyError, TypeError, ValueError) as exc:
        log.warning("analog stick 設定が不正です: %s", exc)
        return
    if stick_cfg is None:
        return

    try:
        reader = ADS1115Reader(bus=stick_cfg.bus, address=stick_cfg.address)
    except Exception as exc:
        log.warning(
            "ADS1115 を初期化できません: bus=%s address=0x%02X (%s)",
            stick_cfg.bus,
            stick_cfg.address,
            exc,
        )
        return

    if stick_cfg.auto_center_on_start and stick_cfg.auto_center_duration > 0:
        try:
            samples: list[tuple[float, float]] = []
            end_at = time.monotonic() + stick_cfg.auto_center_duration
            while not shutdown.is_set() and time.monotonic() < end_at:
                samples.append(await asyncio.to_thread(read_stick_volts, reader, stick_cfg))
                await asyncio.sleep(stick_cfg.poll_interval)
            if samples:
                x_center = statistics.median(sample[0] for sample in samples)
                y_center = statistics.median(sample[1] for sample in samples)
                stick_cfg = stick_cfg.with_centers(x_center, y_center)
                log.info(
                    "ADS1115 analog stick runtime center calibrated: x=%.4f y=%.4f samples=%d duration=%.2fs",
                    x_center,
                    y_center,
                    len(samples),
                    stick_cfg.auto_center_duration,
                )
        except Exception as exc:
            log.warning("analog stick runtime center calibration failed: %s", exc)
        if shutdown.is_set():
            return

    log.info(
        "ADS1115 analog stick polling: bus=%s address=0x%02X x=AIN%d y=AIN%d interval=%.3fs idle=%.3fs after=%.3fs ctrl=%s",
        stick_cfg.bus,
        stick_cfg.address,
        stick_cfg.x_axis.channel,
        stick_cfg.y_axis.channel,
        stick_cfg.poll_interval,
        stick_cfg.idle_poll_interval,
        stick_cfg.idle_after_sec,
        stick_cfg.ctrl_socket,
    )
    last_sent: tuple[int, int] | None = None
    last_active_at = time.monotonic()
    writer: asyncio.StreamWriter | None = None

    async def _connect() -> asyncio.StreamWriter | None:
        try:
            _reader, new_writer = await asyncio.open_unix_connection(stick_cfg.ctrl_socket)
            log.info("analog stick connected to logicd ctrl socket: %s", stick_cfg.ctrl_socket)
            return new_writer
        except (FileNotFoundError, ConnectionRefusedError, PermissionError, OSError) as exc:
            log.debug("analog stick ctrl socket unavailable: %s", exc)
            return None

    try:
        while not shutdown.is_set():
            try:
                x_volts, y_volts = await asyncio.to_thread(read_stick_volts, reader, stick_cfg)
                x, y = normalize_stick(x_volts, y_volts, stick_cfg)
                current = (x, y)
                if current != (0, 0):
                    last_active_at = time.monotonic()
                should_send = current != last_sent or current != (0, 0)
                if should_send:
                    if writer is None or writer.is_closing():
                        writer = await _connect()
                    if writer is not None:
                        writer.write(build_ctrl_event(stick_cfg.stick_index, x, y))
                        await writer.drain()
                        last_sent = current
            except (BrokenPipeError, ConnectionResetError, OSError) as exc:
                log.debug("analog stick ctrl write failed: %s", exc)
                if writer is not None:
                    writer.close()
                    writer = None
            except Exception as exc:
                log.warning("analog stick polling failed: %s", exc)
                await asyncio.sleep(1.0)
            interval = (
                stick_cfg.poll_interval
                if time.monotonic() - last_active_at < stick_cfg.idle_after_sec
                else stick_cfg.idle_poll_interval
            )
            await asyncio.sleep(interval)
    finally:
        if writer is not None:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
            except (OSError, asyncio.TimeoutError):
                pass
        reader.close()


async def _wifi_status_loop(
    snapshot_ref: dict[str, dict],
    shutdown: asyncio.Event,
    *,
    interval_sec: float = 1.0,
    connected_interval_sec: float = 5.0,
) -> None:
    """Refresh Wi-Fi status out of the OLED drawing path."""
    interval_sec = max(0.2, float(interval_sec))
    connected_interval_sec = max(interval_sec, float(connected_interval_sec))
    while not shutdown.is_set():
        next_interval = interval_sec
        try:
            snapshot = await wifi_status(max_age_sec=0.0)
            snapshot_ref["wifi"] = snapshot
            if snapshot.get("connected") is True:
                next_interval = connected_interval_sec
        except Exception as exc:
            log.debug("Wi-Fi status unavailable for OLED row: %s", exc)
            snapshot_ref["wifi"] = {}
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=next_interval)
        except asyncio.TimeoutError:
            pass


async def _system_status_loop(
    snapshot_ref: dict[str, dict],
    shutdown: asyncio.Event,
    *,
    interval_sec: float = 1.0,
) -> None:
    """Refresh cheap /proc and /sys status outside the OLED drawing path."""
    interval_sec = max(0.2, min(10.0, float(interval_sec)))
    while not shutdown.is_set():
        try:
            snapshot_ref["system"] = {
                "cpu_percent": _cpu_percent(),
                "cpu_temp": _cpu_temp(),
                "sampled_at": time.monotonic(),
            }
        except Exception as exc:
            log.debug("system status unavailable for OLED row: %s", exc)
            snapshot_ref["system"] = {}
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=interval_sec)
        except asyncio.TimeoutError:
            pass


async def _outputd_status_loop(
    snapshot_ref: dict[str, dict],
    shutdown: asyncio.Event,
    *,
    status_path: str,
    interval_sec: float = 0.5,
) -> None:
    """Refresh the canonical output router state outside the drawing path."""
    interval_sec = max(0.1, min(10.0, float(interval_sec)))
    max_age_sec = max(2.0, interval_sec * 4.0)
    while not shutdown.is_set():
        snapshot_ref["outputd"] = load_outputd_status(status_path, max_age_sec=max_age_sec)
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=interval_sec)
        except asyncio.TimeoutError:
            pass

# ---------------------------------------------------------------------------
# メインループ
# ---------------------------------------------------------------------------
async def _main() -> None:
    global _SVC_TTL
    cfg = _load_conf()
    device = _init_device(cfg)
    font = _load_font(cfg)

    _shutdown = asyncio.Event()

    def _on_shutdown() -> None:
        if not _shutdown.is_set():
            log.info("シャットダウンシグナルを受信")
            _shutdown.set()
            for writer in list(_i2c_client_writers):
                writer.close()

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, _on_shutdown)
    loop.add_signal_handler(signal.SIGINT, _on_shutdown)
    analog_task = asyncio.create_task(_analog_stick_loop(cfg, _shutdown))

    ledd_sock = (cfg.get("ipc") or {}).get("i2c_socket", "/tmp/i2c_events.sock")
    direct_frame_status_path = (cfg.get("ipc") or {}).get("direct_frame_status", _DEFAULT_DIRECT_FRAME_STATUS)
    outputd_status_path = (cfg.get("ipc") or {}).get("outputd_status", "/run/hidloom/outputd-status.json")
    fps_monitor = _DirectFrameFpsMonitor(direct_frame_status_path)
    poll_sec = 2.0
    display_cfg = cfg.get("display") or {}
    try:
        refresh_sec = float(display_cfg.get("refresh_interval_sec", 5.0))
    except (TypeError, ValueError):
        refresh_sec = 5.0
    refresh_sec = max(1.0, min(60.0, refresh_sec))
    try:
        display_fps = float(display_cfg.get("fps", 10.0))
    except (TypeError, ValueError):
        display_fps = 10.0
    display_fps = max(0.2, min(10.0, display_fps))
    event_refresh_sec = 1.0 / display_fps
    try:
        wifi_poll_interval_sec = float(display_cfg.get("wifi_poll_interval_sec", 1.0))
    except (TypeError, ValueError):
        wifi_poll_interval_sec = 1.0
    wifi_poll_interval_sec = max(0.2, min(60.0, wifi_poll_interval_sec))
    try:
        wifi_connected_poll_interval_sec = float(display_cfg.get("wifi_connected_poll_interval_sec", 5.0))
    except (TypeError, ValueError):
        wifi_connected_poll_interval_sec = 5.0
    wifi_connected_poll_interval_sec = max(wifi_poll_interval_sec, min(300.0, wifi_connected_poll_interval_sec))
    try:
        service_status_poll_interval_sec = float(display_cfg.get("service_status_poll_interval_sec", _SVC_TTL))
    except (TypeError, ValueError):
        service_status_poll_interval_sec = _SVC_TTL
    _SVC_TTL = max(1.0, min(300.0, service_status_poll_interval_sec))
    try:
        system_poll_interval_sec = float(display_cfg.get("system_poll_interval_sec", 1.0))
    except (TypeError, ValueError):
        system_poll_interval_sec = 1.0
    system_poll_interval_sec = max(0.2, min(10.0, system_poll_interval_sec))
    try:
        output_status_poll_interval_sec = float(display_cfg.get("output_status_poll_interval_sec", 0.5))
    except (TypeError, ValueError):
        output_status_poll_interval_sec = 0.5
    output_status_poll_interval_sec = max(0.1, min(10.0, output_status_poll_interval_sec))

    layer = 0
    active: list[int] = [0]
    current_mode: str = ""
    display_mode: str = ""
    daemon_status: dict[str, bool] = {}
    status_snapshots: dict[str, dict] = {"wifi": {}, "system": {}, "outputd": {}}
    last_refresh = 0.0
    display_dirty = True
    alert_msg: str = ""
    alert_until: float = 0.0
    alert_was_active: bool = False
    alert_queue: list[tuple[str, float, bool]] = []

    def _start_alert(message: str, duration: float, inverted: bool = False) -> None:
        nonlocal alert_msg, alert_until, alert_was_active
        alert_msg = message
        alert_until = time.monotonic() + max(0.1, duration)
        alert_was_active = True
        _draw_alert(device, font, alert_msg, inverted=inverted)

    if os.path.exists(ledd_sock):
        os.unlink(ledd_sock)
    server = await asyncio.start_unix_server(_handle_logicd_client, path=ledd_sock)
    os.chmod(ledd_sock, 0o666)
    log.info(
        "i2cd 起動（表示: %dx%d, sock: %s, refresh: %.1fs, event_fps: %.1f）",
        device.width,
        device.height,
        ledd_sock,
        refresh_sec,
        display_fps,
    )
    wifi_task = asyncio.create_task(
        _wifi_status_loop(
            status_snapshots,
            _shutdown,
            interval_sec=wifi_poll_interval_sec,
            connected_interval_sec=wifi_connected_poll_interval_sec,
        )
    )
    system_task = asyncio.create_task(
        _system_status_loop(
            status_snapshots,
            _shutdown,
            interval_sec=system_poll_interval_sec,
        )
    )
    outputd_task = asyncio.create_task(
        _outputd_status_loop(
            status_snapshots,
            _shutdown,
            status_path=outputd_status_path,
            interval_sec=output_status_poll_interval_sec,
        )
    )

    async with server:
        while not _shutdown.is_set():
            matrixd_ok = await _service_active("matrixd")
            logicd_ok = _i2c_client_count > 0
            daemon_status = _merge_busybox_daemon_status(daemon_status)
            next_display_mode = effective_output_display_mode(
                current_mode,
                status_snapshots.get("outputd", {}),
            )
            if next_display_mode != display_mode:
                display_mode = next_display_mode
                source = "outputd" if outputd_display_mode(status_snapshots.get("outputd", {})) else "logicd"
                log.info("OLED出力モード同期: %s (source=%s)", display_mode, source)
                display_dirty = True

            try:
                data = await asyncio.wait_for(_msg_queue.get(), timeout=0.05)
                msg = json.loads(data.decode())
                if msg.get("t") == "layer":
                    layer = msg.get("layer", 0)
                    active = msg.get("active", [layer])
                    display_dirty = True
                elif msg.get("t") == "mode":
                    current_mode = msg.get("mode", current_mode)
                    log.info("HIDモード変更: %s", current_mode)
                    display_dirty = True
                elif msg.get("t") == "daemon_status":
                    services = msg.get("services", {})
                    if isinstance(services, dict):
                        daemon_status = _merge_busybox_daemon_status(
                            {str(k): bool(v) for k, v in services.items()}
                        )
                        daemon_status["logicd"] = logicd_ok
                        display_dirty = True
                elif msg.get("t") == "oled_config_reload":
                    invalidate_oled_customization_cache()
                    display_dirty = True
                    log.info("OLED customization reloaded")
                elif msg.get("t") == "bt_pairing":
                    phase = str(msg.get("phase", "off")).lower()
                    digits = str(msg.get("digits", ""))
                    if phase in {"pairing", "passkey", "passkey_wait", "digits"}:
                        title = "BT PAIRING" if phase == "pairing" else "ENTER CODE"
                        shown_digits = "*" * min(len(digits), 6)
                        alert_queue.append((f"{title}\n{shown_digits}", 2.0, False))
                    elif phase in {"success", "paired", "connected"}:
                        alert_queue.append(("BT CONNECTED", 2.0, False))
                    elif phase in {"failed", "error"}:
                        alert_queue.append(("PAIR FAILED", 3.0, True))
                elif msg.get("t") == "script_exit":
                    name = msg.get("name", "")
                    exit_code = msg.get("code", -1)
                    log.info("スクリプト終了受信: %s (exit_code=%d)", name, exit_code)
                    alert_queue.append((f"{name}\nexit: {exit_code}", 3.0, False))
                elif msg.get("t") in ("alert", "warning"):
                    raw_alert = str(msg.get("msg", ""))
                    incoming_alert = ascii_oled_text(raw_alert)
                    if incoming_alert != raw_alert:
                        log.warning("OLED alert contained unsupported non-ASCII text; replaced before rendering")
                    duration = float(msg.get("sec", 5.0))
                    inverted = msg.get("t") == "warning" or str(msg.get("level", "")).lower() == "warning"
                    if _alert_is_immediate(msg):
                        _start_alert(incoming_alert, duration, inverted)
                    else:
                        alert_queue.append((incoming_alert, duration, inverted))
                    kind = "警告" if inverted else "アラート"
                    log.info("%s受信: %s (%.1f秒)", kind, incoming_alert, duration)
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                log.warning("メッセージ読み取りエラー: %s", e)

            now = time.monotonic()
            if alert_until > now:
                await asyncio.sleep(0.1)
            elif alert_queue:
                pending_msg, pending_duration, pending_inverted = alert_queue.pop(0)
                _start_alert(pending_msg, pending_duration, pending_inverted)
                await asyncio.sleep(0.1)
            elif not (matrixd_ok and logicd_ok):
                if alert_was_active:
                    last_refresh = 0.0
                    display_dirty = True
                    alert_was_active = False
                _draw_boot(device, font, matrixd_ok, logicd_ok)
                await asyncio.sleep(poll_sec)
            else:
                if alert_was_active:
                    last_refresh = 0.0
                    display_dirty = True
                    alert_was_active = False
                periodic_due = now - last_refresh >= refresh_sec or last_refresh == 0.0
                event_due = display_dirty and now - last_refresh >= event_refresh_sec
                if periodic_due or event_due:
                    _draw_ready(
                        device,
                        font,
                        layer,
                        active,
                        matrixd_ok,
                        logicd_ok,
                        display_mode,
                        fps_monitor.label(),
                        status_snapshots.get("wifi", {}),
                        daemon_status,
                        status_snapshots.get("system", {}),
                    )
                    last_refresh = now
                    display_dirty = False
                await asyncio.sleep(0.1)

    analog_task.cancel()
    try:
        await analog_task
    except asyncio.CancelledError:
        pass
    wifi_task.cancel()
    try:
        await wifi_task
    except asyncio.CancelledError:
        pass
    system_task.cancel()
    try:
        await system_task
    except asyncio.CancelledError:
        pass
    outputd_task.cancel()
    try:
        await outputd_task
    except asyncio.CancelledError:
        pass

    log.info("シャットダウンメッセージを OLED に表示")
    _draw_shutdown(device, font)
    await asyncio.sleep(2.0)
    device.cleanup = lambda: None


def main() -> None:
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        print(_HELP.rstrip())
        return

    asyncio.run(_main())


if __name__ == "__main__":
    main()
