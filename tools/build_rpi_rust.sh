#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

TARGET=${HIDLOOM_RPI_RUST_TARGET:-aarch64-unknown-linux-musl}
BIN_DIR_OVERRIDE=${BIN_DIR:-}
CARGO=${CARGO:-cargo}
RUSTUP=${RUSTUP:-rustup}
HIDLOOM_USE_SCCACHE=${HIDLOOM_USE_SCCACHE:-auto}

usage() {
    cat <<'EOF'
usage: tools/build_rpi_rust.sh [--target TARGET] [--bin-dir DIR] [--no-sccache]

Build Raspberry Pi Rust daemons on a faster x86_64 host.

Default target:
  aarch64-unknown-linux-musl  static ARM64 binary, recommended for Pi deploy

Useful alternative:
  aarch64-unknown-linux-gnu   dynamic ARM64 glibc binary

sccache:
  Uses sccache automatically when it is installed. Set HIDLOOM_USE_SCCACHE=0 or
  pass --no-sccache to disable it for one run.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --target)
            TARGET=${2:?missing --target value}
            shift 2
            ;;
        --bin-dir)
            BIN_DIR_OVERRIDE=${2:?missing --bin-dir value}
            shift 2
            ;;
        --no-sccache)
            HIDLOOM_USE_SCCACHE=0
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

BIN_DIR=${BIN_DIR_OVERRIDE:-"$REPO_ROOT/build/rpi-rust/$TARGET/bin"}
python3 "$REPO_ROOT/tools/generated_binary_hygiene.py" \
    --root "$REPO_ROOT" --extra-bin-dir "$BIN_DIR" --clean

require_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "missing command: $1" >&2
        exit 1
    fi
}

require_cmd "$CARGO"
require_cmd "$RUSTUP"

SCCACHE_ACTIVE=0
case "$HIDLOOM_USE_SCCACHE" in
    0|false|False|FALSE|no|No|NO)
        ;;
    auto|1|true|True|TRUE|yes|Yes|YES)
        if [ -z "${RUSTC_WRAPPER:-}" ] && command -v sccache >/dev/null 2>&1; then
            export RUSTC_WRAPPER=sccache
            SCCACHE_ACTIVE=1
            echo "using RUSTC_WRAPPER=sccache"
        elif [ -n "${RUSTC_WRAPPER:-}" ] && { [ "$RUSTC_WRAPPER" = "sccache" ] || [ "$(basename -- "$RUSTC_WRAPPER")" = "sccache" ]; }; then
            SCCACHE_ACTIVE=1
            echo "using existing RUSTC_WRAPPER=$RUSTC_WRAPPER"
        fi
        ;;
    *)
        echo "unsupported HIDLOOM_USE_SCCACHE value: $HIDLOOM_USE_SCCACHE" >&2
        exit 1
        ;;
esac

case "$TARGET" in
    aarch64-unknown-linux-musl)
        export CARGO_TARGET_AARCH64_UNKNOWN_LINUX_MUSL_LINKER=${CARGO_TARGET_AARCH64_UNKNOWN_LINUX_MUSL_LINKER:-rust-lld}
        ;;
    aarch64-unknown-linux-gnu)
        require_cmd aarch64-linux-gnu-gcc
        export CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER=${CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER:-aarch64-linux-gnu-gcc}
        ;;
    *)
        echo "unsupported target for this repository helper: $TARGET" >&2
        exit 1
        ;;
esac

if ! "$RUSTUP" target list --installed | grep -qx "$TARGET"; then
    echo "rust target is not installed: $TARGET" >&2
    echo "run: rustup target add $TARGET" >&2
    exit 1
fi

mkdir -p "$BIN_DIR"

build_one() {
    crate_dir=$1
    bin_name=$2
    manifest="$REPO_ROOT/$crate_dir/Cargo.toml"
    output="$REPO_ROOT/$crate_dir/target/$TARGET/release/$bin_name"

    echo "== $crate_dir -> $bin_name ($TARGET) =="
    "$CARGO" build --locked --manifest-path "$manifest" --release --target "$TARGET"
    install -m 755 "$output" "$BIN_DIR/$bin_name.tmp"
    mv -f "$BIN_DIR/$bin_name.tmp" "$BIN_DIR/$bin_name"
    file "$BIN_DIR/$bin_name"
}

build_one tools/hidloom_hidd hidloom-hidd
build_one tools/hidloom_uidd hidloom-uidd
build_one tools/hidloom_outputd hidloom-outputd
build_one tools/hidloom_logicd_core hidloom-logicd-core

echo "installed ARM64 Rust binaries: $BIN_DIR"
if [ "$SCCACHE_ACTIVE" -eq 1 ]; then
    sccache --show-stats || true
fi
