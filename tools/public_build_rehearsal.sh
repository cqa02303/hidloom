#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUT_DIR=${OUT_DIR:-"$ROOT/build/public-rebuild"}
BUILDROOT_OUTPUT=${BUILDROOT_OUTPUT:-"$ROOT/build/artifacts/buildroot-m6-output"}
BUILDROOT_DIR=${BUILDROOT_DIR:-"$ROOT/build/artifacts/buildroot-upstream"}
BUILDROOT_WORK_DIR=$(dirname -- "$BUILDROOT_OUTPUT")
M6_NATIVE_DIR=${HIDLOOM_M6_NATIVE_DIR:-"$BUILDROOT_WORK_DIR/buildroot-m4-native/bin"}
BUILD_HOSTBIN=${HIDLOOM_BUILD_HOSTBIN:-"$BUILDROOT_WORK_DIR/buildroot-hostbin"}
PROVENANCE=${PROVENANCE:-}
PROFILE=${HIDLOOM_DEVICE_PROFILE:-keyboard-ver1}
PACKAGE=0
BUILDROOT_MODE=

usage() {
    cat <<'EOF'
usage: tools/public_build_rehearsal.sh [options]

Rebuild distributable artifacts from a clean public export or public clone.

Options:
  --package              build the ARM64 release bundle, core .deb, and device profile .deb
  --profile ID           package device profile; default keyboard-ver1
  --buildroot-configure  prepare pinned Buildroot source and expand the M6 defconfig
  --buildroot-image      build and verify the complete M6 sdcard image
  --all                  build packages and the complete M6 image
  --out-dir DIR          package output directory; default build/public-rebuild
  --provenance FILE      machine-readable build evidence; default OUT_DIR/PUBLIC_BUILD_PROVENANCE.json
  -h, --help             show this help

At least one build option is required. Long-running compilation runs on the
x86_64 build host; Raspberry Pi hardware is only used for final smoke tests.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --package)
            PACKAGE=1
            shift
            ;;
        --buildroot-configure)
            BUILDROOT_MODE=configure
            shift
            ;;
        --buildroot-image)
            BUILDROOT_MODE=image
            shift
            ;;
        --all)
            PACKAGE=1
            BUILDROOT_MODE=image
            shift
            ;;
        --out-dir)
            OUT_DIR=${2:?missing --out-dir value}
            shift 2
            ;;
        --profile)
            PROFILE=${2:?missing --profile value}
            shift 2
            ;;
        --provenance)
            PROVENANCE=${2:?missing --provenance value}
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

if [ "$PACKAGE" -eq 0 ] && [ -z "$BUILDROOT_MODE" ]; then
    echo "select --package, --buildroot-configure, --buildroot-image, or --all" >&2
    exit 2
fi
if [ -z "$PROVENANCE" ]; then
    PROVENANCE="$OUT_DIR/PUBLIC_BUILD_PROVENANCE.json"
fi
if [ ! -f "$ROOT/PUBLIC_EXPORT_REPORT.json" ]; then
    echo "PUBLIC_EXPORT_REPORT.json is missing; run this from a clean public export or clone" >&2
    exit 1
fi
case "$PROFILE" in
    ''|*[!A-Za-z0-9._-]*)
        echo "invalid profile name: $PROFILE" >&2
        exit 2
        ;;
esac
if [ ! -f "$ROOT/config/device-profiles/$PROFILE.json" ]; then
    echo "device profile not found: $PROFILE" >&2
    exit 1
fi

if [ "$PACKAGE" -eq 1 ]; then
    mkdir -p "$OUT_DIR"
    "$ROOT/tools/package/build_release_bundle.sh" --out-dir "$OUT_DIR"
    BUNDLE=$(ls -t "$OUT_DIR"/hidloom-*-aarch64.tar.zst | sed -n '1p')
    "$ROOT/tools/package/build_deb_package.sh" \
        --bundle "$BUNDLE" --out-dir "$OUT_DIR" --package-id hidloom-core
    "$ROOT/tools/package/build_device_profile_deb.sh" \
        --bundle "$BUNDLE" --out-dir "$OUT_DIR" --profile "$PROFILE"
    (cd "$OUT_DIR" && sha256sum -c ./*.sha256)
    dpkg-deb --info "$OUT_DIR"/hidloom-core_*_arm64.deb >/dev/null
    dpkg-deb --info "$OUT_DIR"/hidloom-profile-"$PROFILE"_*_arm64.deb >/dev/null
fi

case "$BUILDROOT_MODE" in
    configure)
        BUILDROOT_DIR="$BUILDROOT_DIR" BUILDROOT_OUTPUT="$BUILDROOT_OUTPUT" \
            HIDLOOM_M6_NATIVE_DIR="$M6_NATIVE_DIR" HIDLOOM_BUILD_HOSTBIN="$BUILD_HOSTBIN" \
            "$ROOT/tools/buildroot_m6_build.sh" --configure-only
        ;;
    image)
        BUILDROOT_DIR="$BUILDROOT_DIR" BUILDROOT_OUTPUT="$BUILDROOT_OUTPUT" \
            HIDLOOM_M6_NATIVE_DIR="$M6_NATIVE_DIR" HIDLOOM_BUILD_HOSTBIN="$BUILD_HOSTBIN" \
            "$ROOT/tools/buildroot_m6_build.sh"
        ;;
esac

if [ "$PACKAGE" -eq 1 ] && [ "$BUILDROOT_MODE" = image ]; then
    PROVENANCE_MODE=all
elif [ "$PACKAGE" -eq 1 ]; then
    PROVENANCE_MODE=package
elif [ "$BUILDROOT_MODE" = image ]; then
    PROVENANCE_MODE=buildroot-image
else
    PROVENANCE_MODE=buildroot-configure
fi

set -- collect --source "$ROOT" --mode "$PROVENANCE_MODE" --output "$PROVENANCE"
if [ "$PACKAGE" -eq 1 ]; then
    set -- "$@" --package-dir "$OUT_DIR" --profile "$PROFILE"
fi
if [ -n "$BUILDROOT_MODE" ]; then
    set -- "$@" --buildroot-source "$BUILDROOT_DIR" --buildroot-output "$BUILDROOT_OUTPUT"
fi
python3 "$ROOT/tools/public_build_provenance.py" "$@" >/dev/null

set -- verify "$PROVENANCE" --source "$ROOT"
if [ "$PACKAGE" -eq 1 ]; then
    set -- "$@" --package-dir "$OUT_DIR" --profile "$PROFILE"
fi
if [ -n "$BUILDROOT_MODE" ]; then
    set -- "$@" --buildroot-source "$BUILDROOT_DIR" --buildroot-output "$BUILDROOT_OUTPUT"
fi
python3 "$ROOT/tools/public_build_provenance.py" "$@"

echo "ok: public source rebuild rehearsal"
