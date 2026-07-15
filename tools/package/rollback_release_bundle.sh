#!/usr/bin/env sh
set -eu

RELEASES_DIR=${HIDLOOM_RELEASES_DIR:-/opt/hidloom/releases}
CURRENT_LINK=${HIDLOOM_CURRENT_LINK:-/opt/hidloom/current}
RELEASE=
PREVIOUS=0
RESTART=0
DRY_RUN=0

usage() {
    cat <<'EOF'
usage: tools/package/rollback_release_bundle.sh [options]

Switch /opt/hidloom/current to an installed release.

Options:
  --previous      select the newest installed release other than current
  --release NAME  select a release name under /opt/hidloom/releases
  --release-dir DIR
                  select a release directory explicitly
  --releases-dir DIR
                  release store; default /opt/hidloom/releases
  --current-link DIR
                  active release symlink; default /opt/hidloom/current
  --restart       restart native input-path services after switching
  --dry-run       inspect target, but do not switch or restart
  -h, --help      show this help
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --previous)
            PREVIOUS=1
            shift
            ;;
        --release)
            RELEASE=${RELEASES_DIR%/}/${2:?missing --release value}
            shift 2
            ;;
        --release-dir)
            RELEASE=${2:?missing --release-dir value}
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
        *)
            echo "unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [ "$PREVIOUS" -eq 1 ] && [ -n "$RELEASE" ]; then
    echo "use either --previous or --release/--release-dir, not both" >&2
    exit 2
fi

if [ "$DRY_RUN" -ne 1 ] && [ "$(id -u)" -ne 0 ]; then
    echo "non-dry-run rollback must run as root because it installs systemd units" >&2
    exit 1
fi

if [ ! -d "$RELEASES_DIR" ]; then
    echo "releases dir not found: $RELEASES_DIR" >&2
    exit 1
fi

CURRENT_TARGET=$(readlink -f "$CURRENT_LINK" 2>/dev/null || true)
ACTIVE_ROOT=$(
    sed -n 's|^ExecStart=\(.*\)/bin/hidloom-hidd.*|\1|p' /etc/systemd/system/hidloom-hidd.service 2>/dev/null |
        sed -n '1p'
)
ACTIVE_RELEASE=
if [ -n "$ACTIVE_ROOT" ]; then
    active_resolved=$(readlink -f "$ACTIVE_ROOT" 2>/dev/null || true)
    case "$active_resolved" in
        "$RELEASES_DIR"/*)
            ACTIVE_RELEASE=$active_resolved
            ;;
    esac
fi
if [ "$PREVIOUS" -eq 1 ]; then
    RELEASE=$(
        find "$RELEASES_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' |
            sort -nr |
            while read -r _ path; do
                resolved=$(readlink -f "$path" 2>/dev/null || true)
                if [ -n "$resolved" ] && [ "$resolved" != "$ACTIVE_RELEASE" ]; then
                    printf '%s\n' "$resolved"
                    break
                fi
            done
    )
fi

if [ -z "$RELEASE" ]; then
    echo "missing release target; use --previous, --release, or --release-dir" >&2
    usage >&2
    exit 2
fi

TARGET_DIR=$(readlink -f "$RELEASE" 2>/dev/null || true)
if [ -z "$TARGET_DIR" ] || [ ! -d "$TARGET_DIR" ]; then
    echo "release dir not found: $RELEASE" >&2
    exit 1
fi

for path in bin/hidloom-hidd bin/hidloom-uidd bin/hidloom-outputd bin/hidloom-logicd-core daemon/matrixd/matrixd; do
    if [ ! -x "$TARGET_DIR/$path" ]; then
        echo "release missing executable path: $path" >&2
        exit 1
    fi
done

for unit in \
    hidloom-hidd.service \
    hidloom-uidd.service \
    hidloom-outputd.service \
    hidloom-logicd-core.service \
    matrixd.service \
    logicd-companion.service
do
    if [ ! -f "$TARGET_DIR/system/systemd/$unit" ]; then
        echo "release missing systemd unit: $unit" >&2
        exit 1
    fi
done

echo "current release link: ${CURRENT_TARGET:-none}"
echo "active unit root: ${ACTIVE_ROOT:-unknown}"
echo "target release: $TARGET_DIR"
if [ -f "$TARGET_DIR/build/package-manifest.json" ]; then
    echo "target manifest:"
    cat "$TARGET_DIR/build/package-manifest.json"
fi

if [ "$DRY_RUN" -eq 1 ]; then
    echo "dry-run: would point $CURRENT_LINK to $TARGET_DIR"
    echo "dry-run: would regenerate native input path systemd units"
    if [ "$RESTART" -eq 1 ]; then
        echo "dry-run: would restart native input path services"
    fi
    exit 0
fi

ln -sfn "$TARGET_DIR" "$CURRENT_LINK"
if [ -f "$TARGET_DIR/build/package-manifest.json" ]; then
    install -d -m 755 /var/lib/hidloom
    install -m 644 "$TARGET_DIR/build/package-manifest.json" /var/lib/hidloom/package-manifest.json
fi

if command -v systemctl >/dev/null 2>&1; then
    for unit in \
        hidloom-hidd.service \
        hidloom-uidd.service \
        hidloom-outputd.service \
        hidloom-logicd-core.service \
        matrixd.service \
        logicd-companion.service
    do
        sed "s|@HIDLOOM_REPO_ROOT@|$CURRENT_LINK|g" "$TARGET_DIR/system/systemd/$unit" > "/etc/systemd/system/$unit"
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
        logicd-companion.service
fi

echo "active release root: $CURRENT_LINK -> $TARGET_DIR"
