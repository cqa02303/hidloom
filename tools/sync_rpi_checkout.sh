#!/usr/bin/env sh
set -eu

DEVICE=${HIDLOOM_RPI_DEVICE:-}
REMOTE=${HIDLOOM_RPI_REMOTE:-}
REMOTE_REPO=${HIDLOOM_RPI_REMOTE_REPO:-}

usage() {
    cat <<'EOF'
usage: tools/sync_rpi_checkout.sh (--device 01|02 | --host USER@HOST --repo PATH)

Fast-forward a Raspberry Pi checkout to origin/main over SSH.

This refuses to run when the remote checkout has local changes.
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

ssh "$REMOTE" "cd '$REMOTE_REPO' && \
    before=\$(git rev-parse --short HEAD) && \
    test -z \"\$(git status --porcelain)\" && \
    git fetch --prune origin && \
    git checkout main && \
    git pull --ff-only origin main && \
    after=\$(git rev-parse --short HEAD) && \
    printf 'remote checkout: %s -> %s\n' \"\$before\" \"\$after\" && \
    git status -sb"
