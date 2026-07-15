"""Auto output switching helpers for logicd."""
from __future__ import annotations

import glob
import logging
import os
import time
from collections.abc import Callable
from typing import Optional

from .hid_report import HidState
from .uinput import create_uinput_write_fn

log = logging.getLogger(__name__)


def _hid_report_logging_enabled() -> bool:
    raw = os.environ.get("LOGICD_HID_REPORT_LOG", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _log_hid_report_write(label: str, hidg_path: str, data: bytes) -> None:
    if not _hid_report_logging_enabled():
        return
    log.info(
        "HID gadget write label=%s path=%s len=%d hex=%s",
        label,
        hidg_path,
        len(data),
        data.hex(),
    )


def new_hid_write_fn(hidg_path: str, initial_fd: Optional[int], nonblocking: bool = False):
    """Return a HID writer that reopens the gadget after disconnects."""
    open_flags = os.O_WRONLY | (os.O_NONBLOCK if nonblocking else 0)
    fd_box: list[Optional[int]] = [initial_fd]
    last_reopen: list[float] = [0.0]
    reopen_interval = 1.0

    def write(data: bytes) -> None:
        if fd_box[0] is None:
            now = time.monotonic()
            if now - last_reopen[0] < reopen_interval:
                return
            last_reopen[0] = now
            try:
                fd_box[0] = os.open(hidg_path, open_flags)
                log.info("HID device reopened: %s", hidg_path)
            except OSError:
                return
        try:
            _log_hid_report_write("direct", hidg_path, data)
            os.write(fd_box[0], data)
        except OSError as exc:
            errno_code = exc.errno
            if errno_code == 11:
                return
            if errno_code in (108, 32, 5):
                log.debug("HID disconnected (errno %d), will reopen on next write", errno_code)
                try:
                    os.close(fd_box[0])
                except OSError:
                    pass
                fd_box[0] = None
                last_reopen[0] = 0.0
            else:
                log.warning("HID write error: %s", exc)

    return write


def with_hid_report_id(write_fn: Callable[[bytes], None], report_id: int) -> Callable[[bytes], None]:
    """Return a writer that prefixes payloads with a HID Report ID."""
    from .hid_report import add_hid_report_id

    def write(data: bytes) -> None:
        write_fn(add_hid_report_id(report_id, data))

    return write


def create_dynamic_write_fn(
    hidg_path: str,
    cfg: dict,
    *,
    get_state: Callable[[], bytes] | None = None,
    release_all: Callable[[], None] | None = None,
    uinput_factory: Callable[[dict], Callable[[bytes], None]] | None = None,
    bt_writer: Callable[[bytes], None] | None = None,
    bt_available: Callable[[], bool] | None = None,
    allow_bt_fallback: bool = False,
    on_bt_disabled: Callable[[], None] | None = None,
    push_ledd_mode: Callable[[str], None] | None = None,
    push_i2cd_mode: Callable[[str], None] | None = None,
    gadget_transform: Callable[[bytes], bytes] | None = None,
    gadget_write_fn: Callable[[bytes], None] | None = None,
) -> Callable[[bytes], None]:
    """Return an auto writer that picks one output.

    The default order is gadget, then uinput. Bluetooth fallback is opt-in so a
    paired phone does not lose its software keyboard merely because btd is
    running.
    """
    check_interval = 2.0
    last_check: list[float] = [-check_interval]
    mode: list[str] = ["unknown"]
    hid_fd_box: list = [None]
    uinput_fn_box: list = [None]
    eagain_count: list[int] = [0]
    eagain_disconnect_threshold = 5
    confirmed_disconnect: list[bool] = [False]
    manual_lock: list[bool] = [False]
    released_for_switch: list[bool] = [False]
    disconnect_errnos = frozenset({5, 6, 19, 32, 108})
    last_usb_check_log: list[tuple[Optional[bool], str, bool] | None] = [None]

    if uinput_factory is None:
        uinput_factory = create_uinput_write_fn
    if gadget_transform is None:
        gadget_transform = lambda data: data

    def _gadget_report(data: bytes) -> bytes:
        return gadget_transform(data)

    def _write_gadget_report(label: str, data: bytes, fd: int | None = None) -> None:
        report = _gadget_report(data)
        _log_hid_report_write(label, hidg_path, report)
        if gadget_write_fn is not None:
            gadget_write_fn(report)
            return
        if fd is None:
            raise OSError("HID gadget fd is not open")
        os.write(fd, report)

    def _push_ledd(value: str) -> None:
        if push_ledd_mode is not None:
            push_ledd_mode(value)

    def _push_i2cd(value: str) -> None:
        if push_i2cd_mode is not None:
            push_i2cd_mode(f"auto:{value}")

    def _check_usb_connected() -> bool:
        for state_path in glob.glob("/sys/class/udc/*/state"):
            try:
                with open(state_path) as fh:
                    if fh.read().strip() == "configured":
                        return True
            except OSError:
                pass
        return False

    def _current_report() -> bytes:
        return get_state() if get_state is not None else HidState.null_report()

    def _release_before_switch(prev: str) -> None:
        if prev not in {"gadget", "bt", "uinput"}:
            return
        null_report = HidState.null_report()
        if prev == "gadget" and (hid_fd_box[0] is not None or gadget_write_fn is not None):
            try:
                _write_gadget_report("switch-release", null_report, hid_fd_box[0])
            except OSError as exc:
                log.debug("切り替え前 release report の送信失敗 (%s): %s", hidg_path, exc)
        elif prev == "bt" and bt_writer is not None:
            try:
                bt_writer(null_report)
            except Exception as exc:
                log.debug("切り替え前 bt release の送信失敗: %s", exc)
            if on_bt_disabled is not None:
                try:
                    on_bt_disabled()
                except Exception as exc:
                    log.warning("BT output disabled hook failed: %s", exc)
        elif prev == "uinput" and uinput_fn_box[0] is not None:
            try:
                uinput_fn_box[0](null_report)
            except Exception as exc:
                log.debug("切り替え前 uinput release の送信失敗: %s", exc)

        if release_all is not None:
            release_all()
        released_for_switch[0] = True
        log.info("出力先切り替え前に未リリースキーを解放しました (%s)", prev)

    def _consume_switch_release_if_needed(data: bytes) -> bytes:
        if not released_for_switch[0]:
            return data
        released_for_switch[0] = False
        return _current_report()

    def _switch_to_gadget() -> bool:
        if hid_fd_box[0] is None and gadget_write_fn is None:
            try:
                hid_fd_box[0] = os.open(hidg_path, os.O_WRONLY | os.O_NONBLOCK)
            except OSError as exc:
                log.warning("gadgetデバイスを開けません %s: %s", hidg_path, exc)
                return False
        prev = mode[0]
        if prev != "gadget":
            _release_before_switch(prev)
        mode[0] = "gadget"
        _write.current_mode = "gadget"
        eagain_count[0] = 0
        if prev != "gadget":
            log.info("動作モード切り替え: uinput -> gadget (%s)", hidg_path)
            try:
                _write_gadget_report("switch-current", _current_report(), hid_fd_box[0])
            except OSError:
                pass
            _push_ledd("gadget")
            _push_i2cd("gadget")
        return True

    def _switch_to_uinput() -> None:
        prev = mode[0]
        if prev != "uinput":
            _release_before_switch(prev)
        mode[0] = "uinput"
        _write.current_mode = "uinput"
        if prev != "uinput":
            log.info("動作モード切り替え: gadget -> uinput")
            _push_ledd("uinput")
            _push_i2cd("uinput")
        if uinput_fn_box[0] is None:
            uinput_fn_box[0] = uinput_factory(cfg)
        if hid_fd_box[0] is not None:
            fd = hid_fd_box[0]
            hid_fd_box[0] = None
            try:
                os.close(fd)
            except OSError:
                pass

    def _bt_is_available() -> bool:
        if not allow_bt_fallback:
            return False
        if bt_writer is None:
            return False
        if bt_available is None:
            return True
        try:
            return bool(bt_available())
        except Exception as exc:
            log.debug("BT output availability check failed: %s", exc)
            return False

    def _log_usb_check(connected: Optional[bool]) -> None:
        state = (connected, mode[0], manual_lock[0])
        if state == last_usb_check_log[0]:
            return
        last_usb_check_log[0] = state
        if manual_lock[0]:
            log.debug("USB接続チェック: 手動ロック中のためスキップ (現在モード: %s)", mode[0])
            return
        log.debug("USB接続チェック: %s (現在モード: %s)", "接続" if connected else "切断", mode[0])

    def _switch_to_bt() -> bool:
        if not _bt_is_available():
            return False
        prev = mode[0]
        if prev != "bt":
            _release_before_switch(prev)
        mode[0] = "bt"
        _write.current_mode = "bt"
        if hid_fd_box[0] is not None:
            fd = hid_fd_box[0]
            hid_fd_box[0] = None
            try:
                os.close(fd)
            except OSError:
                pass
        if prev != "bt":
            log.info("動作モード切り替え: %s -> bt", prev)
            _push_ledd("bt")
            _push_i2cd("bt")
        return True

    def _switch_to_fallback() -> None:
        if _switch_to_bt():
            return
        _switch_to_uinput()

    def check_and_switch() -> None:
        last_check[0] = time.monotonic()
        if manual_lock[0]:
            _log_usb_check(None)
            return
        connected = _check_usb_connected()
        _log_usb_check(connected)

        if not connected:
            if mode[0] not in {"bt", "uinput"}:
                _switch_to_fallback()
            elif mode[0] == "bt" and not _bt_is_available():
                _switch_to_uinput()
            elif mode[0] == "uinput" and _bt_is_available():
                _switch_to_bt()
            return

        if mode[0] != "gadget":
            if confirmed_disconnect[0]:
                if gadget_write_fn is not None:
                    try:
                        _write_gadget_report("probe-null", HidState.null_report(), None)
                        confirmed_disconnect[0] = False
                        eagain_count[0] = 0
                        log.info("動作モード切り替え: uinput -> gadget (%s) [broker確認済み]", hidg_path)
                        _switch_to_gadget()
                    except OSError as exc:
                        log.debug("切断確定済み: broker probe 失敗、fallback outputを維持: %s", exc)
                        _switch_to_fallback()
                    return
                try:
                    test_fd = os.open(hidg_path, os.O_WRONLY | os.O_NONBLOCK)
                    try:
                        _write_gadget_report("probe-null", HidState.null_report(), test_fd)
                        confirmed_disconnect[0] = False
                        eagain_count[0] = 0
                        hid_fd_box[0] = test_fd
                        log.info("動作モード切り替え: uinput -> gadget (%s) [再接続確認済み]", hidg_path)
                        _switch_to_gadget()
                    except OSError as exc:
                        try:
                            os.close(test_fd)
                        except OSError:
                            pass
                        log.debug("切断確定済み: プローブ失敗 (errno %d)、fallback outputを維持", exc.errno)
                        _switch_to_fallback()
                except OSError as exc:
                    log.debug("切断確定済み: gadgetデバイスを開けません: %s", exc)
                    _switch_to_fallback()
                return
            if not _switch_to_gadget():
                _switch_to_fallback()
            return

        if hid_fd_box[0] is not None or gadget_write_fn is not None:
            try:
                _write_gadget_report("probe-current", _current_report(), hid_fd_box[0])
                eagain_count[0] = 0
            except OSError as exc:
                if exc.errno == 11:
                    eagain_count[0] += 1
                    if eagain_count[0] >= eagain_disconnect_threshold:
                        log.info("EAGAIN 連続 %d 回 - USB切断とみなしuinputへフォールバック", eagain_count[0])
                        confirmed_disconnect[0] = True
                        _switch_to_fallback()
                elif exc.errno in disconnect_errnos:
                    log.info("HIDプローブ失敗 (errno %d) - fallback outputへ切り替え", exc.errno)
                    _switch_to_fallback()

    def _write(data: bytes) -> None:
        now = time.monotonic()
        if now - last_check[0] >= check_interval:
            check_and_switch()
            data = _consume_switch_release_if_needed(data)

        if mode[0] == "gadget" and (hid_fd_box[0] is not None or gadget_write_fn is not None):
            try:
                _write_gadget_report("auto", data, hid_fd_box[0])
                eagain_count[0] = 0
            except OSError as exc:
                if exc.errno == 11:
                    eagain_count[0] += 1
                    if eagain_count[0] >= eagain_disconnect_threshold:
                        log.info("EAGAIN 連続 %d 回 - USB切断とみなしuinputへフォールバック", eagain_count[0])
                        confirmed_disconnect[0] = True
                        _switch_to_fallback()
                        if mode[0] == "uinput" and uinput_fn_box[0]:
                            uinput_fn_box[0](_current_report())
                        elif mode[0] == "bt" and bt_writer is not None:
                            bt_writer(_current_report())
                    return
                if exc.errno in disconnect_errnos:
                    log.info("HID書き込みエラー (errno %d) - fallback outputへ切り替え", exc.errno)
                    _switch_to_fallback()
                    if mode[0] == "uinput" and uinput_fn_box[0]:
                        uinput_fn_box[0](_current_report())
                    elif mode[0] == "bt" and bt_writer is not None:
                        bt_writer(_current_report())
                else:
                    log.warning("HID書き込みエラー: %s", exc)
        elif mode[0] == "bt" and bt_writer is not None:
            if _bt_is_available():
                bt_writer(data)
            else:
                _switch_to_uinput()
                if uinput_fn_box[0]:
                    uinput_fn_box[0](_current_report())
        elif mode[0] == "uinput" and uinput_fn_box[0]:
            uinput_fn_box[0](data)

    def force_gadget() -> None:
        manual_lock[0] = False
        confirmed_disconnect[0] = False
        eagain_count[0] = 0
        _switch_to_gadget()

    def force_uinput() -> None:
        manual_lock[0] = True
        confirmed_disconnect[0] = True
        _switch_to_uinput()

    def force_auto() -> None:
        manual_lock[0] = False
        confirmed_disconnect[0] = False
        eagain_count[0] = 0
        log.info("自動切り替えモードへ復帰")
        prev = mode[0]
        check_and_switch()
        if mode[0] == prev:
            _push_ledd(mode[0])
            _push_i2cd(mode[0])

    _write.check_and_switch = check_and_switch
    _write.force_gadget = force_gadget
    _write.force_uinput = force_uinput
    _write.force_auto = force_auto
    _write.current_mode = mode[0]

    if _check_usb_connected():
        _switch_to_gadget()
    else:
        _switch_to_fallback()

    return _write
