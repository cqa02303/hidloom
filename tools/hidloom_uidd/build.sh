#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
BIN_DIR=${BIN_DIR:-"$REPO_ROOT/bin"}

python3 "$REPO_ROOT/tools/generated_binary_hygiene.py" \
    --root "$REPO_ROOT" --extra-bin-dir "$BIN_DIR" --clean
make -C "$SCRIPT_DIR" install BIN_DIR="$BIN_DIR"
printf 'installed: %s/hidloom-uidd\n' "$BIN_DIR"
