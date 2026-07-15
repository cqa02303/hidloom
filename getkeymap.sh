#!/bin/bash
#
# getkeymap.sh - logicd のオンメモリキーマップを取得する
#
# Usage:
#   getkeymap.sh [--pretty]
#
# オプション:
#   --pretty   jq で整形して表示（jq が必要）
#
# 動作:
#   ctrl_events.sock に {"t":"G"} コマンドを送信し、
#   現在のキーマップ状態を JSON で取得します。
#
# 出力形式:
#   {
#     "t": "keymap",
#     "layers": [
#       {"7,0": "KC_ESC", "6,0": "KC_F1", ...},
#       {"7,0": "KC_GRAVE", ...}
#     ],
#     "active": {
#       "momentary": [1, 2],
#       "toggled": [3],
#       "all": [3, 2, 1, 0]
#     }
#   }
#

SOCKET="/tmp/ctrl_events.sock"
PRETTY=false

# 引数処理
while [[ $# -gt 0 ]]; do
    case $1 in
        --pretty)
            PRETTY=true
            shift
            ;;
        --socket)
            SOCKET="$2"
            shift 2
            ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Use --help for usage information" >&2
            exit 1
            ;;
    esac
done

# ソケットが存在するか確認
if [[ ! -S "$SOCKET" ]]; then
    echo "Error: Socket not found: $SOCKET" >&2
    echo "Is logicd running?" >&2
    exit 1
fi

# python3 が利用可能か確認
if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 is required but not installed" >&2
    exit 1
fi

# ctrl_events.sock に接続してキーマップを取得
# タイムアウト付きで実行（1秒）
RESPONSE=$(SOCKET="$SOCKET" timeout 1 python3 - <<'PY' 2>/dev/null
import json
import os
import socket

sock_path = os.environ["SOCKET"]
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
    sock.connect(sock_path)
    sock.sendall(json.dumps({"t": "G"}).encode("utf-8") + b"\n")
    data = b""
    while not data.endswith(b"\n"):
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
print(data.decode("utf-8").strip())
PY
)
EXIT_CODE=$?

if [[ $EXIT_CODE -eq 124 ]]; then
    echo "Error: Request timed out" >&2
    exit 1
elif [[ $EXIT_CODE -ne 0 ]]; then
    echo "Error: Failed to connect to $SOCKET (exit code: $EXIT_CODE)" >&2
    exit 1
fi

if [[ -z "$RESPONSE" ]]; then
    echo "Error: No response from logicd" >&2
    exit 1
fi

# 出力
if [[ "$PRETTY" == "true" ]]; then
    if command -v jq >/dev/null 2>&1; then
        echo "$RESPONSE" | jq .
    else
        echo "Warning: jq not installed, showing raw JSON" >&2
        echo "$RESPONSE"
    fi
else
    echo "$RESPONSE"
fi
