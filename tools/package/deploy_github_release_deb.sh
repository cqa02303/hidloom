#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

TAG=
REMOTE_ARG=
DRY_RUN=0
INSTALL=0
RUN_SMOKE=1
KEEP=0

usage() {
    cat <<'EOF'
usage: tools/package/deploy_github_release_deb.sh --tag TAG (--device 01|02 | --host USER@HOST) [options]

Download and verify a GitHub Release .deb, then run the release install flow on
a Raspberry Pi.

Options:
  --tag TAG        GitHub Release tag to deploy
  --device 01|02   target known device
  --host USER@HOST target explicit remote host
  --dry-run        run apt dependency-aware dry-run and unit switch dry-run only
  --install        install package, switch package units, and verify
  --no-smoke       with --install, run package verify without live smoke
  --keep           keep the temporary release asset download directory
  -h, --help       show this help

This script requires exactly one of --dry-run or --install. Use --dry-run first.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --tag)
            TAG=${2:?missing --tag value}
            shift 2
            ;;
        --device)
            case "${2:?missing --device value}" in
                01|02) REMOTE_ARG="--device $2" ;;
                *)
                    echo "unknown device: $2" >&2
                    exit 2
                    ;;
            esac
            shift 2
            ;;
        --host)
            REMOTE_ARG="--host ${2:?missing --host value}"
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
        --no-smoke)
            RUN_SMOKE=0
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

if [ -z "$TAG" ]; then
    echo "missing --tag TAG" >&2
    usage >&2
    exit 2
fi
if [ -z "$REMOTE_ARG" ]; then
    echo "missing --device or --host" >&2
    usage >&2
    exit 2
fi
if [ "$DRY_RUN" -eq "$INSTALL" ]; then
    echo "select exactly one of --dry-run or --install" >&2
    exit 2
fi

keep_arg=
if [ "$KEEP" -eq 1 ]; then
    keep_arg="--keep"
fi

if [ "$DRY_RUN" -eq 1 ]; then
    echo "== release deb install dry-run =="
    # shellcheck disable=SC2086
    "$SCRIPT_DIR/install_github_release_deb.sh" --tag "$TAG" $REMOTE_ARG --dry-run --apt $keep_arg
    echo
    echo "== package unit switch dry-run =="
    # shellcheck disable=SC2086
    "$SCRIPT_DIR/deploy_deb_unit_switch.sh" $REMOTE_ARG --dry-run
    echo
    echo "release deb deploy dry-run complete: $TAG"
    exit 0
fi

echo "== release deb install =="
# shellcheck disable=SC2086
"$SCRIPT_DIR/install_github_release_deb.sh" --tag "$TAG" $REMOTE_ARG --install --apt $keep_arg
echo
echo "== package unit switch and restart =="
# shellcheck disable=SC2086
"$SCRIPT_DIR/deploy_deb_unit_switch.sh" $REMOTE_ARG --restart
echo
echo "== package verify =="
verify_args=
if [ "$RUN_SMOKE" -eq 1 ]; then
    verify_args="--smoke"
fi
# shellcheck disable=SC2086
"$SCRIPT_DIR/deploy_deb_verify.sh" $REMOTE_ARG $verify_args
echo
echo "release deb deploy complete: $TAG"
