#!/usr/bin/env sh
set -eu

TARGET=${HIDLOOM_RPI_RUST_TARGET:-aarch64-unknown-linux-musl}
DEVICE=${HIDLOOM_RPI_DEVICE:-02}
REMOTE=${HIDLOOM_RPI_REMOTE:-}
REMOTE_REPO=${HIDLOOM_RPI_REMOTE_REPO:-}
CHECK_SSH=1
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

usage() {
    cat <<'EOF'
usage: tools/cross_build_host_check.sh [--target TARGET] [--device 01|02] [--host USER@HOST --repo PATH] [--no-ssh]

Check the cross-build host prerequisites used by the Raspberry Pi Rust
cross-build and deploy workflow.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --target)
            TARGET=${2:?missing --target value}
            shift 2
            ;;
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
        --no-ssh)
            CHECK_SSH=0
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

check_cmd() {
    name=$1
    if command -v "$name" >/dev/null 2>&1; then
        printf 'ok: command %-24s %s\n' "$name" "$(command -v "$name")"
    else
        printf 'missing: command %s\n' "$name"
        return 1
    fi
}

status=0

check_cmd rustup || status=1
check_cmd cargo || status=1
check_cmd rsync || status=1
check_cmd ssh || status=1

if command -v sccache >/dev/null 2>&1; then
    printf 'ok: command %-24s %s\n' sccache "$(command -v sccache)"
    sccache --version || true
else
    echo "warn: sccache is not installed; builds still work, but repeated clean builds may be slower"
fi

if command -v rustup >/dev/null 2>&1; then
    host=$(rustc -Vv 2>/dev/null | awk '/^host:/ {print $2}')
    toolchain=$(rustup show active-toolchain 2>/dev/null | awk '{print $1}')
    if [ -n "$host" ] && [ -n "$toolchain" ]; then
        rust_lld="$HOME/.rustup/toolchains/$toolchain/lib/rustlib/$host/bin/rust-lld"
        if [ -x "$rust_lld" ]; then
            echo "ok: rust-lld $rust_lld"
        else
            echo "missing: rust-lld under active rustup toolchain"
            status=1
        fi
    else
        echo "warn: could not resolve active rustup toolchain host"
    fi
    if rustup target list --installed | grep -qx "$TARGET"; then
        echo "ok: rust target $TARGET is installed"
    else
        echo "missing: rust target $TARGET"
        echo "run: rustup target add $TARGET"
        status=1
    fi
fi

if [ "$TARGET" = "aarch64-unknown-linux-gnu" ]; then
    check_cmd aarch64-linux-gnu-gcc || status=1
fi

if [ "$CHECK_SSH" -eq 1 ]; then
    if [ -z "$REMOTE" ] || [ -z "$REMOTE_REPO" ]; then
        echo "warn: SSH target not configured; use --device 01|02 or --host and --repo"
    else
        echo "checking SSH target: $REMOTE:$REMOTE_REPO"
        local_head=$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || true)
        remote_info=$(ssh -o BatchMode=yes -o ConnectTimeout=5 "$REMOTE" "test -d '$REMOTE_REPO' && hostname && git -C '$REMOTE_REPO' rev-parse --short HEAD && git -C '$REMOTE_REPO' status --porcelain" 2>/dev/null) || remote_info=
        if [ -n "$remote_info" ]; then
            remote_host=$(printf '%s\n' "$remote_info" | sed -n '1p')
            remote_head=$(printf '%s\n' "$remote_info" | sed -n '2p')
            remote_dirty=$(printf '%s\n' "$remote_info" | sed -n '3p')
            echo "$remote_host"
            echo "$remote_head"
            if [ -n "$local_head" ] && [ "$remote_head" != "$local_head" ]; then
                echo "warn: remote checkout differs from local HEAD: remote=$remote_head local=$local_head"
                echo "run: tools/sync_rpi_checkout.sh --device ${DEVICE:-02}"
            fi
            if [ -n "$remote_dirty" ]; then
                echo "warn: remote checkout has local changes"
            fi
            echo "ok: SSH target is reachable"
        else
            echo "missing: SSH target is not ready"
            status=1
        fi
    fi
fi

exit "$status"
