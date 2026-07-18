#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)

BUNDLE=
OUT_DIR=${OUT_DIR:-"$REPO_ROOT/build/packages"}
WORK_ROOT=${WORK_ROOT:-"$REPO_ROOT/build/deb-work"}
APP_ROOT=${HIDLOOM_APP_ROOT:-/usr/lib/hidloom}
UNIT_ROOT=${HIDLOOM_UNIT_ROOT:-/usr/lib/hidloom}
UNIT_DIR=${HIDLOOM_DEB_SYSTEMD_UNIT_DIR:-/lib/systemd/system}
PACKAGE_ID=${HIDLOOM_DEB_PACKAGE_ID:-hidloom}
MAINTAINER=${HIDLOOM_DEB_MAINTAINER:-HIDloom maintainers <root@localhost>}
BUILD_BUNDLE=0
ALLOW_DIRTY=0

usage() {
    cat <<'EOF'
usage: tools/package/build_deb_package.sh [options]

Build an arm64 Debian package from a release bundle.

Options:
  --bundle PATH       release bundle; default latest build/packages/*.tar.zst
  --out-dir DIR      output directory; default build/packages
  --work-root DIR    staging directory; default build/deb-work
  --app-root DIR     package app root; default /usr/lib/hidloom
  --unit-dir DIR     systemd unit directory; default /lib/systemd/system
  --package-id NAME  Debian package name; default hidloom
  --build-bundle     build a fresh release bundle first
  --allow-dirty      pass --allow-dirty when --build-bundle is used
  -h, --help         show this help

Runtime definitions under /mnt/p3 are not included in the package payload.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --bundle)
            BUNDLE=${2:?missing --bundle value}
            shift 2
            ;;
        --out-dir)
            OUT_DIR=${2:?missing --out-dir value}
            shift 2
            ;;
        --work-root)
            WORK_ROOT=${2:?missing --work-root value}
            shift 2
            ;;
        --app-root)
            APP_ROOT=${2:?missing --app-root value}
            UNIT_ROOT=$APP_ROOT
            shift 2
            ;;
        --unit-dir)
            UNIT_DIR=${2:?missing --unit-dir value}
            shift 2
            ;;
        --package-id)
            PACKAGE_ID=${2:?missing --package-id value}
            shift 2
            ;;
        --build-bundle)
            BUILD_BUNDLE=1
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

require_cmd dpkg-deb
require_cmd fakeroot
require_cmd gzip
require_cmd python3
require_cmd rsync
require_cmd tar
require_cmd zstd

if [ "$BUILD_BUNDLE" -eq 1 ]; then
    bundle_args=
    if [ "$ALLOW_DIRTY" -eq 1 ]; then
        bundle_args="--allow-dirty"
    fi
    "$SCRIPT_DIR/build_release_bundle.sh" --out-dir "$OUT_DIR" $bundle_args
fi

if [ -z "$BUNDLE" ]; then
    BUNDLE=$(ls -t "$OUT_DIR"/hidloom-*-aarch64.tar.zst 2>/dev/null | sed -n '1p')
fi

if [ -z "$BUNDLE" ] || [ ! -f "$BUNDLE" ]; then
    echo "release bundle not found; run tools/package/build_release_bundle.sh first" >&2
    exit 1
fi

TMP_DIR=$(mktemp -d)
cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT INT TERM

tar -C "$TMP_DIR" --zstd -xf "$BUNDLE"

for required in script/migrate_runtime_scripts.py config/default/script-migrations.json; do
    if [ ! -f "$TMP_DIR/$required" ]; then
        echo "bundle missing runtime script migration input: $required" >&2
        exit 1
    fi
done

MANIFEST="$TMP_DIR/build/package-manifest.json"
if [ ! -f "$MANIFEST" ]; then
    echo "bundle manifest not found: build/package-manifest.json" >&2
    exit 1
fi

metadata=$(
    python3 - "$MANIFEST" <<'PY'
import json
import re
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
sha = str(manifest.get("git_sha") or "unknown")
package = str(manifest.get("package") or f"hidloom-{sha}-aarch64")
rev_count = int(manifest.get("git_rev_count") or 0)
version_sha = re.sub(r"[^0-9A-Za-z.+~:-]", ".", sha)
print(f"package={package}")
print(f"version=0.0.{rev_count}+git{version_sha}")
print(f"git_sha={sha}")
PY
)
eval "$metadata"

DEB_NAME="${PACKAGE_ID}_${version}_arm64.deb"
DEB_WORK="$WORK_ROOT/$PACKAGE_ID"
DEB_ROOT="$DEB_WORK/root"
APP_REL=${APP_ROOT#/}
UNIT_REL=${UNIT_DIR#/}

rm -rf "$DEB_WORK"
mkdir -p "$DEB_ROOT/DEBIAN" "$DEB_ROOT/$APP_REL" "$DEB_ROOT/$UNIT_REL" "$OUT_DIR"
chmod 755 "$DEB_ROOT" "$DEB_ROOT/DEBIAN"

rsync -a --exclude '.git/' "$TMP_DIR"/ "$DEB_ROOT/$APP_REL"/
find "$DEB_ROOT" -type d -exec chmod 755 {} +
find "$DEB_ROOT" -type f ! -perm /111 -exec chmod 644 {} +
find "$DEB_ROOT" -type f -perm /111 -exec chmod 755 {} +

unit_count=0
for src in "$TMP_DIR/system/systemd"/*.service "$TMP_DIR/system/systemd"/*.timer; do
    [ -e "$src" ] || continue
    unit_count=$((unit_count + 1))
    unit=$(basename "$src")
    sed "s|@HIDLOOM_REPO_ROOT@|$UNIT_ROOT|g" "$src" > "$DEB_ROOT/$UNIT_REL/$unit"
    chmod 644 "$DEB_ROOT/$UNIT_REL/$unit"
done
if [ "$unit_count" -eq 0 ]; then
    echo "bundle missing systemd unit templates under system/systemd" >&2
    exit 1
fi

install -d -m 755 "$DEB_ROOT/var/lib/hidloom"
install -m 644 "$MANIFEST" "$DEB_ROOT/var/lib/hidloom/package-manifest.json"

install -d -m 755 "$DEB_ROOT/usr/bin"
cat > "$DEB_ROOT/usr/bin/hidloom-profile" <<EOF
#!/bin/sh
exec /usr/bin/python3 "$APP_ROOT/script/apply_device_profile.py" "\$@"
EOF
chmod 755 "$DEB_ROOT/usr/bin/hidloom-profile"
for command in hidloom-key hidloom-keytext hidloom-oled hidloom-notify hidloom-ctrl; do
    command_path="$DEB_ROOT/$APP_REL/bin/$command"
    if [ ! -x "$command_path" ]; then
        echo "bundle missing helper command: $APP_ROOT/bin/$command" >&2
        exit 1
    fi
    ln -s "$APP_ROOT/bin/$command" "$DEB_ROOT/usr/bin/$command"
done

MAN_SRC="$TMP_DIR/docs/man"
if [ ! -d "$MAN_SRC" ]; then
    echo "bundle missing docs/man manual page sources" >&2
    exit 1
fi
man_count=0
for src in "$MAN_SRC"/man[158]/*.[158]; do
    [ -e "$src" ] || continue
    section=$(basename "$(dirname "$src")" | sed 's/^man//')
    dest_dir="$DEB_ROOT/usr/share/man/man$section"
    dest="$dest_dir/$(basename "$src").gz"
    expanded="$DEB_WORK/$(basename "$src").expanded"
    install -d -m 755 "$dest_dir"
    sed \
        -e "s|@HIDLOOM_VERSION@|$version|g" \
        -e "s|@HIDLOOM_GIT_SHA@|$git_sha|g" \
        "$src" > "$expanded"
    gzip -9n < "$expanded" > "$dest"
    rm -f "$expanded"
    chmod 644 "$dest"
    man_count=$((man_count + 1))
done
if [ "$man_count" -eq 0 ]; then
    echo "bundle docs/man contains no manual pages" >&2
    exit 1
fi

cat > "$DEB_ROOT/DEBIAN/control" <<EOF
Package: $PACKAGE_ID
Version: $version
Section: misc
Priority: optional
Architecture: arm64
Maintainer: $MAINTAINER
EOF
if [ "$PACKAGE_ID" = "hidloom-core" ]; then
    cat >> "$DEB_ROOT/DEBIAN/control" <<EOF
Replaces: hidloom
Conflicts: hidloom
EOF
fi
cat >> "$DEB_ROOT/DEBIAN/control" <<EOF
Depends: python3, systemd, python3-aiohttp, python3-dbus-next, python3-luma.oled, python3-pil, i2c-tools, openssl, rfkill, socat
Description: HIDloom Raspberry Pi keyboard runtime
 Native keyboard input-path services and companion Python runtime for
 CQA02303v5 Raspberry Pi devices. Mutable runtime definitions remain outside
 the package under /mnt/p3.
EOF

cat > "$DEB_ROOT/DEBIAN/postinst" <<EOF
#!/bin/sh
set -e

HIDLOOM_APP_ROOT="$APP_ROOT"
HIDLOOM_RUNTIME_DIR="\${HIDLOOM_RUNTIME_DIR:-/mnt/p3}"

if [ -d "\$HIDLOOM_APP_ROOT/config/default" ]; then
    install -d -m 0755 "\$HIDLOOM_RUNTIME_DIR" "\$HIDLOOM_RUNTIME_DIR/script"
    /usr/bin/python3 "\$HIDLOOM_APP_ROOT/script/migrate_runtime_scripts.py" \
        --defaults-dir "\$HIDLOOM_APP_ROOT/config/default/script" \
        --manifest "\$HIDLOOM_APP_ROOT/config/default/script-migrations.json" \
        --runtime-dir "\$HIDLOOM_RUNTIME_DIR/script"
fi

if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload || true
    systemctl enable \
        hidloom-hidd.service \
        hidloom-uidd.service \
        hidloom-outputd.service \
        hidloom-logicd-core.service \
        matrixd.service \
        logicd-companion.service \
        httpd.service \
        i2cd.service \
        ledd.service \
        hidloom-usb-gadget.service \
        hidloom-power-shed.service \
        ledd-shutdown.service \
        hidloom-late-services.timer \
        hidloom-network-late.timer >/dev/null 2>&1 || true
fi

exit 0
EOF

cat > "$DEB_ROOT/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e

if [ "$1" = remove ] && command -v systemctl >/dev/null 2>&1; then
    systemctl stop \
        matrixd.service \
        logicd-companion.service \
        hidloom-logicd-core.service \
        hidloom-outputd.service \
        hidloom-uidd.service \
        hidloom-hidd.service \
        httpd.service \
        i2cd.service \
        ledd.service \
        btd.service \
        viald.service >/dev/null 2>&1 || true
fi

exit 0
EOF

cat > "$DEB_ROOT/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e

if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload || true
fi

exit 0
EOF

chmod 755 "$DEB_ROOT/DEBIAN/postinst" "$DEB_ROOT/DEBIAN/prerm" "$DEB_ROOT/DEBIAN/postrm"
find "$DEB_ROOT/DEBIAN" -type f -print | sort > "$DEB_WORK/debian-control-files.txt"
find "$DEB_ROOT" -type d -exec chmod 755 {} +
find "$DEB_ROOT" -type f ! -perm /111 -exec chmod 644 {} +
find "$DEB_ROOT" -type f -perm /111 -exec chmod 755 {} +

DEB_PATH="$OUT_DIR/$DEB_NAME"
fakeroot dpkg-deb --build "$DEB_ROOT" "$DEB_PATH"
(cd "$(dirname "$DEB_PATH")" && sha256sum "$(basename "$DEB_PATH")" > "$(basename "$DEB_PATH").sha256")

echo "created: $DEB_PATH"
cat "$DEB_PATH.sha256"
echo "package source bundle: $BUNDLE"
echo "package app root: $APP_ROOT"
echo "package systemd unit dir: $UNIT_DIR"
echo "runtime mutable data: /mnt/p3 (not packaged)"
