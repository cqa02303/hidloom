#!/usr/bin/env sh
set -eu

REPO_DIR=${HIDLOOM_REMOTE_REPO:-/home/pi/hidloom}
MODE=checkout
MODE_SET=0
RELEASES_DIR=${HIDLOOM_RELEASES_DIR:-/opt/hidloom/releases}
CURRENT_LINK=${HIDLOOM_CURRENT_LINK:-/opt/hidloom/current}
APP_ROOT=${HIDLOOM_APP_ROOT:-/usr/lib/hidloom}
UNIT_DIR=${HIDLOOM_SYSTEMD_UNIT_DIR:-/etc/systemd/system}
RESTART=0
DRY_RUN=0
BUNDLE=

usage() {
    cat <<'EOF'
usage: tools/package/apply_release_bundle.sh BUNDLE.tar.zst [options]

Apply a release bundle to a Raspberry Pi.

Options:
  --repo-dir DIR  target checkout; default /home/pi/hidloom
  --opt-release   install to /opt/hidloom/releases and update current symlink
  --deb-layout    install to /usr/lib/hidloom without a release symlink
  --app-root DIR  application root for --deb-layout; default /usr/lib/hidloom
  --unit-dir DIR  systemd unit output dir; default /etc/systemd/system
  --releases-dir DIR
                  release store for --opt-release; default /opt/hidloom/releases
  --current-link DIR
                  symlink used as active root for --opt-release; default /opt/hidloom/current
  --restart       restart package-managed services after applying
  --dry-run       inspect bundle and target, but do not copy or restart
  -h, --help      show this help

Default checkout mode updates the existing checkout path. --opt-release installs
the bundle into a release directory and points systemd units at current.
--deb-layout is a pre-.deb rehearsal mode for the fixed package install root.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --repo-dir)
            REPO_DIR=${2:?missing --repo-dir value}
            shift 2
            ;;
        --opt-release)
            if [ "$MODE_SET" -eq 1 ]; then
                echo "select only one install mode" >&2
                exit 2
            fi
            MODE=opt-release
            MODE_SET=1
            shift
            ;;
        --deb-layout)
            if [ "$MODE_SET" -eq 1 ]; then
                echo "select only one install mode" >&2
                exit 2
            fi
            MODE=deb-layout
            MODE_SET=1
            shift
            ;;
        --app-root)
            APP_ROOT=${2:?missing --app-root value}
            shift 2
            ;;
        --unit-dir)
            UNIT_DIR=${2:?missing --unit-dir value}
            shift 2
            ;;
        --releases-dir)
            RELEASES_DIR=${2:?missing --releases-dir value}
            shift 2
            ;;
        --current-link)
            CURRENT_LINK=${2:?missing --current-link value}
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
        -*)
            echo "unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
        *)
            if [ -n "$BUNDLE" ]; then
                echo "multiple bundle paths supplied" >&2
                exit 2
            fi
            BUNDLE=$1
            shift
            ;;
    esac
done

if [ -z "$BUNDLE" ]; then
    echo "missing bundle path" >&2
    usage >&2
    exit 2
fi

if [ ! -f "$BUNDLE" ]; then
    echo "bundle not found: $BUNDLE" >&2
    exit 1
fi

if [ "$MODE" = checkout ] && [ ! -d "$REPO_DIR" ]; then
    echo "repo dir not found: $REPO_DIR" >&2
    exit 1
fi

if [ "$DRY_RUN" -ne 1 ] && [ "$(id -u)" -ne 0 ]; then
    echo "non-dry-run apply must run as root because it installs systemd units" >&2
    exit 1
fi

require_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "missing command: $1" >&2
        exit 1
    fi
}

require_cmd tar
require_cmd zstd
require_cmd rsync
require_cmd file

TMP_DIR=$(mktemp -d)
cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT INT TERM

tar -C "$TMP_DIR" --zstd -xf "$BUNDLE"

for path in bin/hidloom-hidd bin/hidloom-uidd bin/hidloom-outputd bin/hidloom-logicd-core daemon/matrixd/matrixd build/package-manifest.json; do
    if [ ! -e "$TMP_DIR/$path" ]; then
        echo "bundle missing required path: $path" >&2
        exit 1
    fi
done

PACKAGE_NAME=$(tr ',' '\n' < "$TMP_DIR/build/package-manifest.json" | sed -n 's/^[[:space:]]*"package":[[:space:]]*"\([^"]*\)".*/\1/p' | sed -n '1p')
if [ -z "$PACKAGE_NAME" ]; then
    echo "bundle manifest is missing package name" >&2
    exit 1
fi

echo "bundle manifest:"
cat "$TMP_DIR/build/package-manifest.json"
echo
echo "bundle binary file types:"
file "$TMP_DIR/bin/hidloom-hidd" \
    "$TMP_DIR/bin/hidloom-uidd" \
    "$TMP_DIR/bin/hidloom-outputd" \
    "$TMP_DIR/bin/hidloom-logicd-core" \
    "$TMP_DIR/daemon/matrixd/matrixd"

if [ "$DRY_RUN" -eq 1 ]; then
    if [ "$MODE" = opt-release ]; then
        echo "dry-run: would install bundle to $RELEASES_DIR/$PACKAGE_NAME"
        echo "dry-run: would point $CURRENT_LINK to $RELEASES_DIR/$PACKAGE_NAME"
    elif [ "$MODE" = deb-layout ]; then
        echo "dry-run: would install bundle to $APP_ROOT"
        echo "dry-run: would write native input path systemd units to $UNIT_DIR"
    else
        echo "dry-run: would apply bundle to $REPO_DIR"
    fi
    exit 0
fi

install -d -m 755 /var/lib/hidloom
install -m 644 "$TMP_DIR/build/package-manifest.json" /var/lib/hidloom/package-manifest.json

if [ "$MODE" = opt-release ]; then
    TARGET_DIR="$RELEASES_DIR/$PACKAGE_NAME"
    UNIT_ROOT="$CURRENT_LINK"
    install -d -m 755 "$RELEASES_DIR"
    rm -rf "$TARGET_DIR.tmp"
    mkdir -p "$TARGET_DIR.tmp"
    rsync -a --exclude '.git/' "$TMP_DIR"/ "$TARGET_DIR.tmp"/
    rm -rf "$TARGET_DIR"
    mv "$TARGET_DIR.tmp" "$TARGET_DIR"
    ln -sfn "$TARGET_DIR" "$CURRENT_LINK"
elif [ "$MODE" = deb-layout ]; then
    TARGET_DIR="$APP_ROOT"
    UNIT_ROOT="$APP_ROOT"
    parent_dir=$(dirname "$APP_ROOT")
    install -d -m 755 "$parent_dir"
    rm -rf "$TARGET_DIR.tmp"
    mkdir -p "$TARGET_DIR.tmp"
    rsync -a --exclude '.git/' "$TMP_DIR"/ "$TARGET_DIR.tmp"/
    rm -rf "$TARGET_DIR"
    mv "$TARGET_DIR.tmp" "$TARGET_DIR"
else
    TARGET_DIR="$REPO_DIR"
    UNIT_ROOT="$REPO_DIR"
    owner=$(stat -c '%U:%G' "$REPO_DIR" 2>/dev/null || echo "")
    rsync -a --exclude '.git/' --exclude 'build/package-manifest.json' "$TMP_DIR"/ "$REPO_DIR"/
    if [ -n "$owner" ]; then
        chown -R "$owner" "$REPO_DIR/bin" "$REPO_DIR/daemon/matrixd/matrixd" 2>/dev/null || true
    fi
fi

if command -v systemctl >/dev/null 2>&1; then
    for src in "$TARGET_DIR/system/systemd"/*.service "$TARGET_DIR/system/systemd"/*.timer; do
        if [ -e "$src" ]; then
            unit=$(basename "$src")
            install -d -m 755 "$UNIT_DIR"
            sed "s|@HIDLOOM_REPO_ROOT@|$UNIT_ROOT|g" "$src" > "$UNIT_DIR/$unit"
        fi
    done
    systemctl daemon-reload || true
fi

if [ "$RESTART" -eq 1 ]; then
    systemctl restart \
        hidloom-hidd.service \
        hidloom-uidd.service \
        hidloom-outputd.service \
        hidloom-logicd-core.service \
        matrixd.service \
        logicd-companion.service \
        httpd.service \
        i2cd.service \
        ledd.service \
        btd.service \
        viald.service
fi

echo "applied release bundle to $TARGET_DIR"
if [ "$MODE" = opt-release ]; then
    echo "active release root: $CURRENT_LINK -> $TARGET_DIR"
elif [ "$MODE" = deb-layout ]; then
    echo "fixed package rehearsal root: $TARGET_DIR"
fi
