#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
PAYLOAD_ROOT=
OUT_DIR=${OUT_DIR:-"$REPO_ROOT/build/packages"}
WORK_ROOT=${WORK_ROOT:-"$REPO_ROOT/build/deb-work"}
VERSION=
PROFILE_PACKAGE=hidloom-profile-keyboard-ver1
PACKAGE_ID=hidloom-early-boot
MAINTAINER=${HIDLOOM_DEB_MAINTAINER:-HIDloom maintainers <root@localhost>}

usage() {
    cat <<'EOF'
usage: tools/package/build_early_boot_deb.sh --payload-root DIR --version VERSION [options]

Build the pinned arm64 hidloom-early-boot control package. PAYLOAD_ROOT must
contain receipt.json, boot/, and accepted/ from a reviewed E5 candidate.

Options:
  --payload-root DIR
  --version VERSION
  --out-dir DIR
  --work-root DIR
  --profile-package NAME
  --package-id NAME
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --payload-root) PAYLOAD_ROOT=${2:?}; shift 2 ;;
        --version) VERSION=${2:?}; shift 2 ;;
        --out-dir) OUT_DIR=${2:?}; shift 2 ;;
        --work-root) WORK_ROOT=${2:?}; shift 2 ;;
        --profile-package) PROFILE_PACKAGE=${2:?}; shift 2 ;;
        --package-id) PACKAGE_ID=${2:?}; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

[ -n "$PAYLOAD_ROOT" ] || { echo "--payload-root is required" >&2; exit 2; }
[ -n "$VERSION" ] || { echo "--version is required" >&2; exit 2; }
for command in dpkg-deb fakeroot python3; do
    command -v "$command" >/dev/null 2>&1 || { echo "missing command: $command" >&2; exit 1; }
done
for required in receipt.json boot/tryboot.txt accepted/early-image.accepted.json; do
    [ -f "$PAYLOAD_ROOT/$required" ] || { echo "payload missing: $required" >&2; exit 1; }
done

DEB_WORK="$WORK_ROOT/$PACKAGE_ID"
DEB_ROOT="$DEB_WORK/root"
ARTIFACT="$DEB_ROOT/usr/lib/hidloom-early-boot/artifact"
rm -rf "$DEB_WORK"
mkdir -p "$DEB_ROOT/DEBIAN" "$ARTIFACT/boot" "$ARTIFACT/accepted" \
    "$DEB_ROOT/usr/lib/hidloom-early-boot" "$DEB_ROOT/usr/bin" \
    "$DEB_ROOT/etc/kernel/postinst.d" "$OUT_DIR"

cp "$PAYLOAD_ROOT/receipt.json" "$ARTIFACT/receipt.json"
cp "$PAYLOAD_ROOT"/boot/* "$ARTIFACT/boot/"
cp "$PAYLOAD_ROOT/accepted/early-image.accepted.json" "$ARTIFACT/accepted/"
python3 "$REPO_ROOT/tools/rpi_os_early_boot_control.py" build \
    --payload-root "$ARTIFACT" --output "$ARTIFACT/manifest.json"
cp "$REPO_ROOT/tools/rpi_os_early_boot_control.py" \
    "$DEB_ROOT/usr/lib/hidloom-early-boot/rpi_os_early_boot_control.py"

cat > "$DEB_ROOT/usr/bin/hidloom-early-boot" <<'EOF'
#!/bin/sh
exec /usr/bin/python3 /usr/lib/hidloom-early-boot/rpi_os_early_boot_control.py "$@"
EOF

cat > "$DEB_ROOT/etc/kernel/postinst.d/hidloom-early-boot" <<'EOF'
#!/bin/sh
set -eu
[ -x /usr/bin/hidloom-early-boot ] || exit 0
exec /usr/bin/hidloom-early-boot kernel-guard --new-release "${1:?missing kernel release}"
EOF

cat > "$DEB_ROOT/DEBIAN/control" <<EOF
Package: $PACKAGE_ID
Version: $VERSION
Section: admin
Priority: optional
Architecture: arm64
Maintainer: $MAINTAINER
Depends: python3, systemd, hidloom-core (= $VERSION), $PROFILE_PACKAGE (= $VERSION)
Description: HIDloom pinned Raspberry Pi early-boot controller
 Installs a reviewed kernel/initramfs artifact in disabled package storage.
 Boot activation, disable, and rollback require explicit operator commands.
EOF

cat > "$DEB_ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
install -d -m 0700 /var/lib/hidloom/early-boot-control
# Deliberately do not copy to /boot or change config.txt here.
/usr/bin/hidloom-early-boot verify >/dev/null
EOF

cat > "$DEB_ROOT/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
if [ "${1:-}" = remove ] || [ "${1:-}" = deconfigure ]; then
    mode=$(/usr/bin/hidloom-early-boot status | /usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin)["mode"])')
    if [ "$mode" = enabled ]; then
        echo "refusing removal while HIDloom early boot is enabled; run hidloom-early-boot rollback" >&2
        exit 1
    fi
fi
EOF

find "$DEB_ROOT" -type d -exec chmod 755 {} +
chmod 700 "$DEB_ROOT/DEBIAN"
find "$DEB_ROOT" -type f -exec chmod 644 {} +
chmod 755 "$DEB_ROOT/usr/bin/hidloom-early-boot" \
    "$DEB_ROOT/usr/lib/hidloom-early-boot/rpi_os_early_boot_control.py" \
    "$DEB_ROOT/etc/kernel/postinst.d/hidloom-early-boot" \
    "$DEB_ROOT/DEBIAN/postinst" "$DEB_ROOT/DEBIAN/prerm"
chmod 755 "$DEB_ROOT/DEBIAN"

DEB="$OUT_DIR/${PACKAGE_ID}_${VERSION}_arm64.deb"
fakeroot dpkg-deb --build "$DEB_ROOT" "$DEB"
dpkg-deb --info "$DEB" >/dev/null
dpkg-deb --contents "$DEB" >/dev/null
sha256sum "$DEB"
printf '%s\n' "$DEB"
