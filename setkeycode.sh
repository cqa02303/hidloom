#!/bin/bash
# setkeycode.sh - Set keycode dynamically in logicd
# Usage: setkeycode.sh [--layer NUM] [--socket PATH] POSITION ACTION

set -e

SOCKET="/tmp/ctrl_events.sock"
LAYER=0
TIMEOUT=1

usage() {
    cat <<EOF
Usage: $0 [OPTIONS] POSITION ACTION

Set a keycode dynamically in logicd's in-memory keymap.

Arguments:
  POSITION    Key position in "row,col" format (e.g., "7,0")
  ACTION      Key action (e.g., "KC_ESC", "KC_A", "MO(1)")

Options:
  --layer NUM      Layer number to modify (default: 0)
  --socket PATH    Custom socket path (default: /tmp/ctrl_events.sock)
  -h, --help       Show this help message

Examples:
  # Set ESC key at position (7,0) on layer 0
  $0 7,0 KC_ESC

  # Set GRAVE key at position (7,0) on layer 1
  $0 --layer 1 7,0 KC_GRAVE

  # Set layer switch key MO(1)
  $0 --layer 0 4,0 MO(1)

Exit codes:
  0  Success
  1  Error (invalid arguments, socket not found, request failed)

EOF
    exit 0
}

error() {
    echo "Error: $*" >&2
    exit 1
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            ;;
        --layer)
            shift
            LAYER="$1"
            [[ -z "$LAYER" ]] && error "--layer requires a number"
            [[ ! "$LAYER" =~ ^[0-9]+$ ]] && error "Invalid layer number: $LAYER"
            shift
            ;;
        --socket)
            shift
            SOCKET="$1"
            [[ -z "$SOCKET" ]] && error "--socket requires a path"
            shift
            ;;
        -*)
            error "Unknown option: $1"
            ;;
        *)
            break
            ;;
    esac
done

# Validate required arguments
[[ $# -ne 2 ]] && error "POSITION and ACTION are required. Use --help for usage."

POSITION="$1"
ACTION="$2"

# Validate position format (should be "row,col")
[[ ! "$POSITION" =~ ^[0-9]+,[0-9]+$ ]] && error "Invalid position format: $POSITION (expected: row,col)"

# Parse row and col
ROW="${POSITION%,*}"
COL="${POSITION#*,}"

# Check if socket exists
[[ ! -S "$SOCKET" ]] && error "Socket not found: $SOCKET\nIs logicd running?"

# Check if python3 is available
if ! command -v python3 &> /dev/null; then
    error "python3 is required but not installed"
fi

# Send request and get response
RESPONSE=$(SOCKET="$SOCKET" LAYER="$LAYER" ROW="$ROW" COL="$COL" ACTION="$ACTION" timeout "$TIMEOUT" python3 - <<'PY' 2>&1
import json
import os
import socket

payload = {
    "t": "M",
    "l": int(os.environ["LAYER"]),
    "r": int(os.environ["ROW"]),
    "c": int(os.environ["COL"]),
    "a": os.environ["ACTION"],
}

with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
    sock.connect(os.environ["SOCKET"])
    sock.sendall(json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n")
    data = b""
    while not data.endswith(b"\n"):
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
print(data.decode("utf-8").strip())
PY
)

if [[ -z "$RESPONSE" ]]; then
    error "Request timed out"
fi

# Parse response (M command returns {"t":"M","result":"ok/error",...})
RESULT=$(echo "$RESPONSE" | grep -o '"result":"[^"]*"' | cut -d'"' -f4)

if [[ "$RESULT" == "ok" ]]; then
    echo "Success: Layer $LAYER, position $POSITION set to $ACTION"
    exit 0
else
    ERROR_MSG=$(echo "$RESPONSE" | grep -o '"msg":"[^"]*"' | cut -d'"' -f4)
    error "Failed to set keycode: ${ERROR_MSG:-Unknown error}\nResponse: $RESPONSE"
fi
