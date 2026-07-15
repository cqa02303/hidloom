#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)

DEB=
CORE_DEB=
PROFILE_DEB=
SPLIT_PROFILE=
OUT_DIR=${OUT_DIR:-"$REPO_ROOT/build/packages"}
NOTE_OUT=
SKIP_CLEAN=0
SKIP_VALIDATION=0
SKIP_BUILD=0

usage() {
    cat <<'EOF'
usage: tools/package/release_candidate_check.sh [options]

Check whether a generated .deb is suitable to upload as a GitHub prerelease
candidate. This script does not create tags, upload artifacts, or touch a
Raspberry Pi.

Options:
  --deb PATH          check this .deb; default latest build/packages/*.deb
  --split-profile ID  check core package plus matching device profile package
  --core-deb PATH     split mode: check this core .deb
  --profile-deb PATH  split mode: check this profile .deb
  --out-dir DIR      package output directory; default build/packages
  --note-out PATH    release note draft path; default build/packages/release-note-<version>.md
  --skip-clean       do not require a clean git worktree
  --skip-validation  skip script/test_validation_suite.py
  --skip-build       do not run make deb-package before checking
  -h, --help         show this help
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --deb)
            DEB=${2:?missing --deb value}
            shift 2
            ;;
        --split-profile)
            SPLIT_PROFILE=${2:?missing --split-profile value}
            shift 2
            ;;
        --core-deb)
            CORE_DEB=${2:?missing --core-deb value}
            shift 2
            ;;
        --profile-deb)
            PROFILE_DEB=${2:?missing --profile-deb value}
            shift 2
            ;;
        --out-dir)
            OUT_DIR=${2:?missing --out-dir value}
            shift 2
            ;;
        --note-out)
            NOTE_OUT=${2:?missing --note-out value}
            shift 2
            ;;
        --skip-clean)
            SKIP_CLEAN=1
            shift
            ;;
        --skip-validation)
            SKIP_VALIDATION=1
            shift
            ;;
        --skip-build)
            SKIP_BUILD=1
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
require_cmd git
require_cmd grep
require_cmd mktemp
require_cmd python3
require_cmd readlink
require_cmd sha256sum

if [ "$SKIP_CLEAN" -eq 0 ]; then
    if [ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]; then
        echo "release candidate check requires a clean git worktree" >&2
        echo "commit or stash changes, or use --skip-clean for local inspection only" >&2
        exit 1
    fi
fi

if [ "$SKIP_VALIDATION" -eq 0 ]; then
    python3 "$REPO_ROOT/script/test_validation_suite.py"
fi

if [ "$SKIP_BUILD" -eq 0 ]; then
    if [ -n "$SPLIT_PROFILE" ]; then
        make -C "$REPO_ROOT" core-deb-package
        make -C "$REPO_ROOT" DEVICE_PROFILE="$SPLIT_PROFILE" profile-deb-package
    else
        make -C "$REPO_ROOT" deb-package
    fi
fi

if [ -n "$SPLIT_PROFILE" ]; then
    profile_package="hidloom-profile-$SPLIT_PROFILE"
    if [ -z "$CORE_DEB" ]; then
        CORE_DEB=$(ls -t "$OUT_DIR"/hidloom-core_*_arm64.deb 2>/dev/null | sed -n '1p')
    fi
    if [ -z "$PROFILE_DEB" ]; then
        PROFILE_DEB=$(ls -t "$OUT_DIR"/"$profile_package"_*_arm64.deb 2>/dev/null | sed -n '1p')
    fi
    for path in "$CORE_DEB" "$PROFILE_DEB"; do
        if [ -z "$path" ] || [ ! -f "$path" ]; then
            echo "split package not found; run make core-deb-package and make DEVICE_PROFILE=$SPLIT_PROFILE profile-deb-package" >&2
            exit 1
        fi
        if [ ! -f "$path.sha256" ]; then
            echo "missing sha256 file: $path.sha256" >&2
            exit 1
        fi
        (cd "$(dirname "$path")" && sha256sum -c "$(basename "$path").sha256")
    done

    core_version=$(dpkg-deb -f "$CORE_DEB" Version)
    core_package=$(dpkg-deb -f "$CORE_DEB" Package)
    core_arch=$(dpkg-deb -f "$CORE_DEB" Architecture)
    core_depends=$(dpkg-deb -f "$CORE_DEB" Depends)
    core_replaces=$(dpkg-deb -f "$CORE_DEB" Replaces || true)
    core_conflicts=$(dpkg-deb -f "$CORE_DEB" Conflicts || true)
    profile_version=$(dpkg-deb -f "$PROFILE_DEB" Version)
    profile_name=$(dpkg-deb -f "$PROFILE_DEB" Package)
    profile_arch=$(dpkg-deb -f "$PROFILE_DEB" Architecture)
    profile_depends=$(dpkg-deb -f "$PROFILE_DEB" Depends)

    if [ "$core_package" != "hidloom-core" ]; then
        echo "unexpected core package name: $core_package" >&2
        exit 1
    fi
    if [ "$profile_name" != "$profile_package" ]; then
        echo "unexpected profile package name: $profile_name" >&2
        exit 1
    fi
    if [ "$core_arch" != "arm64" ] || [ "$profile_arch" != "arm64" ]; then
        echo "unexpected split package architecture: core=$core_arch profile=$profile_arch" >&2
        exit 1
    fi
    if [ "$core_version" != "$profile_version" ]; then
        echo "split package versions differ: core=$core_version profile=$profile_version" >&2
        exit 1
    fi
    case "$core_version" in
        0.0.*+git*) ;;
        *)
            echo "unexpected split package version: $core_version" >&2
            exit 1
            ;;
    esac
    for dependency in \
        python3 \
        systemd \
        python3-aiohttp \
        python3-dbus-next \
        python3-luma.oled \
        python3-pil \
        i2c-tools \
        openssl \
        rfkill \
        socat
    do
        if ! printf '%s\n' "$core_depends" | grep -F "$dependency" >/dev/null; then
            echo "core package dependency missing: $dependency" >&2
            exit 1
        fi
    done
    if ! printf '%s\n' "$profile_depends" | grep -F "hidloom-core (= $core_version)" >/dev/null; then
        echo "profile package does not depend on matching core version: $profile_depends" >&2
        exit 1
    fi
    if ! printf '%s\n' "$core_replaces" | grep -F "hidloom" >/dev/null; then
        echo "core package does not replace legacy hidloom: $core_replaces" >&2
        exit 1
    fi
    if ! printf '%s\n' "$core_conflicts" | grep -F "hidloom" >/dev/null; then
        echo "core package does not conflict with legacy hidloom: $core_conflicts" >&2
        exit 1
    fi

    core_contents=$(dpkg-deb --contents "$CORE_DEB")
    profile_contents=$(dpkg-deb --contents "$PROFILE_DEB")
    require_split_content() {
        haystack=$1
        pattern=$2
        label=$3
        if ! printf '%s\n' "$haystack" | grep -E "$pattern" >/dev/null; then
            echo "$label package contents missing: $pattern" >&2
            exit 1
        fi
    }
    require_split_content "$core_contents" '\./usr/lib/hidloom/bin/hidloom-hidd$' core
    require_split_content "$core_contents" '\./usr/lib/hidloom/bin/hidloom-usb-gadget-fast$' core
    require_split_content "$core_contents" '\./usr/lib/hidloom/bin/hidloom-key$' core
    require_split_content "$core_contents" '\./usr/lib/hidloom/daemon/matrixd/matrixd$' core
    require_split_content "$core_contents" '\./lib/systemd/system/hidloom-hidd.service$' core
    require_split_content "$core_contents" '\./lib/systemd/system/httpd.service$' core
    require_split_content "$core_contents" '\./var/lib/hidloom/package-manifest.json$' core
    require_split_content "$profile_contents" "\./usr/share/hidloom/profiles/$SPLIT_PROFILE/profile.json$" profile
    require_split_content "$profile_contents" "\./usr/share/hidloom/profiles/$SPLIT_PROFILE/runtime/keymap.json$" profile
    require_split_content "$profile_contents" "\./usr/share/hidloom/profiles/$SPLIT_PROFILE/runtime/keyboard-layout.json$" profile
    require_split_content "$profile_contents" "\./usr/share/hidloom/profiles/$SPLIT_PROFILE/runtime/vial.json$" profile
    if printf '%s\n%s\n' "$core_contents" "$profile_contents" | grep -E '/home/(pi|operator)/hidloom|/mnt/p3' >/dev/null; then
        echo "split package member path contains runtime or retired checkout path" >&2
        exit 1
    fi

    TMP_DIR=$(mktemp -d)
    cleanup() {
        rm -rf "$TMP_DIR"
    }
    trap cleanup EXIT INT TERM
    dpkg-deb -x "$CORE_DEB" "$TMP_DIR/core"
    dpkg-deb -x "$PROFILE_DEB" "$TMP_DIR/profile"
    MANIFEST="$TMP_DIR/core/var/lib/hidloom/package-manifest.json"
    PROFILE_JSON="$TMP_DIR/profile/usr/share/hidloom/profiles/$SPLIT_PROFILE/profile.json"
    if [ ! -f "$MANIFEST" ] || [ ! -f "$PROFILE_JSON" ]; then
        echo "split package manifest/profile metadata missing" >&2
        exit 1
    fi
    for command in hidloom-key hidloom-keytext hidloom-oled hidloom-notify hidloom-ctrl; do
        command_link="$TMP_DIR/core/usr/bin/$command"
        expected_target="/usr/lib/hidloom/bin/$command"
        if [ ! -L "$command_link" ] || [ "$(readlink "$command_link")" != "$expected_target" ]; then
            echo "split package helper entrypoint invalid: $command_link -> $(readlink "$command_link" 2>/dev/null || true)" >&2
            exit 1
        fi
    done
    split_metadata=$(
        python3 - "$MANIFEST" "$PROFILE_JSON" "$SPLIT_PROFILE" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
profile = json.load(open(sys.argv[2], encoding="utf-8"))
expected_profile = sys.argv[3]
if profile.get("id") != expected_profile:
    raise SystemExit(f"profile id mismatch: {profile.get('id')} != {expected_profile}")
git_sha = str(manifest.get("git_sha") or "unknown")
dirty = str(bool(manifest.get("dirty_worktree_ignored", False))).lower()
print(f"full_git_sha={git_sha}")
print(f"manifest_dirty={dirty}")
print(f"git_sha={git_sha[:7]}")
PY
    )
    eval "$split_metadata"
    if [ "$manifest_dirty" != "false" ]; then
        echo "core package manifest reports dirty_worktree_ignored=$manifest_dirty" >&2
        exit 1
    fi
    case "$core_version" in
        *"+git$git_sha"*) ;;
        *)
            echo "split package version does not match manifest git sha: version=$core_version manifest=$git_sha" >&2
            exit 1
            ;;
    esac
    runtime_path_files=$(find \
        "$TMP_DIR/core/usr/lib/hidloom/config/default/script" \
        "$TMP_DIR/core/usr/lib/hidloom/system/systemd" \
        "$TMP_DIR/core/lib/systemd/system" \
        \( -name 'KC_SH*.sh' -o -name '*.service' -o -name '*.timer' \) \
        -type f 2>/dev/null || true)
    for file in $runtime_path_files; do
        if grep '/home/pi/hidloom\|/home/USERNAME/hidloom' "$file" >/dev/null 2>&1; then
            echo "core package runtime path contains retired checkout path: $file" >&2
            exit 1
        fi
    done

    if [ -z "$NOTE_OUT" ]; then
        NOTE_OUT="$OUT_DIR/release-note-v$core_version-$SPLIT_PROFILE.md"
    fi
    mkdir -p "$(dirname "$NOTE_OUT")"
    core_sha256_line=$(cat "$CORE_DEB.sha256")
    profile_sha256_line=$(cat "$PROFILE_DEB.sha256")
    cat > "$NOTE_OUT" <<EOF
# v$core_version ($SPLIT_PROFILE)

## Artifacts

- core package: $(basename "$CORE_DEB")
- profile package: $(basename "$PROFILE_DEB")
- version: $core_version
- git sha: $full_git_sha
- core sha256: $core_sha256_line
- profile sha256: $profile_sha256_line

## Local Candidate Gate

- git worktree: clean
- validation suite: passed
- core/profile package build: passed
- dpkg metadata: passed
- dpkg contents: passed
- sha256: passed
- exact version dependency: passed
- runtime path check: passed

## Real Device Verification

- profile: $SPLIT_PROFILE
- install: not tested
- smoke: not tested
- failed units: not tested

## Known Risk

- This is a prerelease candidate until real-device install and verify results are added.
EOF

    echo "split release candidate ok"
    echo "core_package: $CORE_DEB"
    echo "profile_package: $PROFILE_DEB"
    echo "version: $core_version"
    echo "git_sha: $git_sha"
    echo "core_sha256: $core_sha256_line"
    echo "profile_sha256: $profile_sha256_line"
    echo "release_note_draft: $NOTE_OUT"
    exit 0
fi

if [ -z "$DEB" ]; then
    DEB=$(ls -t "$OUT_DIR"/hidloom_*_arm64.deb 2>/dev/null | sed -n '1p')
fi

if [ -z "$DEB" ] || [ ! -f "$DEB" ]; then
    echo "package not found; run make deb-package first or pass --deb PATH" >&2
    exit 1
fi

SHA_FILE="$DEB.sha256"
if [ ! -f "$SHA_FILE" ]; then
    echo "missing sha256 file: $SHA_FILE" >&2
    exit 1
fi

version=$(dpkg-deb -f "$DEB" Version)
package=$(dpkg-deb -f "$DEB" Package)
arch=$(dpkg-deb -f "$DEB" Architecture)
depends=$(dpkg-deb -f "$DEB" Depends)

if [ "$package" != "hidloom" ]; then
    echo "unexpected package name: $package" >&2
    exit 1
fi
if [ "$arch" != "arm64" ]; then
    echo "unexpected package architecture: $arch" >&2
    exit 1
fi
case "$version" in
    0.0.*+git*) ;;
    *)
        echo "unexpected package version: $version" >&2
        exit 1
        ;;
esac

for dependency in \
    python3 \
    systemd \
    python3-aiohttp \
    python3-dbus-next \
    python3-luma.oled \
    python3-pil \
    i2c-tools \
    openssl \
    rfkill \
    socat
do
    if ! printf '%s\n' "$depends" | grep -F "$dependency" >/dev/null; then
        echo "package dependency missing: $dependency" >&2
        exit 1
    fi
done

(cd "$(dirname "$DEB")" && sha256sum -c "$(basename "$SHA_FILE")")

contents=$(dpkg-deb --contents "$DEB")
require_content() {
    pattern=$1
    if ! printf '%s\n' "$contents" | grep -E "$pattern" >/dev/null; then
        echo "package contents missing: $pattern" >&2
        exit 1
    fi
}

require_content '\./usr/lib/hidloom/bin/hidloom-hidd$'
require_content '\./usr/lib/hidloom/bin/hidloom-uidd$'
require_content '\./usr/lib/hidloom/bin/hidloom-outputd$'
require_content '\./usr/lib/hidloom/bin/hidloom-logicd-core$'
require_content '\./usr/lib/hidloom/bin/hidloom-usb-gadget-fast$'
require_content '\./usr/lib/hidloom/bin/hidloom-key$'
require_content '\./usr/lib/hidloom/bin/hidloom-keytext$'
require_content '\./usr/lib/hidloom/bin/hidloom-oled$'
require_content '\./usr/lib/hidloom/bin/hidloom-notify$'
require_content '\./usr/lib/hidloom/bin/hidloom-ctrl$'
require_content '\./usr/lib/hidloom/daemon/matrixd/matrixd$'
require_content '\./lib/systemd/system/hidloom-hidd.service$'
require_content '\./lib/systemd/system/hidloom-logicd-core.service$'
require_content '\./lib/systemd/system/matrixd.service$'
require_content '\./lib/systemd/system/httpd.service$'
require_content '\./var/lib/hidloom/package-manifest.json$'
require_content '\./usr/share/man/man1/hidloom-key\.1\.gz$'
require_content '\./usr/share/man/man1/hidloom-ctrl\.1\.gz$'
require_content '\./usr/share/man/man5/hidloom-keymap\.5\.gz$'
require_content '\./usr/share/man/man8/logicd\.8\.gz$'
require_content '\./usr/share/man/man8/matrixd\.8\.gz$'
require_content '\./usr/share/man/man8/hidloom-logicd-core\.8\.gz$'

if printf '%s\n' "$contents" | grep -E '/home/(pi|operator)/hidloom' >/dev/null; then
    echo "package member path contains retired checkout path" >&2
    exit 1
fi

TMP_DIR=$(mktemp -d)
cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT INT TERM

dpkg-deb -x "$DEB" "$TMP_DIR"
MANIFEST="$TMP_DIR/var/lib/hidloom/package-manifest.json"
if [ ! -f "$MANIFEST" ]; then
    echo "package manifest missing: /var/lib/hidloom/package-manifest.json" >&2
    exit 1
fi
manifest_metadata=$(
    python3 - "$MANIFEST" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
git_sha = str(manifest.get("git_sha") or "unknown")
dirty = str(bool(manifest.get("dirty_worktree_ignored", False))).lower()
print(f"full_git_sha={git_sha}")
print(f"manifest_dirty={dirty}")
print(f"git_sha={git_sha[:7]}")
PY
)
eval "$manifest_metadata"
if [ "$manifest_dirty" != "false" ]; then
    echo "package manifest reports dirty_worktree_ignored=$manifest_dirty" >&2
    exit 1
fi
case "$version" in
    *"+git$git_sha"*) ;;
    *)
        echo "package version does not match manifest git sha: version=$version manifest=$git_sha" >&2
        exit 1
        ;;
esac
runtime_path_files=$(find \
    "$TMP_DIR/usr/lib/hidloom/config/default/script" \
    "$TMP_DIR/usr/lib/hidloom/system/systemd" \
    "$TMP_DIR/lib/systemd/system" \
    \( -name 'KC_SH*.sh' -o -name '*.service' -o -name '*.timer' \) \
    -type f 2>/dev/null || true)
for file in $runtime_path_files; do
    if grep '/home/pi/hidloom\|/home/USERNAME/hidloom' "$file" >/dev/null 2>&1; then
        echo "package runtime path contains retired checkout path: $file" >&2
        exit 1
    fi
done

if [ -z "$NOTE_OUT" ]; then
    NOTE_OUT="$OUT_DIR/release-note-v$version.md"
fi
mkdir -p "$(dirname "$NOTE_OUT")"
sha256_line=$(cat "$SHA_FILE")
cat > "$NOTE_OUT" <<EOF
# v$version

## Artifact

- package: $(basename "$DEB")
- version: $version
- git sha: $full_git_sha
- sha256: $sha256_line

## Local Candidate Gate

- git worktree: clean
- validation suite: passed
- deb package build: passed
- dpkg metadata: passed
- dpkg contents: passed
- sha256: passed
- retired checkout path check: passed

## Real Device Verification

- <keyboard-host> install: not tested
- <keyboard-host> smoke: not tested
- <keyboard-host> install: not tested
- <keyboard-host> smoke: not tested
- failed units: not tested

## Known Risk

- This is a prerelease candidate until real-device install and verify results are added.

## Rollback

- Use the previous Debian package or the documented systemd backup under /var/backups/hidloom/systemd-pre-deb/.
EOF

echo "release candidate ok"
echo "package: $DEB"
echo "version: $version"
echo "git_sha: $git_sha"
echo "sha256: $sha256_line"
echo "release_note_draft: $NOTE_OUT"
