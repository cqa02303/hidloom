"""Pure helpers for the sessiond PTY mirror M0."""
from __future__ import annotations

from dataclasses import dataclass
import fcntl
import os
import pty
import select
import shlex
import signal
import subprocess
import termios
import time
from typing import Iterable, Mapping

ESC = "\x1b"

CONTROL_ACTION_BYTES: Mapping[str, bytes] = {
    "KC_ENTER": b"\r",
    "KC_ENT": b"\r",
    "KC_RETURN": b"\r",
    "KC_TAB": b"\t",
    "KC_BSPC": b"\x7f",
    "KC_BSPACE": b"\x7f",
    "KC_BACKSPACE": b"\x7f",
    "KC_ESC": b"\x1b",
    "KC_LEFT": b"\x1b[D",
    "KC_RGHT": b"\x1b[C",
    "KC_RIGHT": b"\x1b[C",
    "KC_UP": b"\x1b[A",
    "KC_DOWN": b"\x1b[B",
    "KC_HOME": b"\x1b[H",
    "KC_END": b"\x1b[F",
    "KC_DEL": b"\x1b[3~",
    "KC_DELETE": b"\x1b[3~",
    "C(KC_C)": b"\x03",
    "C(KC_D)": b"\x04",
}

_BASE_KEY_CHARS: Mapping[str, str] = {
    "KC_A": "a",
    "KC_B": "b",
    "KC_C": "c",
    "KC_D": "d",
    "KC_E": "e",
    "KC_F": "f",
    "KC_G": "g",
    "KC_H": "h",
    "KC_I": "i",
    "KC_J": "j",
    "KC_K": "k",
    "KC_L": "l",
    "KC_M": "m",
    "KC_N": "n",
    "KC_O": "o",
    "KC_P": "p",
    "KC_Q": "q",
    "KC_R": "r",
    "KC_S": "s",
    "KC_T": "t",
    "KC_U": "u",
    "KC_V": "v",
    "KC_W": "w",
    "KC_X": "x",
    "KC_Y": "y",
    "KC_Z": "z",
    "KC_1": "1",
    "KC_2": "2",
    "KC_3": "3",
    "KC_4": "4",
    "KC_5": "5",
    "KC_6": "6",
    "KC_7": "7",
    "KC_8": "8",
    "KC_9": "9",
    "KC_0": "0",
    "KC_SPACE": " ",
    "KC_SPC": " ",
    "KC_MINUS": "-",
    "KC_MINS": "-",
    "KC_EQUAL": "=",
    "KC_EQL": "=",
    "KC_LBRACKET": "[",
    "KC_LBRC": "[",
    "KC_RBRACKET": "]",
    "KC_RBRC": "]",
    "KC_NUHS": "]",
    "KC_BSLASH": "\\",
    "KC_SCOLON": ";",
    "KC_SCLN": ";",
    "KC_QUOTE": "'",
    "KC_QUOT": "'",
    "KC_GRAVE": "`",
    "KC_COMMA": ",",
    "KC_COMM": ",",
    "KC_DOT": ".",
    "KC_SLASH": "/",
    "KC_SLSH": "/",
}

_SHIFT_KEY_CHARS: Mapping[str, str] = {
    "KC_A": "A",
    "KC_B": "B",
    "KC_C": "C",
    "KC_D": "D",
    "KC_E": "E",
    "KC_F": "F",
    "KC_G": "G",
    "KC_H": "H",
    "KC_I": "I",
    "KC_J": "J",
    "KC_K": "K",
    "KC_L": "L",
    "KC_M": "M",
    "KC_N": "N",
    "KC_O": "O",
    "KC_P": "P",
    "KC_Q": "Q",
    "KC_R": "R",
    "KC_S": "S",
    "KC_T": "T",
    "KC_U": "U",
    "KC_V": "V",
    "KC_W": "W",
    "KC_X": "X",
    "KC_Y": "Y",
    "KC_Z": "Z",
    "KC_1": "!",
    "KC_2": "@",
    "KC_3": "#",
    "KC_4": "$",
    "KC_5": "%",
    "KC_6": "^",
    "KC_7": "&",
    "KC_8": "*",
    "KC_9": "(",
    "KC_0": ")",
    "KC_MINUS": "_",
    "KC_MINS": "_",
    "KC_EQUAL": "+",
    "KC_EQL": "+",
    "KC_LBRACKET": "{",
    "KC_LBRC": "{",
    "KC_RBRACKET": "}",
    "KC_RBRC": "}",
    "KC_NUHS": "}",
    "KC_BSLASH": "|",
    "KC_SCOLON": ":",
    "KC_SCLN": ":",
    "KC_QUOTE": '"',
    "KC_QUOT": '"',
    "KC_GRAVE": "~",
    "KC_COMMA": "<",
    "KC_COMM": "<",
    "KC_DOT": ">",
    "KC_SLASH": "?",
    "KC_SLSH": "?",
}

SHIFT_MODIFIERS = frozenset({
    "KC_LSFT",
    "KC_RSFT",
    "KC_LSHIFT",
    "KC_RSHIFT",
    "LSFT",
    "RSFT",
    "LSHIFT",
    "RSHIFT",
    "SHIFT",
})
CTRL_MODIFIERS = frozenset({
    "KC_LCTL",
    "KC_RCTL",
    "KC_LCTRL",
    "KC_RCTRL",
    "LCTL",
    "RCTL",
    "LCTRL",
    "RCTRL",
    "CTRL",
    "CONTROL",
})


def key_action_to_pty_bytes(action: str, *, is_press: bool = True, active_modifiers: Iterable[str] = ()) -> bytes:
    """Translate a small M0 key action subset to PTY input bytes."""
    if not is_press:
        return b""
    normalized = str(action or "").strip()
    if not normalized:
        return b""
    if normalized in CONTROL_ACTION_BYTES:
        return CONTROL_ACTION_BYTES[normalized]

    modifiers = {str(mod).strip().upper() for mod in active_modifiers}
    if modifiers & CTRL_MODIFIERS and normalized.startswith("KC_") and len(normalized) == 4:
        letter = normalized[-1]
        if "A" <= letter <= "Z":
            return bytes([ord(letter) - ord("A") + 1])

    shifted = bool(modifiers & SHIFT_MODIFIERS)
    table = _SHIFT_KEY_CHARS if shifted else _BASE_KEY_CHARS
    char = table.get(normalized)
    if char is None:
        return b""
    return char.encode("ascii")


def clip_line(text: str, columns: int) -> str:
    if columns <= 0:
        return ""
    cleaned = "".join(ch if ch >= " " else " " for ch in text.replace("\t", "    "))
    return cleaned[:columns]


def normalize_screen(lines: Iterable[str], *, rows: int, columns: int) -> tuple[str, ...]:
    clipped = [clip_line(str(line), columns) for line in lines]
    if rows <= 0:
        return tuple()
    if len(clipped) < rows:
        clipped.extend([""] * (rows - len(clipped)))
    return tuple(clipped[:rows])


@dataclass(frozen=True)
class RowUpdate:
    row: int
    text: str


def diff_rows(previous: Iterable[str], current: Iterable[str], *, rows: int, columns: int) -> list[RowUpdate]:
    prev = normalize_screen(previous, rows=rows, columns=columns)
    cur = normalize_screen(current, rows=rows, columns=columns)
    return [RowUpdate(index + 1, text) for index, text in enumerate(cur) if prev[index] != text]


def render_initial_frame(lines: Iterable[str], *, rows: int, columns: int) -> str:
    screen = normalize_screen(lines, rows=rows, columns=columns)
    body = "\r\n".join(screen).rstrip()
    return f"{ESC}[2J{ESC}[H{body}"


def render_row_updates(updates: Iterable[RowUpdate]) -> str:
    chunks: list[str] = []
    for update in updates:
        if update.row <= 0:
            continue
        chunks.append(f"{ESC}[{update.row};1H{update.text}{ESC}[K")
    return "".join(chunks)


def render_cursor(row: int, column: int) -> str:
    safe_row = max(1, int(row))
    safe_column = max(1, int(column))
    return f"{ESC}[{safe_row};{safe_column}H"


class PtyMirrorSession:
    """Small PTY process wrapper for M0 local tests and sessiond wiring."""

    def __init__(self, command: str = "bash", *, rows: int = 35, columns: int = 120) -> None:
        self.command = command
        self.rows = rows
        self.columns = columns
        self.master_fd: int | None = None
        self.process: subprocess.Popen[bytes] | None = None

    @property
    def active(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self) -> None:
        if self.active:
            raise RuntimeError("PTY mirror session is already active")
        argv = shlex.split(self.command) or ["bash"]
        master_fd, slave_fd = pty.openpty()
        attrs = termios.tcgetattr(slave_fd)
        attrs[3] &= ~termios.ECHO
        termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)
        env = os.environ.copy()
        env.update({
            "TERM": "xterm-256color",
            "COLUMNS": str(self.columns),
            "LINES": str(self.rows),
            "LC_ALL": "C",
            "LANG": "C",
        })

        def child_setup() -> None:
            for sig in (signal.SIGINT, signal.SIGQUIT, signal.SIGTERM):
                signal.signal(sig, signal.SIG_DFL)
            os.setsid()
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

        try:
            self.process = subprocess.Popen(
                argv,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                env=env,
                close_fds=True,
                preexec_fn=child_setup,
            )
        except Exception:
            os.close(master_fd)
            raise
        finally:
            os.close(slave_fd)
        self.master_fd = master_fd

    def write(self, data: bytes) -> int:
        if self.master_fd is None or not self.active:
            return 0
        if not data:
            return 0
        return os.write(self.master_fd, data)

    def write_key_action(self, action: str, *, is_press: bool = True, active_modifiers: Iterable[str] = ()) -> int:
        return self.write(key_action_to_pty_bytes(action, is_press=is_press, active_modifiers=active_modifiers))

    def interrupt(self) -> bool:
        process = self.process
        if process is None or process.poll() is not None:
            return False
        target_pgids = {process.pid}
        if self.master_fd is not None:
            try:
                target_pgids.add(os.tcgetpgrp(self.master_fd))
            except OSError:
                pass
        target_pgids.update(_process_groups_in_session(process.pid))
        sent = False
        for target_pgid in sorted(target_pgids):
            try:
                os.killpg(target_pgid, signal.SIGINT)
            except ProcessLookupError:
                continue
            sent = True
        return sent

    def read_available(self, *, timeout: float = 0.0, max_bytes: int = 4096) -> bytes:
        if self.master_fd is None:
            return b""
        ready, _write, _error = select.select([self.master_fd], [], [], max(0.0, timeout))
        if not ready:
            return b""
        try:
            return os.read(self.master_fd, max_bytes)
        except OSError:
            return b""

    def read_text_until_quiet(self, *, timeout: float = 0.5, quiet_sec: float = 0.05, max_bytes: int = 8192) -> str:
        deadline = time.monotonic() + max(0.0, timeout)
        quiet_deadline = time.monotonic() + max(0.0, quiet_sec)
        chunks: list[bytes] = []
        total = 0
        limit = max(256, int(max_bytes or 8192))
        while time.monotonic() < deadline:
            remaining = max(1, limit - total)
            chunk = self.read_available(timeout=0.01, max_bytes=min(4096, remaining))
            if chunk:
                chunks.append(chunk)
                total += len(chunk)
                if total >= limit:
                    break
                quiet_deadline = time.monotonic() + max(0.0, quiet_sec)
                continue
            if chunks and time.monotonic() >= quiet_deadline:
                break
            if not self.active and not chunk:
                break
        return b"".join(chunks).decode(errors="replace")

    def wait(self, *, timeout: float = 1.0) -> int | None:
        if self.process is None:
            return None
        try:
            return self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    def terminate(self) -> None:
        process = self.process
        if process is None or process.poll() is not None:
            self.close()
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        self.wait(timeout=0.5)
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.wait(timeout=0.5)
        self.close()

    def close(self) -> None:
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = None

    def __enter__(self) -> "PtyMirrorSession":
        self.start()
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.terminate()


def _process_groups_in_session(session_id: int) -> set[int]:
    groups: set[int] = set()
    proc = "/proc"
    try:
        entries = os.listdir(proc)
    except OSError:
        return groups
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(os.path.join(proc, entry, "stat"), "r", encoding="utf-8") as fh:
                stat = fh.read()
        except OSError:
            continue
        close = stat.rfind(")")
        if close < 0:
            continue
        fields = stat[close + 2 :].split()
        if len(fields) < 4:
            continue
        try:
            pgrp = int(fields[2])
            sid = int(fields[3])
        except ValueError:
            continue
        if sid == session_id:
            groups.add(pgrp)
    return groups
