#!/usr/bin/env sh
set -eu

TAG=
NOTES_FILE=
SKIP_ASSET_VERIFY=0

usage() {
    cat <<'EOF'
usage: tools/package/check_github_release_stable_ready.sh --tag TAG [options]

Read a GitHub Release note and fail if it still looks like a prerelease-only
candidate. This is a read-only gate to run before removing the prerelease flag.

Options:
  --tag TAG              GitHub Release tag to check
  --notes-file PATH      check this release note text instead of gh release view
  --skip-asset-verify    do not run verify_github_release_assets.sh
  -h, --help             show this help
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --tag)
            TAG=${2:?missing --tag value}
            shift 2
            ;;
        --notes-file)
            NOTES_FILE=${2:?missing --notes-file value}
            shift 2
            ;;
        --skip-asset-verify)
            SKIP_ASSET_VERIFY=1
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

require_cmd grep
require_cmd mktemp

if [ -z "$TAG" ]; then
    echo "missing --tag TAG" >&2
    usage >&2
    exit 2
fi

TMP_DIR=$(mktemp -d)
cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT INT TERM

if [ -z "$NOTES_FILE" ]; then
    require_cmd gh
    NOTES_FILE="$TMP_DIR/release-note.md"
    gh release view "$TAG" --json body --jq .body > "$NOTES_FILE"
fi

if [ ! -f "$NOTES_FILE" ]; then
    echo "release note file not found: $NOTES_FILE" >&2
    exit 1
fi

if grep -Eiq 'not tested|skipped|known risk|prerelease candidate|No route to host' "$NOTES_FILE"; then
    echo "release is not stable-ready: release note still contains prerelease-only wording" >&2
    echo "blocked phrases include: not tested, skipped, known risk, prerelease candidate, No route to host" >&2
    exit 1
fi

require_line() {
    pattern=$1
    message=$2
    if ! grep -Eiq "$pattern" "$NOTES_FILE"; then
        echo "release is not stable-ready: $message" >&2
        exit 1
    fi
}

require_line '<keyboard-host> install: (passed|ok)' "missing <keyboard-host> install passed/ok"
require_line '<keyboard-host> smoke: (passed|ok)' "missing <keyboard-host> smoke passed/ok"
require_line '<keyboard-host> (install|verify): (passed|ok)' "missing <keyboard-host> install/verify passed/ok"
require_line 'failed units: (0|passed|ok)' "missing failed units 0/passed/ok"
require_line 'rollback: (confirmed|passed|ok)' "missing rollback confirmed/passed/ok"

if [ "$SKIP_ASSET_VERIFY" -eq 0 ]; then
    "$(dirname "$0")/verify_github_release_assets.sh" --tag "$TAG"
fi

cat <<EOF
stable release readiness ok
tag: $TAG
notes: $NOTES_FILE
EOF
