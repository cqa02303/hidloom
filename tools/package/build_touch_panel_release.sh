#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
SOURCE=${SOURCE:-$ROOT}
PACKAGE_DIR=${PACKAGE_DIR:-$ROOT/build/public-rebuild}
OUTPUT=${OUTPUT:-$ROOT/build/touch-panel-release}
PROFILE=touch-waveshare-8.8
GUIDE=${GUIDE:-$SOURCE/docs/hardware/raspberry-pi-4-touch-panel-package.md}
FORCE=0
CHANNEL=internal-rc

usage() {
    cat <<'EOF'
usage: tools/package/build_touch_panel_release.sh [options]

Assemble the Raspberry Pi 4 touch-panel package set, corresponding source,
checksums, manifest, and GitHub Release notes from a public source build.

Options:
  --source DIR       clean public export or clone; default repository root
  --package-dir DIR  public rebuild package directory; default build/public-rebuild
  --output DIR       release directory; default build/touch-panel-release
  --channel CHANNEL  internal-rc (default) or stable-public
  --force            replace a non-empty release directory
  -h, --help         show this help

This command never creates a tag or GitHub Release. Publication readiness is
recorded in PACKAGE_RELEASE_MANIFEST.json and remains blocked until all guards pass.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --source)
            SOURCE=${2:?missing --source value}
            GUIDE="$SOURCE/docs/hardware/raspberry-pi-4-touch-panel-package.md"
            shift 2
            ;;
        --package-dir)
            PACKAGE_DIR=${2:?missing --package-dir value}
            shift 2
            ;;
        --output)
            OUTPUT=${2:?missing --output value}
            shift 2
            ;;
        --channel)
            CHANNEL=${2:?missing --channel value}
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

if [ ! -f "$PACKAGE_DIR/PUBLIC_BUILD_PROVENANCE.json" ]; then
    echo "public build provenance is missing: $PACKAGE_DIR/PUBLIC_BUILD_PROVENANCE.json" >&2
    echo "run tools/public_build_rehearsal.sh --package --profile $PROFILE first" >&2
    exit 1
fi

set -- $(python3 - "$PACKAGE_DIR/PUBLIC_BUILD_PROVENANCE.json" "$PACKAGE_DIR" "$PROFILE" <<'PY'
import json
from pathlib import Path
import sys

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
directory = Path(sys.argv[2])
profile = sys.argv[3]
packages = report.get("packages") or {}
if packages.get("profile_id") != profile:
    raise SystemExit(f"build provenance profile mismatch: {packages.get('profile_id')} != {profile}")
metadata = packages.get("metadata") or {}
version = (metadata.get("core") or {}).get("version")
if not version:
    raise SystemExit("build provenance package version is missing")
core = directory / f"hidloom-core_{version}_arm64.deb"
device = directory / f"hidloom-profile-{profile}_{version}_arm64.deb"
if not core.is_file() or not device.is_file():
    raise SystemExit("package files recorded by provenance are missing")
print(core)
print(device)
PY
)
CORE=${1:?missing core package}
DEVICE_PROFILE=${2:?missing profile package}

set -- python3 "$SOURCE/tools/package/build_profile_release_bundle.py" build \
    --source "$SOURCE" \
    --core-package "$CORE" \
    --profile-package "$DEVICE_PROFILE" \
    --profile "$PROFILE" \
    --guide "$GUIDE" \
    --build-provenance "$PACKAGE_DIR/PUBLIC_BUILD_PROVENANCE.json" \
    --channel "$CHANNEL" \
    --output "$OUTPUT"
if [ "$FORCE" -eq 1 ]; then
    set -- "$@" --force
fi
"$@"

cat <<EOF

touch-panel release directory ready: $OUTPUT
release page draft: $OUTPUT/RELEASE_NOTES.md
publication state: $OUTPUT/PACKAGE_RELEASE_MANIFEST.json

Final gates:
  python3 $SOURCE/tools/package/build_profile_release_bundle.py verify $OUTPUT --require-channel-ready $CHANNEL
EOF
