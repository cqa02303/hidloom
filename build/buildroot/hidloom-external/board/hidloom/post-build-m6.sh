#!/bin/sh
set -eu

TARGET_DIR=$1
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../../../../.." && pwd)
NATIVE_DIR=${HIDLOOM_M6_NATIVE_DIR:-$ROOT/build/artifacts/buildroot-m4-native/bin}
HIDLOOM_DIR=$TARGET_DIR/usr/share/hidloom

for binary in hidloom-hidd hidloom-logicd-core hidloom-outputd hidloom-uidd; do
    test -x "$NATIVE_DIR/$binary" || {
        echo "M6 native binary missing: $NATIVE_DIR/$binary" >&2
        exit 1
    }
    install -D -m 0755 "$NATIVE_DIR/$binary" "$TARGET_DIR/usr/bin/$binary"
done

rm -rf "$HIDLOOM_DIR"
install -d "$HIDLOOM_DIR/daemon" "$HIDLOOM_DIR/config"
for module in logicd viald i2cd ledd usbd; do
    cp -a "$ROOT/daemon/$module" "$HIDLOOM_DIR/daemon/"
done
cp -a "$ROOT/config/." "$HIDLOOM_DIR/config/"
install -m 0644 "$ROOT/hidloom_paths.py" "$HIDLOOM_DIR/hidloom_paths.py"
install -m 0644 "$ROOT/vialrgb_effects.py" "$HIDLOOM_DIR/vialrgb_effects.py"
find "$HIDLOOM_DIR" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$HIDLOOM_DIR" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
chmod 0440 "$TARGET_DIR/etc/sudoers.d/pi"
rm -f "$TARGET_DIR/etc/init.d/S25hidloom-m3-router"

install -d "$TARGET_DIR/mnt/p3"
for name in config keymap vial; do
    install -m 0644 "$ROOT/config/default/$name.json" "$TARGET_DIR/mnt/p3/$name.json"
done
