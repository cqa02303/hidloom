#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)

BUNDLE=
PROFILE_ID=
OUT_DIR=${OUT_DIR:-"$REPO_ROOT/build/packages"}
WORK_ROOT=${WORK_ROOT:-"$REPO_ROOT/build/deb-work"}
CORE_PACKAGE_ID=${HIDLOOM_DEB_CORE_PACKAGE_ID:-hidloom-core}
PACKAGE_ID=
MAINTAINER=${HIDLOOM_DEB_MAINTAINER:-HIDloom maintainers <root@localhost>}
BUILD_BUNDLE=0
ALLOW_DIRTY=0

usage() {
    cat <<'EOF'
usage: tools/package/build_device_profile_deb.sh --profile PROFILE [options]

Build an arm64 Debian package containing one HIDloom device profile.

Options:
  --profile ID              device profile id, for example touch-waveshare-8.8
  --bundle PATH             release bundle; default latest build/packages/*.tar.zst
  --out-dir DIR             output directory; default build/packages
  --work-root DIR           staging directory; default build/deb-work
  --core-package-id NAME    core package dependency; default hidloom-core
  --package-id NAME         profile package name; default hidloom-profile-<profile>
  --build-bundle            build a fresh release bundle first
  --allow-dirty             pass --allow-dirty when --build-bundle is used
  -h, --help                show this help

The package installs profile metadata and immutable profile files under
/usr/share/hidloom/profiles/<profile>. Runtime files under /mnt/p3 are
updated only when hidloom-profile apply is run.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --profile)
            PROFILE_ID=${2:?missing --profile value}
            shift 2
            ;;
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
        --core-package-id)
            CORE_PACKAGE_ID=${2:?missing --core-package-id value}
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
require_cmd python3
require_cmd tar
require_cmd zstd

if [ -z "$PROFILE_ID" ]; then
    echo "--profile is required" >&2
    usage >&2
    exit 2
fi

if [ -z "$PACKAGE_ID" ]; then
    PACKAGE_ID="hidloom-profile-$PROFILE_ID"
fi

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

MANIFEST="$TMP_DIR/build/package-manifest.json"
PROFILE_JSON="$TMP_DIR/config/device-profiles/$PROFILE_ID.json"
if [ ! -f "$MANIFEST" ]; then
    echo "bundle manifest not found: build/package-manifest.json" >&2
    exit 1
fi
if [ ! -f "$PROFILE_JSON" ]; then
    echo "device profile not found: $PROFILE_ID" >&2
    exit 1
fi

metadata=$(
    python3 - "$MANIFEST" <<'PY'
import json
import re
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
sha = str(manifest.get("git_sha") or "unknown")
rev_count = int(manifest.get("git_rev_count") or 0)
version_sha = re.sub(r"[^0-9A-Za-z.+~:-]", ".", sha)
print(f"version=0.0.{rev_count}+git{version_sha}")
print(f"git_sha={sha}")
PY
)
eval "$metadata"

DEB_NAME="${PACKAGE_ID}_${version}_arm64.deb"
DEB_WORK="$WORK_ROOT/$PACKAGE_ID"
DEB_ROOT="$DEB_WORK/root"
PROFILE_DEST="$DEB_ROOT/usr/share/hidloom/profiles/$PROFILE_ID"

rm -rf "$DEB_WORK"
mkdir -p "$DEB_ROOT/DEBIAN" "$PROFILE_DEST" "$OUT_DIR"
chmod 755 "$DEB_ROOT" "$DEB_ROOT/DEBIAN"

python3 - "$TMP_DIR" "$PROFILE_JSON" "$PROFILE_DEST" <<'PY'
import json
import shutil
import sys
from pathlib import Path

root = Path(sys.argv[1])
src_profile = Path(sys.argv[2])
dest = Path(sys.argv[3])
profile = json.loads(src_profile.read_text(encoding="utf-8"))

for group, dirname in (("runtime_files", "runtime"), ("config_files", "config")):
    files = profile.get(group, {})
    if not isinstance(files, dict):
        raise SystemExit(f"{group} must be an object")
    rewritten = {}
    for name, source in files.items():
        src = root / str(source)
        if not src.exists():
            raise SystemExit(f"missing profile source: {src}")
        target = dest / dirname / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        rewritten[name] = f"{dirname}/{name}"
    profile[group] = rewritten

(dest / "profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

find "$DEB_ROOT" -type d -exec chmod 755 {} +
find "$DEB_ROOT" -type f -exec chmod 644 {} +

cat > "$DEB_ROOT/DEBIAN/control" <<EOF
Package: $PACKAGE_ID
Version: $version
Section: misc
Priority: optional
Architecture: arm64
Maintainer: $MAINTAINER
Depends: $CORE_PACKAGE_ID (= $version), python3, systemd
Description: HIDloom device profile for $PROFILE_ID
 Immutable runtime definition files and service policy for the CQA02303v5
 $PROFILE_ID device profile. Apply it with hidloom-profile after installing the
 matching core package.
EOF

cat > "$DEB_ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e

if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload || true
fi

exit 0
EOF

chmod 755 "$DEB_ROOT/DEBIAN/postinst"

DEB_PATH="$OUT_DIR/$DEB_NAME"
fakeroot dpkg-deb --build "$DEB_ROOT" "$DEB_PATH"
(cd "$(dirname "$DEB_PATH")" && sha256sum "$(basename "$DEB_PATH")" > "$(basename "$DEB_PATH").sha256")

echo "created: $DEB_PATH"
cat "$DEB_PATH.sha256"
echo "package source bundle: $BUNDLE"
echo "device profile: $PROFILE_ID"
echo "profile install root: /usr/share/hidloom/profiles/$PROFILE_ID"
