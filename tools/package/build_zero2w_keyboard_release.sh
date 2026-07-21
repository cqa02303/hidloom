#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
SOURCE=
PACKAGE_DIR=
BUILDROOT_SOURCE=
BUILDROOT_OUTPUT=
COMPLIANCE_BUNDLE=
PROVENANCE=
TOUCH_PACKAGE_DIR=
TOUCH_PROVENANCE=
GUIDE=
OUTPUT=
VERSION=
HARDWARE_STATUS=pending
DEVICE=keyboard-ver1
USABLE_SECONDS=
TOUCH_HARDWARE_STATUS=pending
TOUCH_DEVICE=touch-waveshare-8.8
TOUCH_READY_SECONDS=
FORCE=0
CHANNEL=internal-rc

usage() {
    cat <<'EOF'
usage: tools/package/build_zero2w_keyboard_release.sh [options]

Assemble the Raspberry Pi Zero 2 W keyboard package set and Buildroot M6
image into one verified release directory. This command never creates tags or
uploads GitHub assets.

Options:
  --source DIR                 clean public source; default repository root
  --package-dir DIR            output from public_build_rehearsal.sh --all
  --buildroot-source DIR       pinned clean Buildroot checkout
  --buildroot-output DIR       verified M6 Buildroot output
  --compliance-bundle FILE     verified Buildroot corresponding-source archive
  --provenance FILE            public all-mode build provenance
  --touch-package-dir DIR      optional matching touch profile package output
  --touch-provenance FILE      optional matching touch package provenance
  --guide FILE                 Zero 2 W package/M6 quickstart inside public source
  --output DIR                 release directory; default build/zero2w-keyboard-release
  --version VERSION            release label; default 0.1.0-dev.<source>
  --channel CHANNEL            internal-rc (default) or stable-public
  --hardware-smoke-status S    aggregate package + exact M6 result; default pending
  --device NAME                hardware smoke device; default keyboard-ver1
  --usable-keyboard-seconds N  positive USB-to-usable timing from the exact M6 image
  --touch-hardware-smoke-status S
                               pending, pass, or fail; default pending
  --touch-device NAME          touch smoke device; default touch-waveshare-8.8
  --touch-ready-seconds N      positive touch-ready measurement for a pass
  --force                      replace a non-empty output directory
  -h, --help                   show this help
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --source)
            SOURCE=${2:?missing --source value}
            shift 2
            ;;
        --package-dir)
            PACKAGE_DIR=${2:?missing --package-dir value}
            shift 2
            ;;
        --buildroot-source)
            BUILDROOT_SOURCE=${2:?missing --buildroot-source value}
            shift 2
            ;;
        --buildroot-output)
            BUILDROOT_OUTPUT=${2:?missing --buildroot-output value}
            shift 2
            ;;
        --compliance-bundle)
            COMPLIANCE_BUNDLE=${2:?missing --compliance-bundle value}
            shift 2
            ;;
        --provenance)
            PROVENANCE=${2:?missing --provenance value}
            shift 2
            ;;
        --touch-package-dir)
            TOUCH_PACKAGE_DIR=${2:?missing --touch-package-dir value}
            shift 2
            ;;
        --touch-provenance)
            TOUCH_PROVENANCE=${2:?missing --touch-provenance value}
            shift 2
            ;;
        --guide)
            GUIDE=${2:?missing --guide value}
            shift 2
            ;;
        --output)
            OUTPUT=${2:?missing --output value}
            shift 2
            ;;
        --version)
            VERSION=${2:?missing --version value}
            shift 2
            ;;
        --channel)
            CHANNEL=${2:?missing --channel value}
            shift 2
            ;;
        --hardware-smoke-status)
            HARDWARE_STATUS=${2:?missing --hardware-smoke-status value}
            shift 2
            ;;
        --device)
            DEVICE=${2:?missing --device value}
            shift 2
            ;;
        --usable-keyboard-seconds)
            USABLE_SECONDS=${2:?missing --usable-keyboard-seconds value}
            shift 2
            ;;
        --touch-hardware-smoke-status)
            TOUCH_HARDWARE_STATUS=${2:?missing --touch-hardware-smoke-status value}
            shift 2
            ;;
        --touch-device)
            TOUCH_DEVICE=${2:?missing --touch-device value}
            shift 2
            ;;
        --touch-ready-seconds)
            TOUCH_READY_SECONDS=${2:?missing --touch-ready-seconds value}
            shift 2
            ;;
        --force)
            FORCE=1
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

SOURCE=${SOURCE:-$ROOT}
PACKAGE_DIR=${PACKAGE_DIR:-$SOURCE/build/public-rebuild}
BUILDROOT_SOURCE=${BUILDROOT_SOURCE:-$SOURCE/build/artifacts/buildroot-upstream}
BUILDROOT_OUTPUT=${BUILDROOT_OUTPUT:-$SOURCE/build/artifacts/buildroot-m6-output}
COMPLIANCE_BUNDLE=${COMPLIANCE_BUNDLE:-$SOURCE/build/artifacts/hidloom-buildroot-m6-compliance.tar.zst}
PROVENANCE=${PROVENANCE:-$PACKAGE_DIR/PUBLIC_BUILD_PROVENANCE.json}
GUIDE=${GUIDE:-$SOURCE/docs/hardware/raspberry-pi-zero-2-w-keyboard-release.md}
OUTPUT=${OUTPUT:-$SOURCE/build/zero2w-keyboard-release}

for required in "$PROVENANCE" "$GUIDE" "$COMPLIANCE_BUNDLE"; do
    if [ ! -f "$required" ]; then
        echo "release input is missing: $required" >&2
        exit 1
    fi
done

PACKAGE_VERSION=$(python3 - "$PROVENANCE" <<'PY'
import json
from pathlib import Path
import sys

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
packages = payload.get("packages") or {}
buildroot = payload.get("buildroot") or {}
if (
    payload.get("schema") != "hidloom.public-build-provenance.v2"
    or not payload.get("ready")
    or payload.get("mode") != "all"
    or packages.get("profile_id") != "keyboard-ver1"
    or not packages.get("version")
    or buildroot.get("mode") != "image"
    or not buildroot.get("ready")
):
    raise SystemExit("public build provenance is not a ready keyboard/M6 all-mode build")
print(packages["version"])
PY
)

CORE_PACKAGE=$PACKAGE_DIR/hidloom-core_${PACKAGE_VERSION}_arm64.deb
PROFILE_PACKAGE=$PACKAGE_DIR/hidloom-profile-keyboard-ver1_${PACKAGE_VERSION}_arm64.deb
for required in "$CORE_PACKAGE" "$PROFILE_PACKAGE" "$BUILDROOT_OUTPUT/images/sdcard.img"; do
    if [ ! -f "$required" ]; then
        echo "release input is missing: $required" >&2
        exit 1
    fi
done

TOUCH_PROFILE_PACKAGE=
if [ -n "$TOUCH_PACKAGE_DIR" ] || [ -n "$TOUCH_PROVENANCE" ]; then
    if [ -z "$TOUCH_PACKAGE_DIR" ] || [ -z "$TOUCH_PROVENANCE" ]; then
        echo "--touch-package-dir and --touch-provenance must be used together" >&2
        exit 2
    fi
    TOUCH_VERSION=$(python3 - "$TOUCH_PROVENANCE" <<'PY'
import json
from pathlib import Path
import sys

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
packages = payload.get("packages") or {}
if (
    payload.get("schema") != "hidloom.public-build-provenance.v2"
    or not payload.get("ready")
    or payload.get("mode") not in {"package", "all"}
    or packages.get("profile_id") != "touch-waveshare-8.8"
    or not packages.get("version")
):
    raise SystemExit("touch public build provenance is not a ready package build")
print(packages["version"])
PY
    )
    if [ "$TOUCH_VERSION" != "$PACKAGE_VERSION" ]; then
        echo "keyboard and touch package versions differ" >&2
        exit 1
    fi
    TOUCH_PROFILE_PACKAGE=$TOUCH_PACKAGE_DIR/hidloom-profile-touch-waveshare-8.8_${TOUCH_VERSION}_arm64.deb
    if [ ! -f "$TOUCH_PROFILE_PACKAGE" ]; then
        echo "release input is missing: $TOUCH_PROFILE_PACKAGE" >&2
        exit 1
    fi
    python3 "$SOURCE/tools/public_build_provenance.py" verify "$TOUCH_PROVENANCE" \
        --source "$SOURCE" \
        --package-dir "$TOUCH_PACKAGE_DIR" \
        --profile touch-waveshare-8.8
fi

python3 "$SOURCE/tools/public_build_provenance.py" verify "$PROVENANCE" \
    --source "$SOURCE" \
    --package-dir "$PACKAGE_DIR" \
    --profile keyboard-ver1 \
    --buildroot-source "$BUILDROOT_SOURCE" \
    --buildroot-output "$BUILDROOT_OUTPUT"

set -- \
    --source "$SOURCE" \
    --buildroot-output "$BUILDROOT_OUTPUT" \
    --core-package "$CORE_PACKAGE" \
    --profile-package "$PROFILE_PACKAGE" \
    --compliance-bundle "$COMPLIANCE_BUNDLE" \
    --build-provenance "$PROVENANCE" \
    --guide "$GUIDE" \
    --output "$OUTPUT" \
    --channel "$CHANNEL" \
    --hardware-smoke-status "$HARDWARE_STATUS" \
    --device "$DEVICE"
if [ -n "$VERSION" ]; then
    set -- "$@" --version "$VERSION"
fi
if [ -n "$USABLE_SECONDS" ]; then
    set -- "$@" --usable-keyboard-seconds "$USABLE_SECONDS"
fi
if [ -n "$TOUCH_PROFILE_PACKAGE" ]; then
    set -- "$@" \
        --touch-profile-package "$TOUCH_PROFILE_PACKAGE" \
        --touch-build-provenance "$TOUCH_PROVENANCE" \
        --touch-hardware-smoke-status "$TOUCH_HARDWARE_STATUS" \
        --touch-device "$TOUCH_DEVICE"
    if [ -n "$TOUCH_READY_SECONDS" ]; then
        set -- "$@" --touch-ready-seconds "$TOUCH_READY_SECONDS"
    fi
fi
if [ "$FORCE" -eq 1 ]; then
    set -- "$@" --force
fi

python3 "$SOURCE/tools/public_release_bundle.py" "$@"
python3 "$SOURCE/tools/public_release_bundle.py" --verify "$OUTPUT"
echo "ok: Raspberry Pi Zero 2 W keyboard/M6 release directory: $OUTPUT"
