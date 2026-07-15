#!/usr/bin/env python3
"""
sendkey - キーイベントを key_events.sock に送信する CLI コマンド

Usage:
    sendkey press <keycode> [modifier]   # キーを押す
    sendkey release <keycode> [modifier] # キーを離す
    sendkey tap <keycode> [modifier]     # キーをタップ (press → release)

Arguments:
    keycode:  16進数 (0x04) または10進数 (4) のHIDキーコード
    modifier: モディファイアビット (省略時は0)
              bit0=LCtrl, bit1=LShift, bit2=LAlt, bit3=LWin
              bit4=RCtrl, bit5=RShift, bit6=RAlt, bit7=RWin

Examples:
    sendkey tap 0x04           # 'A' キーをタップ
    sendkey tap 0x04 0x02      # Shift+'A' (大文字A) をタップ
    sendkey press 0xe0         # 左Ctrlを押す
    sendkey release 0xe0       # 左Ctrlを離す
"""

import socket
import sys
import time
from pathlib import Path


DEFAULT_SOCKET_PATH = "/tmp/key_events.sock"


def parse_int(s: str) -> int:
    """16進数または10進数の文字列を整数に変換する。"""
    s = s.strip()
    if s.startswith("0x") or s.startswith("0X"):
        return int(s, 16)
    return int(s, 10)


def send_event(sock: socket.socket, event_type: str, keycode: int, modifier: int) -> None:
    """key_events.sock にイベントを送信する。

    Args:
        sock: Unixドメインソケット
        event_type: "press" または "release"
        keycode: HIDキーコード (0x00-0xFF)
        modifier: モディファイアビット (0x00-0xFF)
    """
    event_byte = 0x50 if event_type == "press" else 0x52  # 'P' or 'R'
    packet = bytes([event_byte, keycode & 0xFF, modifier & 0xFF, 0x00])
    sock.sendall(packet)


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()

    if command not in ("press", "release", "tap"):
        print(f"Error: Unknown command '{command}'")
        print(__doc__)
        sys.exit(1)

    try:
        keycode = parse_int(sys.argv[2])
    except ValueError:
        print(f"Error: Invalid keycode '{sys.argv[2]}'")
        sys.exit(1)

    modifier = 0
    if len(sys.argv) >= 4:
        try:
            modifier = parse_int(sys.argv[3])
        except ValueError:
            print(f"Error: Invalid modifier '{sys.argv[3]}'")
            sys.exit(1)

    # Socket path from config (future: load from config file)
    socket_path = DEFAULT_SOCKET_PATH

    if not Path(socket_path).exists():
        print(f"Error: Socket not found: {socket_path}")
        print("Is logicd running?")
        sys.exit(1)

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(socket_path)

        if command == "tap":
            # Press → wait → Release
            send_event(sock, "press", keycode, modifier)
            time.sleep(0.05)  # 50ms hold
            send_event(sock, "release", keycode, modifier)
            print(f"Tapped: keycode=0x{keycode:02x} modifier=0x{modifier:02x}")
        else:
            send_event(sock, command, keycode, modifier)
            print(f"{command.capitalize()}: keycode=0x{keycode:02x} modifier=0x{modifier:02x}")

        sock.close()
    except ConnectionRefusedError:
        print(f"Error: Connection refused to {socket_path}")
        print("Is logicd running?")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
