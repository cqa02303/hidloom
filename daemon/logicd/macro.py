"""
Macro, Unicode, and IME action executor.

Supported action formats
------------------------
KC_*            : standard or JIS keycode (press / release)
MO(N) / TG(N)  : layer actions (handled by LayerManager, not here)
MACRO:<name>    : execute named macro from config macros dict
IME_ON          : send かな key (0x88) to force IME on
IME_OFF         : send 半角/全角 (KC_GRAVE) to toggle IME off
U+XXXX          : Windows Unicode input (type hex → F5 → Enter)

Macro element syntax (list items):
  plain string       → type each character
  "{KC:KC_NAME}"     → single keycode tap
  "{U+XXXX}"         → Unicode sequence
  "{IME_ON}"         → IME on
  "{IME_OFF}"        → IME off
"""
from __future__ import annotations

import asyncio
import os
import shlex
import logging
from typing import Any, Callable, Dict, Sequence
from pathlib import Path

import subprocess
from .hid_report import (
    KEYCODE,
    CONSUMER_KEYCODE,
    MOUSE_MOVE_STEP,
    MOUSE_WHEEL_STEP,
    HidState,
    MouseState,
    _MOUSE_MIN,
)
from .script_report import parse_script_report_metadata, sanitize_report_text

# KC_SH0 ~ KC_SH10 の HID コード範囲 (keycodes.json: 960-970)
_SH_KEY_MIN = 960
_SH_KEY_MAX = 970
_JIS_ZENKAKU_HANKAKU_KEY = 997
_JIS_ZENKAKU_HANKAKU_INTERNAL_MARKER = 0x5A
_JIS_ZENKAKU_HANKAKU_HID_USAGE = 0x35
_REPO_ROOT = Path(
    os.environ.get("HIDLOOM_REPO_ROOT")
    or Path(__file__).resolve().parents[2]
)

log = logging.getLogger(__name__)

_CONSUMER_ACTION_ALIASES = {
    "KC_KB_MUTE": "KC_AUDIO_MUTE",
    "KC_KB_VOLUME_UP": "KC_AUDIO_VOL_UP",
    "KC_KB_VOLUME_DOWN": "KC_AUDIO_VOL_DOWN",
    "KC_MUTE": "KC_AUDIO_MUTE",
    "KC_VOLU": "KC_AUDIO_VOL_UP",
    "KC_VOLD": "KC_AUDIO_VOL_DOWN",
}

_MOUSE_ACTION_ALIASES = {
    "MS_BTN1": "KC_BTN1",
    "MS_BTN2": "KC_BTN2",
    "MS_BTN3": "KC_BTN3",
    "MS_BTN4": "KC_BTN4",
    "MS_BTN5": "KC_BTN5",
    "MS_UP": "KC_MS_U",
    "MS_DOWN": "KC_MS_D",
    "MS_LEFT": "KC_MS_L",
    "MS_RGHT": "KC_MS_R",
    "MS_RIGHT": "KC_MS_R",
    "MS_WHLU": "KC_WH_U",
    "MS_WHLD": "KC_WH_D",
    "MS_WHLL": "KC_WH_L",
    "MS_WHLR": "KC_WH_R",
}
_MOUSE_ACCELERATION_PROFILES = {
    "MS_ACL0": (2, 1),
    "MS_ACL1": (5, 3),
    "MS_ACL2": (12, 6),
}

# Timing constants (seconds)
_KEY_HOLD  = 0.030   # how long a single tap is held
_KEY_GAP   = 0.020   # gap between keystrokes in a macro

# ---------------------------------------------------------------------------
# ASCII → (modifier_bits, hid_code) for string typing (US/JIS common chars)
# ---------------------------------------------------------------------------
_CHAR_MAP: Dict[str, tuple] = {}


def _build_char_map() -> None:
    kc = KEYCODE
    # Lowercase
    for c in "abcdefghijklmnopqrstuvwxyz":
        _CHAR_MAP[c] = (0, kc[f"KC_{c.upper()}"])
    # Uppercase (need Shift)
    for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        _CHAR_MAP[c] = (0x02, kc[f"KC_{c}"])
    # Digits
    for c in "1234567890":
        _CHAR_MAP[c] = (0, kc[f"KC_{c}"])
    # Plain punctuation
    for char, name in [
        (" ", "KC_SPACE"), ("\t", "KC_TAB"), ("\n", "KC_ENTER"),
        ("-", "KC_MINUS"), ("=", "KC_EQUAL"),
        ("[", "KC_LBRACKET"), ("]", "KC_NUHS"), ("\\", "KC_BSLASH"),
        (";", "KC_SCOLON"), ("'", "KC_QUOTE"), ("`", "KC_GRAVE"),
        (",", "KC_COMMA"), (".", "KC_DOT"), ("/", "KC_SLASH"),
    ]:
        _CHAR_MAP[char] = (0, kc[name])
    # Shifted punctuation (US layout assumptions)
    for char, name in [
        ("!", "KC_1"), ("@", "KC_2"), ("#", "KC_3"), ("$", "KC_4"),
        ("%", "KC_5"), ("^", "KC_6"), ("&", "KC_7"), ("*", "KC_8"),
        ("(", "KC_9"), (")", "KC_0"), ("_", "KC_MINUS"), ("+", "KC_EQUAL"),
        ("{", "KC_LBRACKET"), ("}", "KC_NUHS"), ("|", "KC_BSLASH"),
        (":", "KC_SCOLON"), ('"', "KC_QUOTE"), ("~", "KC_GRAVE"),
        ("<", "KC_COMMA"), (">", "KC_DOT"), ("?", "KC_SLASH"),
    ]:
        _CHAR_MAP[char] = (0x02, kc[name])


_build_char_map()


class MacroExecutor:
    """Executes keycode actions, IME sequences, Unicode input, and macros."""

    def __init__(
        self,
        hid_state: HidState,
        write_fn: Callable[[bytes], None],
        macros: Dict[str, Any],
        mouse_write_fn: Callable[[bytes], None] = lambda b: None,
        consumer_write_fn: Callable[[int, bool], None] = lambda u, p: None,
        key_event_broadcast: Callable[[int, int, bool], None] = lambda k, m, p: None,
        script_dir: str | Sequence[str] = "",
        script_exit_notify: Callable[[str, int], None] = lambda n, c: None,
        script_report_notify: Callable[[str, str, str, int], None] = lambda n, s, t, c: None,
    ) -> None:
        self._state       = hid_state
        self._write       = write_fn
        self._macros      = macros
        self._mouse_state = MouseState()
        self._mouse_write = mouse_write_fn
        self._consumer    = consumer_write_fn
        self._key_event_broadcast = key_event_broadcast
        if isinstance(script_dir, str):
            self._script_dirs = [script_dir] if script_dir else []
        else:
            self._script_dirs = [str(path) for path in script_dir if path]
        self._script_exit_notify = script_exit_notify
        self._script_report_notify = script_report_notify
        self._mouse_move_step = MOUSE_MOVE_STEP
        self._mouse_wheel_step = MOUSE_WHEEL_STEP
        # キーコード → 連続移動タスクのマッピング
        self._move_tasks: Dict[int, asyncio.Task] = {}

    @property
    def mouse_buttons(self) -> int:
        return self._mouse_state.buttons

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def handle(self, action: str, is_press: bool) -> None:
        """Dispatch action on key press or release."""
        if action in ("KC_NONE", "KC_TRNS", ""):
            return

        action = _MOUSE_ACTION_ALIASES.get(action, action)
        consumer_action = _CONSUMER_ACTION_ALIASES.get(action, action)

        if action in _MOUSE_ACCELERATION_PROFILES:
            if is_press:
                self._mouse_move_step, self._mouse_wheel_step = _MOUSE_ACCELERATION_PROFILES[action]
            return

        # Consumer Control キー (Usage Page 0x0C) — HID キーボードレポートではなく
        # Consumer Control report is routed through the configured output writer.
        if consumer_action in CONSUMER_KEYCODE:
            self._consumer(CONSUMER_KEYCODE[consumer_action], is_press)
            return

        if action.startswith("KC_"):
            code = KEYCODE.get(action, 0)
            # 出力先強制切り替えキー (押下時のみ動作)
            if code in (980, 981, 982, 992):  # KC_CONNAUTO / KC_CONSOLE / KC_USB / KC_BT
                if is_press:
                    fn_map = {
                        980: "force_auto",     # KC_CONNAUTO: 自動切り替えモードへ復帰
                        981: "force_uinput",   # KC_CONSOLE: uinput単独出力
                        982: "force_gadget",   # KC_USB:     gadget単独出力
                        992: "force_bt",       # KC_BT:      Bluetooth単独出力
                    }
                    fn_name = fn_map[code]
                    fn = getattr(self._write, fn_name, None)
                    if fn is not None:
                        fn()
                        log.info("出力先切り替え: %s", fn_name)
                    else:
                        log.warning("%s が利用できません (OutputRouter/動的切り替えモード以外)", fn_name)
                return

            if code == _JIS_ZENKAKU_HANKAKU_KEY:
                report = (
                    bytes([
                        self._state.mod,
                        _JIS_ZENKAKU_HANKAKU_INTERNAL_MARKER,
                        _JIS_ZENKAKU_HANKAKU_HID_USAGE,
                        0,
                        0,
                        0,
                        0,
                        0,
                    ])
                    if is_press
                    else bytes([self._state.mod, 0x00, 0, 0, 0, 0, 0, 0])
                )
                self._write(report)
                self._key_event_broadcast(code, self._state.mod, is_press)
                return

            # KC_SH0 ~ KC_SH10: 仮想スクリプトキー (hid 960-970)
            if _SH_KEY_MIN <= code <= _SH_KEY_MAX:
                if is_press:
                    name = f"KC_SH{code - _SH_KEY_MIN}"
                    asyncio.create_task(self._run_shell_script(name))
                return

            if code == 999:  # KC_SHUTDOWN
                if is_press:
                    log.info("シャットダウン要求を受信しました (SW90)")
                    with open("/tmp/shutdown_test.log", "a") as f: f.write("KC_SHUTDOWN triggered at " + str(__import__("datetime").datetime.now()) + "\n")
                    try:
                        # Linuxのシャットダウンコマンドを実行
                        log.info("システムをシャットダウンします")
                        command = os.environ.get(
                            "LOGICD_SHUTDOWN_COMMAND",
                            "sudo shutdown -h now",
                        )
                        argv = shlex.split(command)
                        if not argv:
                            raise RuntimeError("LOGICD_SHUTDOWN_COMMAND is empty")
                        subprocess.Popen(argv)
                        log.info("シャットダウンコマンドを実行しました")
                    except Exception as e:
                        log.error("シャットダウンコマンド実行エラー: %s", e)
                return

            if code >= _MOUSE_MIN:
                # Mouse / wheel reports are routed through the configured output writer.
                loop = asyncio.get_event_loop()
                if is_press:
                    self._mouse_state.press(code)
                    delta = MouseState.move_delta(
                        code,
                        move_step=self._mouse_move_step,
                        wheel_step=self._mouse_wheel_step,
                    )
                    if delta and code not in self._move_tasks:
                        # 移動系: 離すまで繰り返し送信するタスクを開始
                        task = asyncio.create_task(self._mouse_repeat(code, delta))
                        self._move_tasks[code] = task
                    else:
                        # ボタン系またはタスク既存: 現在のボタン状態を即時送信
                        await loop.run_in_executor(
                            None, self._mouse_write, self._mouse_state.null_report())
                else:
                    # キー離し: 連続移動タスクをキャンセルして停止
                    task = self._move_tasks.pop(code, None)
                    if task:
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                    self._mouse_state.release(code)
                    await loop.run_in_executor(
                        None, self._mouse_write, self._mouse_state.null_report())
                return
            # 通常のキーコード処理
            if is_press:
                self._state.press(code)
            else:
                self._state.release(code)
            self._write(self._state.build())

            # key_events.sock へブロードキャスト
            modifier = self._state.mod  # 現在のモディファイアビット
            self._key_event_broadcast(code, modifier, is_press)
            return

        # Press-only actions below
        if not is_press:
            return

        if action == "IME_ON":
            await self._tap(KEYCODE["KC_KANA"])
        elif action == "IME_OFF":
            await self._tap(KEYCODE["KC_GRAVE"])
        elif action.startswith("U+"):
            await self._unicode(action[2:])
        elif action.startswith("MACRO:"):
            await self._run_named(action[6:])
        else:
            log.debug("Unknown action: %s", action)

    # ------------------------------------------------------------------
    # Shell script execution (KC_SH0 ~ KC_SH10)
    # ------------------------------------------------------------------

    async def _run_shell_script(self, name: str) -> None:
        """仮想スクリプトキーに対応するシェルスクリプトを子プロセスとして実行する。

        スクリプトが終了したら exit コードを i2cd へ通知する。
        スクリプトが存在しない場合は exit code 127 を通知する。
        """
        script_path = self._resolve_shell_script(name)
        if not script_path or not os.path.isfile(script_path):
            locations = ", ".join(os.path.join(path, f"{name}.sh") for path in self._script_dirs)
            log.warning("スクリプトが見つかりません: %s", locations or f"(script_dir 未設定) {name}.sh")
            self._script_exit_notify(name, 127)
            return

        report_meta = self._load_script_report_metadata(script_path)
        log.info("スクリプト実行開始: %s", script_path)
        exit_code = -1
        try:
            proc = await asyncio.create_subprocess_exec(
                script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._shell_script_env(),
            )
            stdout, stderr = await proc.communicate()
            exit_code = proc.returncode if proc.returncode is not None else -1
            if stdout:
                log.info("Script %s stdout: %s",
                         name, stdout.decode(errors="replace").strip())
            if stderr:
                log.warning("Script %s stderr: %s",
                            name, stderr.decode(errors="replace").strip())
            if report_meta.enabled:
                await self._notify_script_report(name, report_meta.sinks, stdout, stderr, exit_code, report_meta)
            log.info("スクリプト終了: %s (exit_code=%d)", name, exit_code)
        except Exception as exc:
            log.error("スクリプト実行エラー: %s: %s", name, exc)
            exit_code = -1
        self._script_exit_notify(name, exit_code)

    def _resolve_shell_script(self, name: str) -> str:
        for script_dir in self._script_dirs:
            script_path = os.path.join(script_dir, f"{name}.sh")
            if os.path.isfile(script_path):
                return script_path
        return ""

    def _load_script_report_metadata(self, script_path: str):
        try:
            text = Path(script_path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            log.warning("script report metadata read failed: %s: %s", script_path, exc)
            return parse_script_report_metadata("")
        return parse_script_report_metadata(text)

    async def _notify_script_report(self, name: str, sinks: tuple[str, ...], stdout: bytes, stderr: bytes, exit_code: int, metadata) -> None:
        chunks = []
        if stdout:
            chunks.append(stdout)
        if stderr:
            if chunks and not chunks[-1].endswith(b"\n"):
                chunks.append(b"\n")
            chunks.append(b"[stderr]\n")
            chunks.append(stderr)
        if not chunks:
            return
        text, _truncated = sanitize_report_text(b"".join(chunks), metadata)
        if not text:
            return
        for sink in sinks:
            if sink == "hid_text":
                await self._type_string(text)
            try:
                self._script_report_notify(name, sink, text, exit_code)
            except Exception as exc:
                log.warning("script report notify failed: %s sink=%s: %s", name, sink, exc)

    def _shell_script_env(self) -> dict[str, str]:
        env = os.environ.copy()
        repo_root = str(_REPO_ROOT)
        bin_dir = str(_REPO_ROOT / "bin")
        current_path = env.get("PATH", "")
        parts = [part for part in current_path.split(os.pathsep) if part]
        if bin_dir not in parts:
            env["PATH"] = os.pathsep.join([bin_dir, *parts])
        env.setdefault("HIDLOOM_REPO_ROOT", repo_root)
        return env

    # ------------------------------------------------------------------
    # Mouse continuous movement
    # ------------------------------------------------------------------

    async def _mouse_repeat(self, code: int, delta: tuple) -> None:
        """押し続けている間、マウスカーソルを継続的に移動させる。"""
        dx, dy, dw = delta
        loop = asyncio.get_event_loop()
        try:
            while True:
                report = self._mouse_state.build_move(dx, dy, dw)
                await loop.run_in_executor(None, self._mouse_write, report)
                await asyncio.sleep(0.016)   # ~60fps (16ms 間隔)
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _tap(
        self, code: int, add_mod_bits: int = 0, hold: float = _KEY_HOLD
    ) -> None:
        """Press and release one key, then wait for gap."""
        if add_mod_bits:
            self._state.set_mod_bits(add_mod_bits)
        self._state.press(code)
        self._write(self._state.build())
        await asyncio.sleep(hold)
        self._state.release(code)
        if add_mod_bits:
            self._state.clear_mod_bits(add_mod_bits)
        self._write(self._state.build())
        await asyncio.sleep(_KEY_GAP)

    async def _unicode(self, hex_str: str) -> None:
        """Windows unicode input: type hex string → F5 → Enter."""
        for ch in hex_str.upper():
            pair = _CHAR_MAP.get(ch)
            if pair:
                mod, code = pair
                await self._tap(code, mod)
        await self._tap(KEYCODE["KC_F5"])
        await self._tap(KEYCODE["KC_ENTER"])

    async def _type_string(self, text: str) -> None:
        for ch in text:
            pair = _CHAR_MAP.get(ch)
            if pair is None:
                continue
            mod, code = pair
            await self._tap(code, mod)

    async def _run_named(self, name: str) -> None:
        macro_def = self._macros.get(name)
        if macro_def is None:
            log.warning("Macro '%s' not found", name)
            return
        await self._exec(macro_def)

    async def _exec(self, macro_def: Any) -> None:
        """Execute a macro definition (str or list of tokens)."""
        if isinstance(macro_def, str):
            await self._type_string(macro_def)
            return
        for item in macro_def:
            if not isinstance(item, str):
                continue
            if item.startswith("{KC:") and item.endswith("}"):
                await self._tap(KEYCODE.get(item[4:-1], 0))
            elif item.startswith("{KC_DOWN:") and item.endswith("}"):
                code = KEYCODE.get(item[9:-1], 0)
                if code:
                    self._state.press(code)
                    self._write(self._state.build())
            elif item.startswith("{KC_UP:") and item.endswith("}"):
                code = KEYCODE.get(item[7:-1], 0)
                if code:
                    self._state.release(code)
                    self._write(self._state.build())
            elif item.startswith("{DELAY:") and item.endswith("}"):
                try:
                    delay_ms = max(0, min(60000, int(item[7:-1])))
                except ValueError:
                    delay_ms = 0
                if delay_ms:
                    await asyncio.sleep(delay_ms / 1000.0)
            elif item.startswith("{U+") and item.endswith("}"):
                await self._unicode(item[3:-1])
            elif item == "{IME_ON}":
                await self._tap(KEYCODE["KC_KANA"])
            elif item == "{IME_OFF}":
                await self._tap(KEYCODE["KC_GRAVE"])
            else:
                await self._type_string(item)
