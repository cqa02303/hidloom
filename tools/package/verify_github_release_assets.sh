#!/usr/bin/env sh
set -eu

TAG=
DOWNLOAD_DIR=
KEEP=0

usage() {
    cat <<'EOF'
usage: tools/package/verify_github_release_assets.sh --tag TAG [options]

Download a GitHub Release .deb and .deb.sha256 into a temporary directory and
verify that the checksum file is portable and passes sha256sum -c.

Options:
  --tag TAG       GitHub Release tag to verify
  --dir DIR       download directory; default temporary directory
  --keep          keep the temporary download directory
  -h, --help      show this help
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

cat <<EOF
release asset verification ok
tag: $TAG
package: $(basename "$DEB")
sha256: $(cat "$SHA_FILE")
download_dir: $DOWNLOAD_DIR
EOF
