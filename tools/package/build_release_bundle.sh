#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)

RUST_TARGET=${HIDLOOM_RPI_RUST_TARGET:-aarch64-unknown-linux-musl}
MATRIX_CC=${MATRIX_CC:-aarch64-linux-gnu-gcc}
HIDLOOM_SEND_CC=${HIDLOOM_SEND_CC:-$MATRIX_CC}
OUT_DIR=${OUT_DIR:-"$REPO_ROOT/build/packages"}
WORK_ROOT=${WORK_ROOT:-"$REPO_ROOT/build/package-work"}
BUILD=1
ALLOW_DIRTY=0

usage() {
    cat <<'EOF'
usage: tools/package/build_release_bundle.sh [options]

Build a Raspberry Pi release bundle on a cross-build host.

Options:
  --rust-target TARGET  Rust target triple; default aarch64-unknown-linux-musl
  --matrix-cc CC        C compiler for matrixd; default aarch64-linux-gnu-gcc
                       Also used for hidloom_send helpers unless HIDLOOM_SEND_CC is set.
  --out-dir DIR         output directory; default build/packages
  --no-build            reuse existing build/rpi-rust and build/rpi-matrixd outputs
  --allow-dirty         allow building while the local worktree has changes
  -h, --help            show this help

When PUBLIC_EXPORT_REPORT.json and PUBLIC_EXPORT_MANIFEST.json are present,
the bundle uses their exact audited file set even inside a public git clone.
Otherwise it is created from git HEAD plus freshly built ARM64 binaries.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --rust-target)
            RUST_TARGET=${2:?missing --rust-target value}
            shift 2
            ;;
        --matrix-cc)
            MATRIX_CC=${2:?missing --matrix-cc value}
            shift 2
            ;;
        --out-dir)
            OUT_DIR=${2:?missing --out-dir value}
            shift 2
            ;;
        --no-build)
            BUILD=0
            shift
            ;;
        --allow-dirty)
            ALLOW_DIRTY=1
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

require_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "missing command: $1" >&2
        exit 1
    fi
}

require_cmd tar
require_cmd zstd
require_cmd file
require_cmd "$MATRIX_CC"
require_cmd "$HIDLOOM_SEND_CC"

SOURCE_MODE=git
REPORT="$REPO_ROOT/PUBLIC_EXPORT_REPORT.json"
EXPORT_MANIFEST="$REPO_ROOT/PUBLIC_EXPORT_MANIFEST.json"
EXPORT_MANIFEST_SHA=
if [ -f "$REPORT" ] || [ -f "$EXPORT_MANIFEST" ]; then
    SOURCE_MODE=public-export
    require_cmd python3
    if [ ! -f "$REPORT" ] || [ ! -f "$EXPORT_MANIFEST" ]; then
        echo "PUBLIC_EXPORT_REPORT.json and PUBLIC_EXPORT_MANIFEST.json must be present together" >&2
        exit 1
    fi
    python3 "$REPO_ROOT/tools/public_export_manifest.py" verify "$REPO_ROOT"
    SOURCE_VALUES=$(python3 - "$REPORT" "$EXPORT_MANIFEST" <<'PY'
import hashlib
import json
import sys

report = json.load(open(sys.argv[1], encoding="utf-8"))
manifest = json.load(open(sys.argv[2], encoding="utf-8"))
report_provenance = report.get("source_provenance")
manifest_provenance = manifest.get("source_provenance")
if report_provenance != manifest_provenance:
    raise SystemExit("public export report/manifest source provenance mismatch")
if not isinstance(report_provenance, dict) or not report_provenance.get("publishable"):
    raise SystemExit("public export source provenance is not publishable")
commit = report_provenance["base_commit"]
print(commit[:12])
print(commit)
print(report_provenance["base_revision_count"])
print(hashlib.sha256(open(sys.argv[2], "rb").read()).hexdigest())
PY
)
    SHA=$(printf '%s\n' "$SOURCE_VALUES" | sed -n '1p')
    DESCRIBE=$(printf '%s\n' "$SOURCE_VALUES" | sed -n '2p')
    REV_COUNT=$(printf '%s\n' "$SOURCE_VALUES" | sed -n '3p')
    EXPORT_MANIFEST_SHA=$(printf '%s\n' "$SOURCE_VALUES" | sed -n '4p')
    DIRTY=
elif git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    SHA=$(git -C "$REPO_ROOT" rev-parse --short HEAD)
    DESCRIBE=$(git -C "$REPO_ROOT" describe --always --dirty --tags)
    REV_COUNT=$(git -C "$REPO_ROOT" rev-list --count HEAD)
    DIRTY=$(git -C "$REPO_ROOT" status --porcelain)
    if [ -n "$DIRTY" ] && [ "$ALLOW_DIRTY" -ne 1 ]; then
        echo "local worktree has changes; commit them or pass --allow-dirty" >&2
        git -C "$REPO_ROOT" status --short >&2
        exit 1
    fi
else
    echo "git metadata and public export provenance are both unavailable" >&2
    exit 1
fi

RUST_BIN_DIR="$REPO_ROOT/build/rpi-rust/$RUST_TARGET/bin"
MATRIX_BIN_DIR="$REPO_ROOT/build/rpi-matrixd/aarch64-static/bin"
USB_GADGET_FAST_BIN_DIR="$REPO_ROOT/build/rpi-usb-gadget-fast/aarch64-static/bin"
HIDLOOM_SEND_BIN_DIR="$REPO_ROOT/build/rpi-hidloom-send/aarch64-static/bin"

if [ "$BUILD" -eq 1 ]; then
    "$REPO_ROOT/tools/build_rpi_rust.sh" --target "$RUST_TARGET" --bin-dir "$RUST_BIN_DIR"
    mkdir -p "$MATRIX_BIN_DIR"
    echo "== daemon/matrixd -> matrixd (aarch64 static) =="
    "$MATRIX_CC" -std=c11 -Wall -Wextra -O2 -D_POSIX_C_SOURCE=200809L -static \
        -o "$MATRIX_BIN_DIR/matrixd" \
        "$REPO_ROOT/daemon/matrixd/matrixd.c" \
        "$REPO_ROOT/daemon/matrixd/debounce.c"
    file "$MATRIX_BIN_DIR/matrixd"
    mkdir -p "$USB_GADGET_FAST_BIN_DIR"
    echo "== tools/hidloom_usb_gadget_fast -> hidloom-usb-gadget-fast (aarch64 static) =="
    "$MATRIX_CC" -std=c11 -Wall -Wextra -O2 -D_POSIX_C_SOURCE=200809L -static \
        -o "$USB_GADGET_FAST_BIN_DIR/hidloom-usb-gadget-fast" \
        "$REPO_ROOT/tools/hidloom_usb_gadget_fast/hidloom_usb_gadget_fast.c"
    file "$USB_GADGET_FAST_BIN_DIR/hidloom-usb-gadget-fast"
    mkdir -p "$HIDLOOM_SEND_BIN_DIR"
    echo "== tools/hidloom_send -> helper commands (aarch64 static) =="
    make -C "$REPO_ROOT/tools/hidloom_send" clean all install \
        BIN_DIR="$HIDLOOM_SEND_BIN_DIR" \
        CC="$HIDLOOM_SEND_CC" \
        CFLAGS="-O2 -Wall -Wextra -std=c11 -static"
    file "$HIDLOOM_SEND_BIN_DIR/hidloom-key" \
        "$HIDLOOM_SEND_BIN_DIR/hidloom-keytext" \
        "$HIDLOOM_SEND_BIN_DIR/hidloom-oled" \
        "$HIDLOOM_SEND_BIN_DIR/hidloom-notify" \
        "$HIDLOOM_SEND_BIN_DIR/hidloom-ctrl"
fi

for bin in hidloom-hidd hidloom-uidd hidloom-outputd hidloom-logicd-core; do
    if [ ! -x "$RUST_BIN_DIR/$bin" ]; then
        echo "missing Rust binary: $RUST_BIN_DIR/$bin" >&2
        exit 1
    fi
done
if [ ! -x "$MATRIX_BIN_DIR/matrixd" ]; then
    echo "missing matrixd binary: $MATRIX_BIN_DIR/matrixd" >&2
    exit 1
fi
if [ ! -x "$USB_GADGET_FAST_BIN_DIR/hidloom-usb-gadget-fast" ]; then
    echo "missing USB gadget fast binary: $USB_GADGET_FAST_BIN_DIR/hidloom-usb-gadget-fast" >&2
    exit 1
fi
for bin in hidloom-key hidloom-keytext hidloom-oled hidloom-notify hidloom-ctrl; do
    if [ ! -x "$HIDLOOM_SEND_BIN_DIR/$bin" ]; then
        echo "missing hidloom_send helper: $HIDLOOM_SEND_BIN_DIR/$bin" >&2
        exit 1
    fi
done

PACKAGE_NAME="hidloom-$SHA-aarch64"
WORK_DIR="$WORK_ROOT/$PACKAGE_NAME"
ROOT_DIR="$WORK_DIR/root"
ARCHIVE="$OUT_DIR/$PACKAGE_NAME.tar.zst"

rm -rf "$WORK_DIR"
mkdir -p "$ROOT_DIR" "$OUT_DIR"
if [ "$SOURCE_MODE" = git ]; then
    git -C "$REPO_ROOT" archive --format=tar HEAD | tar -C "$ROOT_DIR" -xf -
else
    python3 "$REPO_ROOT/tools/public_export_manifest.py" materialize "$REPO_ROOT" "$ROOT_DIR" >/dev/null
fi

mkdir -p "$ROOT_DIR/bin" "$ROOT_DIR/daemon/matrixd" "$ROOT_DIR/build"
install -m 755 "$RUST_BIN_DIR/hidloom-hidd" "$ROOT_DIR/bin/hidloom-hidd"
install -m 755 "$RUST_BIN_DIR/hidloom-uidd" "$ROOT_DIR/bin/hidloom-uidd"
install -m 755 "$RUST_BIN_DIR/hidloom-outputd" "$ROOT_DIR/bin/hidloom-outputd"
install -m 755 "$RUST_BIN_DIR/hidloom-logicd-core" "$ROOT_DIR/bin/hidloom-logicd-core"
install -m 755 "$USB_GADGET_FAST_BIN_DIR/hidloom-usb-gadget-fast" "$ROOT_DIR/bin/hidloom-usb-gadget-fast"
install -m 755 "$HIDLOOM_SEND_BIN_DIR/hidloom-key" "$ROOT_DIR/bin/hidloom-key"
install -m 755 "$HIDLOOM_SEND_BIN_DIR/hidloom-keytext" "$ROOT_DIR/bin/hidloom-keytext"
install -m 755 "$HIDLOOM_SEND_BIN_DIR/hidloom-oled" "$ROOT_DIR/bin/hidloom-oled"
install -m 755 "$HIDLOOM_SEND_BIN_DIR/hidloom-notify" "$ROOT_DIR/bin/hidloom-notify"
install -m 755 "$HIDLOOM_SEND_BIN_DIR/hidloom-ctrl" "$ROOT_DIR/bin/hidloom-ctrl"
install -m 755 "$MATRIX_BIN_DIR/matrixd" "$ROOT_DIR/daemon/matrixd/matrixd"

cat > "$ROOT_DIR/build/package-manifest.json" <<EOF
{
  "schema": "hidloom.release-bundle.v1",
  "package": "$PACKAGE_NAME",
  "git_sha": "$SHA",
  "git_describe": "$DESCRIBE",
  "git_rev_count": $REV_COUNT,
  "rust_target": "$RUST_TARGET",
  "matrix_target": "aarch64-static",
  "dirty_worktree_ignored": $([ -n "$DIRTY" ] && echo true || echo false),
  "source_mode": "$SOURCE_MODE",
  "public_export_manifest_sha256": $([ -n "$EXPORT_MANIFEST_SHA" ] && printf '"%s"' "$EXPORT_MANIFEST_SHA" || printf 'null'),
  "binaries": [
    "bin/hidloom-hidd",
    "bin/hidloom-uidd",
    "bin/hidloom-outputd",
    "bin/hidloom-logicd-core",
    "bin/hidloom-usb-gadget-fast",
    "bin/hidloom-key",
    "bin/hidloom-keytext",
    "bin/hidloom-oled",
    "bin/hidloom-notify",
    "bin/hidloom-ctrl",
    "daemon/matrixd/matrixd"
  ]
}
EOF

tar -C "$ROOT_DIR" --zstd -cf "$ARCHIVE" .
(cd "$(dirname "$ARCHIVE")" && sha256sum "$(basename "$ARCHIVE")" > "$(basename "$ARCHIVE").sha256")

echo "created: $ARCHIVE"
cat "$ARCHIVE.sha256"
