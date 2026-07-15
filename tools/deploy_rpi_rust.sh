#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

TARGET=${HIDLOOM_RPI_RUST_TARGET:-aarch64-unknown-linux-musl}
BIN_DIR_OVERRIDE=${BIN_DIR:-}
DEVICE=${HIDLOOM_RPI_DEVICE:-}
REMOTE=${HIDLOOM_RPI_REMOTE:-}
REMOTE_REPO=${HIDLOOM_RPI_REMOTE_REPO:-}
BUILD=1
RESTART=0
SMOKE=0

usage() {
    cat <<'EOF'
usage: tools/deploy_rpi_rust.sh (--device 01|02 | --host USER@HOST --repo PATH) [options]

Build and deploy cross-built Rust daemons to a Raspberry Pi checkout.

Targets:
  --device 01      operator@<keyboard-ip>:/home/USERNAME/hidloom
  --device 02      pi@<keyboard-ip>:/home/pi/hidloom
  --host REMOTE    SSH target, for example pi@<keyboard-ip>
  --repo PATH      repository path on the SSH target

Options:
  --target TARGET  Rust target triple; default aarch64-unknown-linux-musl
  --bin-dir DIR    local binary directory; default build/rpi-rust/$TARGET/bin
  --no-build       deploy an existing local bin directory without rebuilding
  --restart        restart Rust daemon units after rsync
  --smoke          run live hidd and logicd-core smoke checks after restart
  -h, --help       show this help

Environment:
  HIDLOOM_RPI_DEVICE, HIDLOOM_RPI_REMOTE, HIDLOOM_RPI_REMOTE_REPO, HIDLOOM_RPI_RUST_TARGET,
  BIN_DIR
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --device)
            DEVICE=${2:?missing --device value}
            shift 2
            ;;
        --host)
            REMOTE=${2:?missing --host value}
            shift 2
            ;;
        --repo)
            REMOTE_REPO=${2:?missing --repo value}
            shift 2
            ;;
        --target)
            TARGET=${2:?missing --target value}
            shift 2
            ;;
        --bin-dir)
            BIN_DIR_OVERRIDE=${2:?missing --bin-dir value}
            shift 2
            ;;
        --no-build)
            BUILD=0
            shift
            ;;
        --restart)
            RESTART=1
            shift
            ;;
        --smoke)
            SMOKE=1
            RESTART=1
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

case "$DEVICE" in
    01|-01)
        REMOTE=${REMOTE:-operator@<keyboard-ip>}
        REMOTE_REPO=${REMOTE_REPO:-/home/USERNAME/hidloom}
        ;;
    02|-02)
        REMOTE=${REMOTE:-pi@<keyboard-ip>}
        REMOTE_REPO=${REMOTE_REPO:-/home/pi/hidloom}
        ;;
    "")
        ;;
    *)
        echo "unknown device profile: $DEVICE" >&2
        exit 2
        ;;
esac

if [ -z "$REMOTE" ] || [ -z "$REMOTE_REPO" ]; then
    echo "missing remote target; use --device 01|02, or --host and --repo" >&2
    usage >&2
    exit 2
fi

BIN_DIR=${BIN_DIR_OVERRIDE:-"$REPO_ROOT/build/rpi-rust/$TARGET/bin"}
UNITS="hidloom-hidd hidloom-uidd hidloom-outputd hidloom-logicd-core"
BINS="hidloom-hidd hidloom-uidd hidloom-outputd hidloom-logicd-core"

python3 "$REPO_ROOT/tools/generated_binary_hygiene.py" \
    --root "$REPO_ROOT" --extra-bin-dir "$BIN_DIR" --clean

if [ "$BUILD" -eq 1 ]; then
    "$REPO_ROOT/tools/build_rpi_rust.sh" --target "$TARGET" --bin-dir "$BIN_DIR"
fi

for bin in $BINS; do
    if [ ! -x "$BIN_DIR/$bin" ]; then
        echo "missing built binary: $BIN_DIR/$bin" >&2
        exit 1
    fi
done

echo "deploying canonical Rust binaries -> $REMOTE:$REMOTE_REPO/bin/"
ssh "$REMOTE" "mkdir -p '$REMOTE_REPO/bin'"
set --
for bin in $BINS; do
    set -- "$@" "$BIN_DIR/$bin"
done
rsync -az --info=stats1 -- "$@" "$REMOTE:$REMOTE_REPO/bin/"

echo "remote binary file types:"
ssh "$REMOTE" "cd '$REMOTE_REPO' && file bin/hidloom-hidd bin/hidloom-uidd bin/hidloom-outputd bin/hidloom-logicd-core"

if [ "$RESTART" -eq 1 ]; then
    echo "restarting Rust daemon units on $REMOTE"
    ssh "$REMOTE" "sudo systemctl restart $UNITS"
fi

echo "remote daemon active state:"
ssh "$REMOTE" "systemctl is-active $UNITS"

echo "remote status snapshots:"
ssh "$REMOTE" "cat /run/hidloom/hidd-status.json /run/hidloom/outputd-status.json /run/hidloom/uidd-status.json /run/hidloom/logicd-core-status.json 2>/dev/null || true"

if [ "$SMOKE" -eq 1 ]; then
    echo "running remote hidloom-hidd live smoke"
    ssh "$REMOTE" "cd '$REMOTE_REPO' && python3 script/hidloom_hidd_live_smoke.py --delay 0.005 --malformed-count 1 --consumer-null-burst 3"
    echo "running remote logicd-core native owner live smoke"
    ssh "$REMOTE" "cd '$REMOTE_REPO' && python3 tools/logicd_core_native_owner_live_smoke.py --apply --json"
fi

echo "deploy complete: $REMOTE:$REMOTE_REPO ($TARGET)"
