#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TARGET=armv7-unknown-linux-musleabihf
OUT=${1:-$ROOT/build/artifacts/buildroot-m4-native}
CARGO_TARGET_DIR=${HIDLOOM_M6_CARGO_TARGET_DIR:-$OUT/cargo-target}
export CARGO_TARGET_DIR

rustup target add "$TARGET"
mkdir -p "$OUT/bin"

for crate in hidloom_logicd_core hidloom_outputd hidloom_hidd hidloom_uidd; do
    cargo build --locked --manifest-path "$ROOT/tools/$crate/Cargo.toml" --release --target "$TARGET"
done

install -m 0755 "$CARGO_TARGET_DIR/$TARGET/release/hidloom-logicd-core" "$OUT/bin/"
install -m 0755 "$CARGO_TARGET_DIR/$TARGET/release/hidloom-outputd" "$OUT/bin/"
install -m 0755 "$CARGO_TARGET_DIR/$TARGET/release/hidloom-hidd" "$OUT/bin/"
install -m 0755 "$CARGO_TARGET_DIR/$TARGET/release/hidloom-uidd" "$OUT/bin/"

file "$OUT/bin/hidloom-logicd-core" "$OUT/bin/hidloom-outputd" "$OUT/bin/hidloom-hidd" "$OUT/bin/hidloom-uidd"
