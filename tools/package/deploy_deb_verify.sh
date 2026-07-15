#!/usr/bin/env sh
set -eu

REMOTE=
RUN_SMOKE=0
ALLOW_DIRTY_MANIFEST=0

usage() {
    cat <<'EOF'
usage: tools/package/deploy_deb_verify.sh (--device 01|02 | --host USER@HOST) [options]

Verify that a Raspberry Pi is running the hidloom .deb layout.

Options:
  --device 01|02  target known device
  --host USER@HOST
  --smoke         run hidloom-hidd and logicd-core live smoke tests
  --allow-dirty-manifest
                  do not fail when package manifest says dirty_worktree_ignored=true
  -h, --help      show this help
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
        --smoke)
            RUN_SMOKE=1
            shift
            ;;
        --allow-dirty-manifest)
            ALLOW_DIRTY_MANIFEST=1
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

ssh "$REMOTE" "
    set -eu
    echo 'boot time:'
    uptime -s
    echo
    echo 'package:'
    dpkg-query -W hidloom
    echo
    echo 'manifest:'
    cat /var/lib/hidloom/package-manifest.json
    if grep -q '\"dirty_worktree_ignored\": true' /var/lib/hidloom/package-manifest.json && [ '$ALLOW_DIRTY_MANIFEST' -ne 1 ]; then
        echo 'error: installed manifest was built with dirty_worktree_ignored=true' >&2
        exit 1
    fi
    echo
    echo 'systemd units:'
    for unit in \
        hidloom-hidd.service \
        hidloom-uidd.service \
        hidloom-outputd.service \
        hidloom-logicd-core.service \
        matrixd.service \
        logicd-companion.service \
        httpd.service \
        i2cd.service \
        ledd.service \
        btd.service \
        viald.service \
        hidloom-usb-gadget.service \
        hidloom-late-services.timer \
        hidloom-network-late.timer
    do
        echo ===\$unit===
        systemctl show -p FragmentPath -p UnitFileState -p ActiveState -p SubState -p NRestarts \"\$unit\"
    done
"

if [ "$RUN_SMOKE" -eq 1 ]; then
    ssh "$REMOTE" "
        set -eu
        cd /usr/lib/hidloom
        for socket_path in /tmp/matrix_events.sock /tmp/matrix_tap_events.sock /tmp/logicd_delegate_events.sock; do
            ready=0
            for _ in \$(seq 1 50); do
                if [ -S \"\$socket_path\" ]; then
                    ready=1
                    break
                fi
                sleep 0.1
            done
            if [ \"\$ready\" -ne 1 ]; then
                echo \"socket not ready: \$socket_path\" >&2
                exit 1
            fi
        done
        python3 script/hidloom_hidd_live_smoke.py --delay 0.005 --malformed-count 1 --consumer-null-burst 3
        python3 tools/logicd_core_native_owner_live_smoke.py --apply --json
    "
fi
