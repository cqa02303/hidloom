#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

DEVICE=${HIDLOOM_RPI_DEVICE:-}
REMOTE=${HIDLOOM_RPI_REMOTE:-}
PREVIOUS=0
RELEASE=
RELEASE_DIR=
RESTART=0
DRY_RUN=0

usage() {
    cat <<'EOF'
usage: tools/package/deploy_release_rollback.sh (--device 01|02 | --host USER@HOST) [options]

Run opt-release rollback on a Raspberry Pi.

Options:
  --previous      select the newest installed release other than current
  --release NAME  select a release name under /opt/hidloom/releases
  --release-dir DIR
                  select a release directory explicitly
  --restart       restart native input-path services after switching
  --dry-run       inspect target, but do not switch or restart
  -h, --help      show this help
EOF
}

quote_arg() {
    printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
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
        --previous)
            PREVIOUS=1
            shift
            ;;
        --release)
            RELEASE=${2:?missing --release value}
            shift 2
            ;;
        --release-dir)
            RELEASE_DIR=${2:?missing --release-dir value}
            shift 2
            ;;
        --restart)
            RESTART=1
            shift
            ;;
        --dry-run)
            DRY_RUN=1
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
        ;;
    02|-02)
        REMOTE=${REMOTE:-pi@<keyboard-ip>}
        ;;
    "")
        ;;
    *)
        echo "unknown device profile: $DEVICE" >&2
        exit 2
        ;;
esac

if [ -z "$REMOTE" ]; then
    echo "missing remote target; use --device 01|02 or --host" >&2
    usage >&2
    exit 2
fi

REMOTE_ROLLBACK="/tmp/hidloom-rollback-release-bundle.sh"
scp "$SCRIPT_DIR/rollback_release_bundle.sh" "$REMOTE:$REMOTE_ROLLBACK"
ssh "$REMOTE" "chmod +x '$REMOTE_ROLLBACK'"

ARGS=
if [ "$PREVIOUS" -eq 1 ]; then
    ARGS="$ARGS --previous"
fi
if [ -n "$RELEASE" ]; then
    ARGS="$ARGS --release $(quote_arg "$RELEASE")"
fi
if [ -n "$RELEASE_DIR" ]; then
    ARGS="$ARGS --release-dir $(quote_arg "$RELEASE_DIR")"
fi
if [ "$RESTART" -eq 1 ]; then
    ARGS="$ARGS --restart"
fi
if [ "$DRY_RUN" -eq 1 ]; then
    ARGS="$ARGS --dry-run"
fi

ssh "$REMOTE" "sudo '$REMOTE_ROLLBACK' $ARGS"
echo "remote release rollback complete: $REMOTE"
