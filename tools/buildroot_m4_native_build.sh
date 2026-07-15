#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TARGET=armv7-unknown-linux-musleabihf
OUT=${1:-$ROOT/build/artifacts/buildroot-m4-native}

rustup target add "$TARGET"
mkdir -p "$OUT/bin"

for crate in hidloom_logicd_core hidloom_outputd hidloom_hidd hidloom_uidd; do
    cargo build --locked --manifest-path "$ROOT/tools/$crate/Cargo.toml" --release --target "$TARGET"
done

install -m 0755 "$ROOT/tools/hidloom_logicd_core/target/$TARGET/release/hidloom-logicd-core" "$OUT/bin/"
install -m 0755 "$ROOT/tools/hidloom_outputd/target/$TARGET/release/hidloom-outputd" "$OUT/bin/"
install -m 0755 "$ROOT/tools/hidloom_hidd/target/$TARGET/release/hidloom-hidd" "$OUT/bin/"
install -m 0755 "$ROOT/tools/hidloom_uidd/target/$TARGET/release/hidloom-uidd" "$OUT/bin/"

file "$OUT/bin/hidloom-logicd-core" "$OUT/bin/hidloom-outputd" "$OUT/bin/hidloom-hidd" "$OUT/bin/hidloom-uidd"
