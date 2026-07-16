#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

usage() {
    cat <<'EOF'
usage: tools/package/verify_github_release_assets.sh --tag TAG [options]

Download and verify the HIDloom Raspberry Pi OS split package assets from a
GitHub Release. This is a read-only wrapper around install_github_release_deb.sh.

Options passed through to the verifier:
  --tag TAG              GitHub Release tag to verify
  --repository OWNER/REPO
                         release repository; default cqa02303/hidloom
  --profile PROFILE      device profile; default keyboard-ver1
  --dir DIR              download directory; default temporary directory
  --keep                 keep the temporary download directory
  -h, --help             show this help
EOF
}

for argument in "$@"; do
    case "$argument" in
        -h|--help)
            usage
            exit 0
            ;;
    esac
done

exec "$SCRIPT_DIR/install_github_release_deb.sh" "$@"
