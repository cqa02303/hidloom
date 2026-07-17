#!/usr/bin/env sh
set -eu

TAG=
REPOSITORY=${HIDLOOM_RELEASE_REPOSITORY:-cqa02303/hidloom}
PROFILE=${HIDLOOM_RELEASE_PROFILE:-keyboard-ver1}
DOWNLOAD_DIR=
REMOTE=
DRY_RUN=0
INSTALL=0
APT=0
KEEP=0

usage() {
    cat <<'EOF'
usage: tools/package/install_github_release_deb.sh --tag TAG [options]

Download the HIDloom Raspberry Pi OS package set from a GitHub Release, verify
SHA256SUMS and split-package metadata, and optionally install both packages on
a Raspberry Pi in one transaction.

Options:
  --tag TAG              GitHub Release tag to download
  --repository OWNER/REPO
                         release repository; default cqa02303/hidloom
  --profile PROFILE      device profile; default keyboard-ver1
  --dir DIR              download directory; default temporary directory
  --device 01|02         target from HIDLOOM_RPI_01 or HIDLOOM_RPI_02
  --host USER@HOST       target explicit remote host for remote install
  --dry-run              run remote install simulation/check
  --install              install both packages and apply the profile
  --apt                  use apt-get for dependency-aware dry-run/install
  --keep                 keep the temporary download directory
  -h, --help             show this help

Without --dry-run or --install this script only downloads and verifies assets.
Legacy releases containing exactly one .deb and one .deb.sha256 remain readable.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --tag)
            TAG=${2:?missing --tag value}
            shift 2
            ;;
        --repository)
            REPOSITORY=${2:?missing --repository value}
            shift 2
            ;;
        --profile)
            PROFILE=${2:?missing --profile value}
            shift 2
            ;;
        --dir)
            DOWNLOAD_DIR=${2:?missing --dir value}
            shift 2
            ;;
        --device)
            case "${2:?missing --device value}" in
                01) REMOTE=${HIDLOOM_RPI_01:-} ;;
                02) REMOTE=${HIDLOOM_RPI_02:-} ;;
                *)
                    echo "unknown device: $2" >&2
                    exit 2
                    ;;
            esac
            if [ -z "$REMOTE" ]; then
                echo "--device $2 requires HIDLOOM_RPI_$2; use --host USER@HOST instead" >&2
                exit 2
            fi
            shift 2
            ;;
        --host)
            REMOTE=${2:?missing --host value}
            shift 2
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --install)
            INSTALL=1
            shift
            ;;
        --apt)
            APT=1
            shift
            ;;
        --keep)
            KEEP=1
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
require_cmd gh
require_cmd grep
require_cmd mktemp
require_cmd sed
require_cmd sha256sum

if [ -z "$TAG" ]; then
    echo "missing --tag TAG" >&2
    usage >&2
    exit 2
fi
case "$REPOSITORY" in
    */*) ;;
    *)
        echo "repository must use OWNER/REPO form: $REPOSITORY" >&2
        exit 2
        ;;
esac
case "$PROFILE" in
    ''|*[!A-Za-z0-9._-]*)
        echo "invalid profile name: $PROFILE" >&2
        exit 2
        ;;
esac

if [ "$DRY_RUN" -eq 1 ] || [ "$INSTALL" -eq 1 ]; then
    if [ -z "$REMOTE" ]; then
        echo "remote install requires --device or --host" >&2
        exit 2
    fi
    require_cmd scp
    require_cmd ssh
fi
if [ "$DRY_RUN" -eq 1 ] && [ "$INSTALL" -eq 1 ]; then
    echo "select only one of --dry-run or --install" >&2
    exit 2
fi

if [ -z "$DOWNLOAD_DIR" ]; then
    DOWNLOAD_DIR=$(mktemp -d)
    CREATED_TMP=1
else
    mkdir -p "$DOWNLOAD_DIR"
    CREATED_TMP=0
fi

cleanup() {
    if [ "${CREATED_TMP:-0}" -eq 1 ] && [ "$KEEP" -eq 0 ]; then
        rm -rf "$DOWNLOAD_DIR"
    fi
}
trap cleanup EXIT INT TERM

ASSET_LIST=$(gh release view "$TAG" --repo "$REPOSITORY" --json assets --jq '.assets[].name')

CORE_ASSET=
CORE_COUNT=0
PROFILE_ASSET=
PROFILE_COUNT=0
CHECKSUM_ASSET=
CHECKSUM_COUNT=0
LEGACY_DEB_ASSET=
DEB_COUNT=0
LEGACY_SHA_ASSET=
LEGACY_SHA_COUNT=0

while IFS= read -r asset_name || [ -n "$asset_name" ]; do
    case "$asset_name" in
        hidloom-core_*_arm64.deb)
            CORE_ASSET=$asset_name
            CORE_COUNT=$((CORE_COUNT + 1))
            ;;
    esac
    case "$asset_name" in
        "hidloom-profile-${PROFILE}_"*_arm64.deb)
            PROFILE_ASSET=$asset_name
            PROFILE_COUNT=$((PROFILE_COUNT + 1))
            ;;
    esac
    case "$asset_name" in
        SHA256SUMS)
            CHECKSUM_ASSET=$asset_name
            CHECKSUM_COUNT=$((CHECKSUM_COUNT + 1))
            ;;
        *.deb.sha256)
            LEGACY_SHA_ASSET=$asset_name
            LEGACY_SHA_COUNT=$((LEGACY_SHA_COUNT + 1))
            ;;
        *.deb)
            LEGACY_DEB_ASSET=$asset_name
            DEB_COUNT=$((DEB_COUNT + 1))
            ;;
    esac
done <<EOF
$ASSET_LIST
EOF

if [ "$CORE_COUNT" -gt 0 ] || [ "$PROFILE_COUNT" -gt 0 ]; then
    MODE=split
    if [ "$CORE_COUNT" -ne 1 ]; then
        echo "expected exactly one hidloom-core arm64 asset, found $CORE_COUNT" >&2
        exit 1
    fi
    if [ "$PROFILE_COUNT" -ne 1 ]; then
        echo "expected exactly one hidloom-profile-$PROFILE arm64 asset, found $PROFILE_COUNT" >&2
        exit 1
    fi
    if [ "$CHECKSUM_COUNT" -ne 1 ]; then
        echo "split package release requires exactly one SHA256SUMS asset" >&2
        exit 1
    fi
else
    MODE=legacy
    if [ "$DEB_COUNT" -ne 1 ] || [ "$LEGACY_SHA_COUNT" -ne 1 ]; then
        echo "release has neither a complete split package set nor one legacy .deb/.deb.sha256 pair" >&2
        exit 1
    fi
    if [ "$LEGACY_SHA_ASSET" != "$LEGACY_DEB_ASSET.sha256" ]; then
        echo "legacy checksum asset does not match package: $LEGACY_SHA_ASSET" >&2
        exit 1
    fi
fi

validate_asset_name() {
    if ! printf '%s\n' "$1" | grep -Eq '^[A-Za-z0-9._+~-]+$'; then
        echo "unsafe release asset name: $1" >&2
        exit 1
    fi
}

download_asset() {
    asset_name=$1
    validate_asset_name "$asset_name"
    if [ -e "$DOWNLOAD_DIR/$asset_name" ]; then
        echo "refusing to overwrite existing download: $DOWNLOAD_DIR/$asset_name" >&2
        exit 1
    fi
    gh release download "$TAG" --repo "$REPOSITORY" --dir "$DOWNLOAD_DIR" --pattern "$asset_name"
    if [ ! -f "$DOWNLOAD_DIR/$asset_name" ]; then
        echo "release download did not create expected asset: $asset_name" >&2
        exit 1
    fi
}

if [ "$MODE" = split ]; then
    download_asset "$CORE_ASSET"
    download_asset "$PROFILE_ASSET"
    download_asset "$CHECKSUM_ASSET"
    CORE_PACKAGE="$DOWNLOAD_DIR/$CORE_ASSET"
    PROFILE_PACKAGE="$DOWNLOAD_DIR/$PROFILE_ASSET"
    SHA_FILE="$DOWNLOAD_DIR/$CHECKSUM_ASSET"
else
    download_asset "$LEGACY_DEB_ASSET"
    download_asset "$LEGACY_SHA_ASSET"
    LEGACY_PACKAGE="$DOWNLOAD_DIR/$LEGACY_DEB_ASSET"
    SHA_FILE="$DOWNLOAD_DIR/$LEGACY_SHA_ASSET"
fi

if grep -E '(^|[[:space:]])/' "$SHA_FILE" >/dev/null; then
    echo "sha256 file is not portable; it contains an absolute path: $SHA_FILE" >&2
    exit 1
fi

verify_checksum_entry() {
    asset_name=$1
    checksum_line=$(grep -F "  $asset_name" "$SHA_FILE" || true)
    set -- $checksum_line
    if [ "$#" -ne 2 ] || [ "$2" != "$asset_name" ]; then
        echo "checksum file does not contain one exact entry for: $asset_name" >&2
        exit 1
    fi
    expected=$1
    case "$expected" in
        *[!0-9A-Fa-f]*|'')
            echo "invalid checksum for: $asset_name" >&2
            exit 1
            ;;
    esac
    if [ "${#expected}" -ne 64 ]; then
        echo "invalid checksum length for: $asset_name" >&2
        exit 1
    fi
    actual=$(sha256sum "$DOWNLOAD_DIR/$asset_name" | sed 's/[[:space:]].*$//')
    if [ "$actual" != "$expected" ]; then
        echo "checksum mismatch: $asset_name" >&2
        exit 1
    fi
    echo "$asset_name: OK"
}

if [ "$MODE" = split ]; then
    verify_checksum_entry "$CORE_ASSET"
    verify_checksum_entry "$PROFILE_ASSET"

    CORE_NAME=$(dpkg-deb -f "$CORE_PACKAGE" Package)
    PROFILE_NAME=$(dpkg-deb -f "$PROFILE_PACKAGE" Package)
    CORE_VERSION=$(dpkg-deb -f "$CORE_PACKAGE" Version)
    PROFILE_VERSION=$(dpkg-deb -f "$PROFILE_PACKAGE" Version)
    CORE_ARCH=$(dpkg-deb -f "$CORE_PACKAGE" Architecture)
    PROFILE_ARCH=$(dpkg-deb -f "$PROFILE_PACKAGE" Architecture)
    PROFILE_DEPENDS=$(dpkg-deb -f "$PROFILE_PACKAGE" Depends)

    if [ "$CORE_NAME" != hidloom-core ]; then
        echo "unexpected core package name: $CORE_NAME" >&2
        exit 1
    fi
    if [ "$PROFILE_NAME" != "hidloom-profile-$PROFILE" ]; then
        echo "unexpected profile package name: $PROFILE_NAME" >&2
        exit 1
    fi
    if [ "$CORE_VERSION" != "$PROFILE_VERSION" ]; then
        echo "core/profile package version mismatch: $CORE_VERSION != $PROFILE_VERSION" >&2
        exit 1
    fi
    if [ "$CORE_ARCH" != arm64 ] || [ "$PROFILE_ARCH" != arm64 ]; then
        echo "core/profile package architecture must be arm64" >&2
        exit 1
    fi
    if ! printf '%s\n' "$PROFILE_DEPENDS" | grep -F "hidloom-core (= $CORE_VERSION)" >/dev/null; then
        echo "profile package lacks exact hidloom-core dependency: $CORE_VERSION" >&2
        exit 1
    fi
else
    verify_checksum_entry "$LEGACY_DEB_ASSET"
    LEGACY_NAME=$(dpkg-deb -f "$LEGACY_PACKAGE" Package)
    LEGACY_VERSION=$(dpkg-deb -f "$LEGACY_PACKAGE" Version)
fi

if [ "$DRY_RUN" -eq 0 ] && [ "$INSTALL" -eq 0 ]; then
    cat <<EOF
release package download ok
repository: $REPOSITORY
tag: $TAG
mode: $MODE
profile: $PROFILE
download_dir: $DOWNLOAD_DIR
EOF
    if [ "$MODE" = split ]; then
        cat <<EOF
core: $CORE_ASSET ($CORE_VERSION)
profile_package: $PROFILE_ASSET ($PROFILE_VERSION)
checksum: $CHECKSUM_ASSET
EOF
    else
        cat <<EOF
package: $LEGACY_DEB_ASSET ($LEGACY_NAME $LEGACY_VERSION)
checksum: $LEGACY_SHA_ASSET
EOF
    fi
    exit 0
fi

if [ "$MODE" = split ]; then
    remote_core="/tmp/$CORE_ASSET"
    remote_profile="/tmp/$PROFILE_ASSET"
    echo "copying split package set -> $REMOTE:/tmp/"
    scp "$CORE_PACKAGE" "$PROFILE_PACKAGE" "$REMOTE:/tmp/"
    remote_packages="'$remote_core' '$remote_profile'"
    query_packages="'hidloom-core' 'hidloom-profile-$PROFILE'"
else
    remote_legacy="/tmp/$LEGACY_DEB_ASSET"
    echo "copying $LEGACY_PACKAGE -> $REMOTE:$remote_legacy"
    scp "$LEGACY_PACKAGE" "$REMOTE:$remote_legacy"
    remote_packages="'$remote_legacy'"
    query_packages="'$LEGACY_NAME'"
fi

ssh "$REMOTE" "
    set -eu
    for package_path in $remote_packages; do
        dpkg-deb --info \"\$package_path\"
    done
    echo
    if [ '$MODE' = split ]; then
        echo 'package ownership preflight:'
        ownership_conflicts=
        for ownership_path in \
            /lib/systemd/system/btd.service \
            /usr/share/hidloom/profiles/$PROFILE/profile.json
        do
            owner_line=\$(dpkg-query -S \"\$ownership_path\" 2>/dev/null | sed -n '1p' || true)
            owner=\${owner_line%%:*}
            case \"\$owner\" in
                ''|hidloom|hidloom-core|hidloom-profile-$PROFILE)
                    if [ -n \"\$owner\" ]; then
                        echo \"ok-owner: \$ownership_path -> \$owner\"
                    else
                        echo \"unowned: \$ownership_path\"
                    fi
                    ;;
                *)
                    echo \"package ownership collision: \$owner owns \$ownership_path\" >&2
                    ownership_conflicts=\"\$ownership_conflicts \$owner\"
                    ;;
            esac
        done
        if [ -n \"\$ownership_conflicts\" ]; then
            echo 'remove the listed pre-hard-cut packages in the same apt transaction as the split install' >&2
            exit 1
        fi
        echo
    fi
    if [ '$INSTALL' -eq 1 ]; then
        if [ '$APT' -eq 1 ]; then
            echo 'apt install:'
            sudo apt-get install -y $remote_packages
        else
            echo 'dpkg install:'
            sudo dpkg -i $remote_packages
        fi
        if [ '$MODE' = split ]; then
            sudo hidloom-profile '$PROFILE' --apply --backup --restart
        fi
    else
        if [ '$APT' -eq 1 ]; then
            echo 'apt dry-run:'
            sudo apt-get -s install $remote_packages
        else
            echo 'dpkg dry-run:'
            sudo dpkg --dry-run -i $remote_packages
        fi
    fi
    echo
    dpkg-query -W $query_packages 2>/dev/null || true
"

if [ "$INSTALL" -eq 1 ]; then
    echo "remote release package install complete: $REMOTE ($MODE)"
else
    echo "remote release package dry-run complete: $REMOTE ($MODE)"
fi
