#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)

DEB=
OUT_DIR=${OUT_DIR:-"$REPO_ROOT/build/packages"}
TAG=
NOTES=
EXECUTE=0
SKIP_CANDIDATE_CHECK=0
SKIP_DOWNLOAD_VERIFY=0

usage() {
    cat <<'EOF'
usage: tools/package/publish_github_prerelease.sh [options]

Prepare or publish a GitHub prerelease for a checked Debian package.
By default this is a dry-run: it prints the tag and gh commands but does not
create tags, push, or upload release artifacts.

Options:
  --deb PATH                package path; default latest build/packages/*.deb
  --out-dir DIR            package output directory; default build/packages
  --tag TAG                release tag; default v<deb-version>
  --notes PATH             release note file; default build/packages/release-note-<tag>.md
  --skip-candidate-check   do not rerun release_candidate_check.sh
  --skip-download-verify   do not verify uploaded assets after publish
  --execute                create/push tag and create the GitHub prerelease
  -h, --help               show this help
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --deb)
            DEB=${2:?missing --deb value}
            shift 2
            ;;
        --out-dir)
            OUT_DIR=${2:?missing --out-dir value}
            shift 2
            ;;
        --tag)
            TAG=${2:?missing --tag value}
            shift 2
            ;;
        --notes)
            NOTES=${2:?missing --notes value}
            shift 2
            ;;
        --skip-candidate-check)
            SKIP_CANDIDATE_CHECK=1
            shift
            ;;
        --skip-download-verify)
            SKIP_DOWNLOAD_VERIFY=1
            shift
            ;;
        --execute)
            EXECUTE=1
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

if [ -z "$DEB" ]; then
    DEB=$(ls -t "$OUT_DIR"/hidloom_*_arm64.deb 2>/dev/null | sed -n '1p')
fi
if [ -z "$DEB" ] || [ ! -f "$DEB" ]; then
    echo "package not found; run make release-candidate-check first or pass --deb PATH" >&2
    exit 1
fi

SHA_FILE="$DEB.sha256"
if [ ! -f "$SHA_FILE" ]; then
    echo "missing sha256 file: $SHA_FILE" >&2
    exit 1
fi

version=$(dpkg-deb -f "$DEB" Version)
head_short=$(git -C "$REPO_ROOT" rev-parse --short HEAD)
case "$version" in
    *"+git$head_short"*) ;;
    *)
        echo "package version does not match current HEAD: version=$version HEAD=$head_short" >&2
        echo "run make release-candidate-check to build a package for the current commit" >&2
        exit 1
        ;;
esac
if [ -z "$TAG" ]; then
    TAG="v$version"
fi
if [ -z "$NOTES" ]; then
    NOTES="$OUT_DIR/release-note-$TAG.md"
fi

if [ "$SKIP_CANDIDATE_CHECK" -eq 0 ]; then
    "$SCRIPT_DIR/release_candidate_check.sh" \
        --deb "$DEB" \
        --skip-build \
        --note-out "$NOTES"
fi

if [ ! -f "$NOTES" ]; then
    echo "release note file not found: $NOTES" >&2
    exit 1
fi

if git -C "$REPO_ROOT" rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
    tag_exists=1
else
    tag_exists=0
fi

if [ "$EXECUTE" -eq 0 ]; then
    cat <<EOF
dry-run: GitHub prerelease publish plan
tag: $TAG
package: $DEB
sha256: $SHA_FILE
notes: $NOTES
tag_exists: $tag_exists

commands:
EOF
    if [ "$tag_exists" -eq 0 ]; then
        echo "  git tag $TAG"
        echo "  git push origin $TAG"
    else
        echo "  # tag already exists locally: $TAG"
        echo "  git push origin $TAG"
    fi
    echo "  gh release create $TAG \\"
    echo "    $DEB \\"
    echo "    $SHA_FILE \\"
    echo "    --prerelease \\"
    echo "    --title $TAG \\"
    echo "    --notes-file $NOTES"
    echo
    echo "dry-run only; pass --execute to create the prerelease"
    exit 0
fi

require_cmd gh

if [ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]; then
    echo "publish requires a clean git worktree" >&2
    exit 1
fi

if [ "$tag_exists" -eq 0 ]; then
    git -C "$REPO_ROOT" tag "$TAG"
fi
git -C "$REPO_ROOT" push origin "$TAG"
gh release create "$TAG" \
    "$DEB" \
    "$SHA_FILE" \
    --prerelease \
    --title "$TAG" \
    --notes-file "$NOTES"

if [ "$SKIP_DOWNLOAD_VERIFY" -eq 0 ]; then
    "$SCRIPT_DIR/verify_github_release_assets.sh" --tag "$TAG"
fi

echo "created GitHub prerelease: $TAG"
