#!/usr/bin/env python3
r"""
kml - Keyboard Macro Language インタープリター

Usage:
    kml <kml_file>              # KMLファイルを実行
    kml -c <kml_string>         # コマンドライン引数のKML文字列を実行
    kml --debug <kml_file>      # デバッグモード（標準出力のみ、ソケット送信なし）
    kml -c --debug <kml_string> # デバッグモード（文字列）

KML Specification:
    詳細は KML.md を参照してください。

Examples:
    # ファイルから実行
    kml copy_paste.kml

    # 文字列を直接実行（シングルクォート推奨）
    kml -c '\T180 \[Ctrl c \] \R8 [End] \n \[Ctrl v \]'

    # デバッグモード
    kml --debug test.kml
"""

import json
import re
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


# デフォルト設定
DEFAULT_SOCKET_PATH = "/tmp/key_events.sock"
DEFAULT_TEMPO = 120  # BPM
DEFAULT_LENGTH = 4   # 4分音符
DEFAULT_KEYHOLD_MS = 50  # キーを押す時間（ms）


# キーコードマッピング（keycodes.jsonから抽出）
KEYCODE_MAP = {
    # アルファベット
    "A": 4, "B": 5, "C": 6, "D": 7, "E": 8, "F": 9, "G": 10, "H": 11,
    "I": 12, "J": 13, "K": 14, "L": 15, "M": 16, "N": 17, "O": 18, "P": 19,
    "Q": 20, "R": 21, "S": 22, "T": 23, "U": 24, "V": 25, "W": 26, "X": 27,
    "Y": 28, "Z": 29,
    # 数字
    "1": 30, "2": 31, "3": 32, "4": 33, "5": 34,
    "6": 35, "7": 36, "8": 37, "9": 38, "0": 39,
    # 特殊キー（角括弧用）
    "Enter": 40, "Esc": 41, "Escape": 41, "Backspace": 42, "Tab": 43,
    "Space": 44, "Minus": 45, "Equal": 46,
    "F1": 58, "F2": 59, "F3": 60, "F4": 61, "F5": 62, "F6": 63,
    "F7": 64, "F8": 65, "F9": 66, "F10": 67, "F11": 68, "F12": 69,
    "Insert": 73, "Delete": 76, "Home": 74, "End": 77,
    "PageUp": 75, "PageDown": 78, "PgUp": 75, "PgDn": 78,
    "Up": 82, "Down": 81, "Left": 80, "Right": 79,
    # モディファイアキー
    "Ctrl": 224, "LCtrl": 224, "RCtrl": 228,
    "Shift": 225, "LShift": 225, "RShift": 229,
    "Alt": 226, "LAlt": 226, "RAlt": 230,
    "Win": 227, "LWin": 227, "RWin": 231,
    "GUI": 227, "Command": 227, "Cmd": 227,
}

# モディファイアビットマップ
MODIFIER_BITS = {
    224: 0x01,  # LCtrl
    225: 0x02,  # LShift
    226: 0x04,  # LAlt
    227: 0x08,  # LWin
    228: 0x10,  # RCtrl
    229: 0x20,  # RShift
    230: 0x40,  # RAlt
    231: 0x80,  # RWin
}


@dataclass
class KMLEvent:
    """KMLイベント（キー操作）"""
    event_type: str  # "press" or "release"
    keycode: int
    modifier: int
    delay_before_ms: int = 0  # イベント前の待機時間（ms）
    duration_ms: int = DEFAULT_KEYHOLD_MS  # キーを押す時間（ms）


class KMLParser:
    """KML文字列をパースしてイベントシーケンスに変換する。"""

    def __init__(self, debug: bool = False):
        self.debug = debug
        self.tempo = DEFAULT_TEMPO
        self.default_length = DEFAULT_LENGTH
        self.events: List[KMLEvent] = []
        self.modifier_stack: List[int] = [0]  # モディファイアスタック

    def parse(self, kml: str) -> List[KMLEvent]:
        """KML文字列を解析してイベントリストを生成する。"""
        self.events = []
        self.modifier_stack = [0]

        # 行ごとに処理してコメント（#で始まる行）を除去
        lines = []
        for line in kml.split('\n'):
            # '#' で始まる行はコメントとして無視
            stripped = line.strip()
            if not stripped.startswith('#'):
                lines.append(line)
        kml = '\n'.join(lines)

        i = 0
        while i < len(kml):
            # 空白をスキップ
            if kml[i] in (' ', '\t', '\n'):
                i += 1
                continue

            if kml[i] == '\\':
                i = self._parse_escape(kml, i)
            elif kml[i] == '[':
                i = self._parse_special_key(kml, i)
            else:
                i = self._parse_character(kml, i)

        return self.events

    def _parse_escape(self, kml: str, i: int) -> int:
        """エスケープシーケンスを処理する。"""
        if i + 1 >= len(kml):
            return i + 1

        cmd = kml[i + 1]

        # KMLコマンド（大文字）
        if cmd == 'T':  # Tempo
            return self._parse_command_value(kml, i, 'tempo')
        elif cmd == 'L':  # Length
            return self._parse_command_value(kml, i, 'length')
        elif cmd == 'R':  # Rest
            return self._parse_command_value(kml, i, 'rest')
        elif cmd == 'O':  # Octave (未実装: 将来のレイヤー切り替え用)
            return self._parse_command_value(kml, i, 'octave')
        elif cmd == '[':  # 範囲制御開始
            return self._parse_range_start(kml, i + 2)
        elif cmd == ']':  # 範囲制御終了
            return self._parse_range_end(kml, i + 2)

        # シェルエスケープシーケンス（小文字）
        elif cmd == 'n':  # 改行
            self._add_tap_event(40, 0)  # Enter
            return i + 2
        elif cmd == 'r':  # 復帰（未実装）
            return i + 2
        elif cmd == 't':  # タブ
            self._add_tap_event(43, 0)  # Tab
            return i + 2
        elif cmd == 'b':  # バックスペース
            self._add_tap_event(42, 0)  # Backspace
            return i + 2
        elif cmd == 's':  # スペース
            self._add_tap_event(44, 0)  # Space
            return i + 2
        elif cmd == '\\':  # バックスラッシュリテラル（未対応：要HID拡張）
            return i + 2
        elif cmd in ('"', "'"):  # 引用符リテラル（未対応）
            return i + 2
        else:
            # 不明なエスケープは無視
            return i + 2

    def _parse_command_value(self, kml: str, i: int, cmd_type: str) -> int:
        """\\T[120] または \\T120 のような値付きコマンドを解析する。"""
        # \\T[120] → i は \\ の位置
        # i+2 は [ または数値開始
        has_bracket = i + 2 < len(kml) and kml[i + 2] == '['

        if has_bracket:
            # 閉じ括弧を探す
            j = i + 3
            while j < len(kml) and kml[j].isdigit():
                j += 1

            if j >= len(kml) or kml[j] != ']':
                return i + 2

            value = int(kml[i + 3:j])
            next_pos = j + 1
        else:
            # 角括弧なし: \\T120 形式
            j = i + 2
            while j < len(kml) and kml[j].isdigit():
                j += 1

            if j == i + 2:  # 数値が見つからない
                return i + 2

            value = int(kml[i + 2:j])
            next_pos = j
            value = int(kml[i + 2:j])
            next_pos = j

        if cmd_type == 'tempo':
            self.tempo = value
            if self.debug:
                print(f"[CMD] Tempo = {value} BPM")
        elif cmd_type == 'length':
            self.default_length = value
            if self.debug:
                print(f"[CMD] Default Length = {value}")
        elif cmd_type == 'rest':
            rest_ms = self._length_to_ms(value)
            if self.debug:
                print(f"[CMD] Rest {value} = {rest_ms}ms")
            # 次のイベントに待機時間を追加するため、ダミーイベント挿入
            # 簡易実装: 直前イベントがあれば遅延追加、なければ最初のイベント用に保存
            if not hasattr(self, '_pending_rest_ms'):
                self._pending_rest_ms = 0
            self._pending_rest_ms += rest_ms
        elif cmd_type == 'octave':
            if self.debug:
                print(f"[CMD] Octave = {value} (未実装)")

        return next_pos

    def _parse_range_start(self, kml: str, i: int) -> int:
        """\\[ ... の範囲制御開始を処理する。

        \\[Ctrl c \\] のように、モディファイアキーを指定してから内容を記述。
        モディファイアは最初のスペースまたは非モディファイアキーで終了。
        """
        # モディファイアをパース（例: Ctrl+Shift）
        j = i
        modifiers = []

        # モディファイア部分を抽出（スペースまたは非英字が来たら終了）
        while j < len(kml):
            # 範囲終了チェック
            if kml[j:j+2] == '\\]':
                break

            # スペースはスキップ
            if kml[j] in (' ', '\t', '\n'):
                j += 1
                continue

            # アルファベットで始まるキー名を抽出
            if kml[j].isalpha():
                k = j
                while k < len(kml) and kml[k].isalnum():
                    k += 1
                key_name = kml[j:k]

                # モディファイアキーかチェック
                if key_name in ("Ctrl", "Shift", "Alt", "Win", "Command", "Cmd", "GUI",
                                "LCtrl", "RCtrl", "LShift", "RShift", "LAlt", "RAlt", "LWin", "RWin"):
                    if key_name in KEYCODE_MAP:
                        keycode = KEYCODE_MAP[key_name]
                        modifiers.append(keycode)
                    j = k
                    # '+' をスキップ
                    while j < len(kml) and kml[j] in ('+', ' ', '\t', '\n'):
                        j += 1
                else:
                    # モディファイアではない → 範囲内コンテンツ開始
                    break
            else:
                # 非英字が見つかった → コンテンツ開始
                break

        # モディファイアビットを計算
        modifier_bits = 0
        for mod_keycode in modifiers:
            if mod_keycode in MODIFIER_BITS:
                modifier_bits |= MODIFIER_BITS[mod_keycode]

        # スタックにプッシュ
        current_mod = self.modifier_stack[-1]
        self.modifier_stack.append(current_mod | modifier_bits)

        if self.debug:
            mod_names = [name for name, code in KEYCODE_MAP.items() if code in modifiers]
            print(f"[RANGE] Start: {'+'.join(mod_names) if mod_names else 'none'} (modifier=0x{self.modifier_stack[-1]:02x})")

        return j

    def _parse_range_end(self, kml: str, i: int) -> int:
        """\\] 範囲制御終了を処理する。"""
        if len(self.modifier_stack) <= 1:
            return i

        old_modifier = self.modifier_stack.pop()

        if self.debug:
            print(f"[RANGE] End")

        return i

    def _parse_special_key(self, kml: str, i: int) -> int:
        """[Enter] のような角括弧で囲まれた特殊キーを処理する。"""
        # '[' の位置が i
        j = i + 1
        while j < len(kml) and kml[j] != ']':
            j += 1

        if j >= len(kml):
            return i + 1

        key_name = kml[i + 1:j]

        if key_name in KEYCODE_MAP:
            keycode = KEYCODE_MAP[key_name]
            modifier = self.modifier_stack[-1]
            self._add_tap_event(keycode, modifier)

            if self.debug:
                print(f"[KEY] [{key_name}] = 0x{keycode:02x} mod=0x{modifier:02x}")
        else:
            if self.debug:
                print(f"[WARN] Unknown special key: [{key_name}]")

        return j + 1

    def _parse_character(self, kml: str, i: int) -> int:
        """通常の文字（A-Z, 0-9）を処理する。"""
        char = kml[i].upper()

        # 次の文字が数字なら長さ指定
        duration_length = self.default_length
        j = i + 1
        if j < len(kml) and kml[j].isdigit():
            duration_length = int(kml[j])
            j += 1

        if char in KEYCODE_MAP:
            keycode = KEYCODE_MAP[char]
            modifier = self.modifier_stack[-1]
            duration_ms = self._length_to_ms(duration_length)

            self._add_tap_event(keycode, modifier, duration_ms)

            if self.debug:
                print(f"[CHAR] '{char}' = 0x{keycode:02x} mod=0x{modifier:02x} len={duration_length} ({duration_ms}ms)")

            return j
        else:
            if self.debug:
                print(f"[WARN] Unknown character: '{char}'")
            return i + 1

    def _add_tap_event(self, keycode: int, modifier: int, duration_ms: int = DEFAULT_KEYHOLD_MS):
        """タップイベント（press → release）を追加する。"""
        # pending restがあれば最初のイベントに適用
        delay = 0
        if hasattr(self, '_pending_rest_ms') and self._pending_rest_ms > 0:
            delay = self._pending_rest_ms
            self._pending_rest_ms = 0

        self.events.append(KMLEvent("press", keycode, modifier, delay, duration_ms))
        self.events.append(KMLEvent("release", keycode, modifier, duration_ms, 0))

    def _length_to_ms(self, length: int) -> int:
        """音符の長さをミリ秒に変換する（BPMベース）。"""
        # 4分音符 = 60000 / BPM (ms)
        # n分音符 = (60000 / BPM) * (4 / n)
        quarter_note_ms = 60000 / self.tempo
        return int(quarter_note_ms * (4 / length))


class KMLExecutor:
    """KMLイベントを実行する。"""

    def __init__(self, socket_path: str = DEFAULT_SOCKET_PATH, debug: bool = False):
        self.socket_path = socket_path
        self.debug = debug
        self.sock: Optional[socket.socket] = None

    def execute(self, events: List[KMLEvent]) -> None:
        """イベントリストを実行する。"""
        if not self.debug:
            if not Path(self.socket_path).exists():
                print(f"Error: Socket not found: {self.socket_path}")
                print("Is logicd running?")
                sys.exit(1)

            try:
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.sock.connect(self.socket_path)
            except ConnectionRefusedError:
                print(f"Error: Connection refused to {self.socket_path}")
                print("Is logicd running?")
                sys.exit(1)

        for event in events:
            # 待機時間
            if event.delay_before_ms > 0:
                if self.debug:
                    print(f"  [WAIT] {event.delay_before_ms}ms")
                else:
                    time.sleep(event.delay_before_ms / 1000.0)

            # イベント送信
            if self.debug:
                action = "PRESS " if event.event_type == "press" else "RELEASE"
                print(f"  [{action}] keycode=0x{event.keycode:02x} mod=0x{event.modifier:02x}")
            else:
                self._send_event(event)

            # キー押下時間
            if event.event_type == "press" and event.duration_ms > 0:
                if not self.debug:
                    time.sleep(event.duration_ms / 1000.0)

        if self.sock:
            self.sock.close()

    def _send_event(self, event: KMLEvent) -> None:
        """key_events.sockにイベントを送信する。"""
        event_byte = 0x50 if event.event_type == "press" else 0x52  # 'P' or 'R'
        packet = bytes([event_byte, event.keycode & 0xFF, event.modifier & 0xFF, 0x00])
        if self.sock:
            self.sock.sendall(packet)


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    debug = "--debug" in sys.argv
    use_string = "-c" in sys.argv

    # 引数を整理
    args = [arg for arg in sys.argv[1:] if arg not in ("--debug", "-c")]

    if not args:
        print(__doc__)
        sys.exit(1)

    # KML文字列を取得
    if use_string:
        kml_string = args[0]
    else:
        kml_file = Path(args[0])
        if not kml_file.exists():
            print(f"Error: File not found: {kml_file}")
            sys.exit(1)
        kml_string = kml_file.read_text()

    if debug:
        print(f"=== KML Debug Mode ===")
        print(f"Input: {kml_string[:100]}...")
        print()

    # パース
    parser = KMLParser(debug=debug)
    events = parser.parse(kml_string)

    if debug:
        print()
        print(f"=== Execution ({len(events)} events) ===")

    # 実行
    executor = KMLExecutor(debug=debug)
    executor.execute(events)

    if debug:
        print()
        print("=== Completed ===")


if __name__ == "__main__":
    main()
