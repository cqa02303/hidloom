#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd "$SCRIPT_DIR/../.." && pwd)
BIN_DIR=${BIN_DIR:-"$REPO_ROOT/bin"}
MAKE=${MAKE:-make}

python3 "$REPO_ROOT/tools/generated_binary_hygiene.py" \
    --root "$REPO_ROOT" --extra-bin-dir "$BIN_DIR" --clean
"$MAKE" -C "$SCRIPT_DIR" clean all install BIN_DIR="$BIN_DIR"

printf 'installed: %s/hidloom-key\n' "$BIN_DIR"
printf 'installed: %s/hidloom-keytext\n' "$BIN_DIR"
printf 'installed: %s/hidloom-oled\n' "$BIN_DIR"
printf 'installed: %s/hidloom-notify\n' "$BIN_DIR"
printf 'installed: %s/hidloom-ctrl\n' "$BIN_DIR"
