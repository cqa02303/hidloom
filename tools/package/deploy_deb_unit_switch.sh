#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

REMOTE=
DRY_RUN=0
RESTART=0

usage() {
    cat <<'EOF'
usage: tools/package/deploy_deb_unit_switch.sh (--device 01|02 | --host USER@HOST) [options]

Copy switch_deb_systemd_units.sh to a Raspberry Pi and run it.

Options:
  --device 01|02  target known device
  --host USER@HOST
  --dry-run       show switch actions without changing files
  --restart       restart package-managed services after switching
  -h, --help      show this help

Use --dry-run before installing the .deb, and use non-dry-run only after the
package units exist under /lib/systemd/system.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
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
        --restart)
            RESTART=1
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

if [ -z "$REMOTE" ]; then
    echo "missing --device or --host" >&2
    usage >&2
    exit 2
fi

remote_script=/tmp/switch_deb_systemd_units.sh
scp "$SCRIPT_DIR/switch_deb_systemd_units.sh" "$REMOTE:$remote_script"

args=
if [ "$DRY_RUN" -eq 1 ]; then
    args="$args --dry-run"
fi
if [ "$RESTART" -eq 1 ]; then
    args="$args --restart"
fi

ssh "$REMOTE" "sudo sh '$remote_script' $args"
