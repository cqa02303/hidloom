#!/usr/bin/env sh
set -eu

TAG=
DOWNLOAD_DIR=
REMOTE=
DRY_RUN=0
INSTALL=0
APT=0
KEEP=0

usage() {
    cat <<'EOF'
usage: tools/package/install_github_release_deb.sh --tag TAG [options]

Download a GitHub Release .deb, verify its portable sha256 file, and optionally
copy it to a Raspberry Pi for dpkg or apt dry-run/install.

Options:
  --tag TAG        GitHub Release tag to download
  --dir DIR        download directory; default temporary directory
  --device 01|02   target known device for remote install
  --host USER@HOST target explicit remote host for remote install
  --dry-run        run remote install simulation/check
  --install        install on the remote host
  --apt            use apt-get for dependency-aware dry-run/install
  --keep           keep the temporary download directory
  -h, --help       show this help

Without --dry-run or --install this script only downloads and verifies assets.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --tag)
            TAG=${2:?missing --tag value}
            shift 2
            ;;
        --dir)
            DOWNLOAD_DIR=${2:?missing --dir value}
            shift 2
            ;;
        --device)
            case "${2:?missing --device value}" in
                01) REMOTE=${HIDLOOM_RPI_01:-operator@<keyboard-ip>} ;;
                02) REMOTE=${HIDLOOM_RPI_02:-pi@<keyboard-ip>} ;;
                *)
                    echo "unknown device: $2" >&2
                    exit 2
                    ;;
            esac
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

require_cmd find
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

if [ "$DRY_RUN" -eq 1 ] || [ "$INSTALL" -eq 1 ]; then
    if [ -z "$REMOTE" ]; then
        echo "remote install requires --device or --host" >&2
        exit 2
    fi
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

gh release view "$TAG" >/dev/null
gh release download "$TAG" --dir "$DOWNLOAD_DIR" --pattern '*.deb*'

deb_count=$(find "$DOWNLOAD_DIR" -maxdepth 1 -type f -name '*.deb' | wc -l)
sha_count=$(find "$DOWNLOAD_DIR" -maxdepth 1 -type f -name '*.deb.sha256' | wc -l)
if [ "$deb_count" -ne 1 ]; then
    echo "expected exactly one .deb asset, found $deb_count in $DOWNLOAD_DIR" >&2
    exit 1
fi
if [ "$sha_count" -ne 1 ]; then
    echo "expected exactly one .deb.sha256 asset, found $sha_count in $DOWNLOAD_DIR" >&2
    exit 1
fi

DEB=$(find "$DOWNLOAD_DIR" -maxdepth 1 -type f -name '*.deb' | sed -n '1p')
SHA_FILE=$(find "$DOWNLOAD_DIR" -maxdepth 1 -type f -name '*.deb.sha256' | sed -n '1p')

if grep -E '(^|[[:space:]])/' "$SHA_FILE" >/dev/null; then
    echo "sha256 file is not portable; it contains an absolute path: $SHA_FILE" >&2
    exit 1
fi
if ! grep -F "$(basename "$DEB")" "$SHA_FILE" >/dev/null; then
    echo "sha256 file does not reference downloaded package basename: $(basename "$DEB")" >&2
    exit 1
fi

(cd "$DOWNLOAD_DIR" && sha256sum -c "$(basename "$SHA_FILE")")

if [ "$DRY_RUN" -eq 0 ] && [ "$INSTALL" -eq 0 ]; then
    cat <<EOF
release deb download ok
tag: $TAG
package: $DEB
sha256: $(cat "$SHA_FILE")
download_dir: $DOWNLOAD_DIR
EOF
    exit 0
fi

remote_deb="/tmp/$(basename "$DEB")"
echo "copying $DEB -> $REMOTE:$remote_deb"
scp "$DEB" "$REMOTE:$remote_deb"

ssh "$REMOTE" "
    set -eu
    dpkg-deb --info '$remote_deb'
    echo
    if [ '$INSTALL' -eq 1 ]; then
        if [ '$APT' -eq 1 ]; then
            echo 'apt install:'
            sudo apt-get install -y '$remote_deb'
        else
            echo 'dpkg install:'
            sudo dpkg -i '$remote_deb'
        fi
    else
        if [ '$APT' -eq 1 ]; then
            echo 'apt dry-run:'
            sudo apt-get -s install '$remote_deb'
        else
            echo 'dpkg dry-run:'
            sudo dpkg --dry-run -i '$remote_deb'
        fi
    fi
    echo
    dpkg-query -W hidloom 2>/dev/null || true
"

if [ "$INSTALL" -eq 1 ]; then
    echo "remote release deb install complete: $REMOTE:$remote_deb"
else
    echo "remote release deb dry-run complete: $REMOTE:$remote_deb"
fi
