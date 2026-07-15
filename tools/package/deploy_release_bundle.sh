#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)

DEVICE=${HIDLOOM_RPI_DEVICE:-}
REMOTE=${HIDLOOM_RPI_REMOTE:-}
REMOTE_REPO=${HIDLOOM_RPI_REMOTE_REPO:-}
BUNDLE=
BUILD=1
RESTART=0
DRY_RUN=0
OPT_RELEASE=0
DEB_LAYOUT=0

usage() {
    cat <<'EOF'
usage: tools/package/deploy_release_bundle.sh (--device 01|02 | --host USER@HOST --repo PATH) [options]

Build/copy/apply a cross-build host release bundle on a Raspberry Pi.

Options:
  --bundle PATH  use an existing bundle instead of building one
  --no-build     do not build; requires --bundle
  --opt-release  install to /opt/hidloom/releases and update current symlink
  --deb-layout   install to /usr/lib/hidloom fixed package root
  --restart      restart native input-path services after applying
  --dry-run      copy and inspect only; remote apply uses --dry-run
  -h, --help     show this help
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
        --bundle)
            BUNDLE=${2:?missing --bundle value}
            BUILD=0
            shift 2
            ;;
        --no-build)
            BUILD=0
            shift
            ;;
        --opt-release)
            OPT_RELEASE=1
            shift
            ;;
        --deb-layout)
            DEB_LAYOUT=1
            shift
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

if [ "$OPT_RELEASE" -eq 1 ] && [ "$DEB_LAYOUT" -eq 1 ]; then
    echo "use either --opt-release or --deb-layout, not both" >&2
    exit 2
fi

if [ "$BUILD" -eq 1 ]; then
    "$SCRIPT_DIR/build_release_bundle.sh" --allow-dirty
    BUNDLE=$(ls -t "$REPO_ROOT"/build/packages/hidloom-*-aarch64.tar.zst | sed -n '1p')
fi

if [ -z "$BUNDLE" ] || [ ! -f "$BUNDLE" ]; then
    echo "missing bundle; pass --bundle or allow build" >&2
    exit 1
fi

REMOTE_BUNDLE="/tmp/$(basename "$BUNDLE")"
echo "copying $BUNDLE -> $REMOTE:$REMOTE_BUNDLE"
scp "$BUNDLE" "$REMOTE:$REMOTE_BUNDLE"

REMOTE_APPLY="/tmp/hidloom-apply-release-bundle.sh"
scp "$SCRIPT_DIR/apply_release_bundle.sh" "$REMOTE:$REMOTE_APPLY"
ssh "$REMOTE" "chmod +x '$REMOTE_APPLY'"

APPLY_ARGS="--repo-dir '$REMOTE_REPO'"
if [ "$OPT_RELEASE" -eq 1 ]; then
    APPLY_ARGS="$APPLY_ARGS --opt-release"
fi
if [ "$DEB_LAYOUT" -eq 1 ]; then
    APPLY_ARGS="$APPLY_ARGS --deb-layout"
fi
if [ "$RESTART" -eq 1 ]; then
    APPLY_ARGS="$APPLY_ARGS --restart"
fi
if [ "$DRY_RUN" -eq 1 ]; then
    APPLY_ARGS="$APPLY_ARGS --dry-run"
fi

ssh "$REMOTE" "sudo '$REMOTE_APPLY' '$REMOTE_BUNDLE' $APPLY_ARGS"
if [ "$DEB_LAYOUT" -eq 1 ]; then
    echo "remote bundle deploy complete: $REMOTE:/usr/lib/hidloom"
elif [ "$OPT_RELEASE" -eq 1 ]; then
    echo "remote bundle deploy complete: $REMOTE:/opt/hidloom/current"
else
    echo "remote bundle deploy complete: $REMOTE:$REMOTE_REPO"
fi
