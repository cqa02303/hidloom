#!/usr/bin/env sh
set -eu

REMOTE=
PROFILE=${HIDLOOM_DEVICE_PROFILE:-keyboard-ver1}
CONNECT_TIMEOUT=${HIDLOOM_SSH_CONNECT_TIMEOUT:-10}
RUN_SMOKE=0
ALLOW_DIRTY_MANIFEST=0

usage() {
    cat <<'EOF'
usage: tools/package/deploy_deb_verify.sh (--device 01|02 | --host USER@HOST) [options]

Verify that a Raspberry Pi is running the hidloom .deb layout.

Options:
  --device 01|02  target known device
  --host USER@HOST
  --profile PROFILE
                  installed device profile; default keyboard-ver1
  --connect-timeout SEC
                  SSH connect timeout; default 10
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
        --profile)
            PROFILE=${2:?missing --profile value}
            shift 2
            ;;
        --connect-timeout)
            CONNECT_TIMEOUT=${2:?missing --connect-timeout value}
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

case "$PROFILE" in
    ""|*[!A-Za-z0-9.+-]*)
        echo "invalid profile: $PROFILE" >&2
        exit 2
        ;;
esac
case "$CONNECT_TIMEOUT" in
    ""|*[!0-9]*|0)
        echo "invalid connect timeout: $CONNECT_TIMEOUT" >&2
        exit 2
        ;;
esac

run_ssh() {
    ssh \
        -o "ConnectTimeout=$CONNECT_TIMEOUT" \
        -o ServerAliveInterval=5 \
        -o ServerAliveCountMax=3 \
        "$REMOTE" "$@"
}

run_ssh "
    set -eu
    echo 'boot time:'
    uptime -s
    echo
    echo 'packages:'
    profile_package='hidloom-profile-$PROFILE'
    package_format='\${db:Status-Status} \${Package} \${Version} \${Architecture}\n'
    core_record=\$(dpkg-query -W -f=\"\$package_format\" hidloom-core)
    profile_record=\$(dpkg-query -W -f=\"\$package_format\" \"\$profile_package\")
    printf '%s\n%s\n' \"\$core_record\" \"\$profile_record\"
    set -- \$core_record
    core_state=\$1
    core_package=\$2
    core_version=\$3
    core_arch=\$4
    set -- \$profile_record
    profile_state=\$1
    installed_profile_package=\$2
    profile_version=\$3
    profile_arch=\$4
    if [ \"\$core_state\" != installed ] || [ \"\$profile_state\" != installed ]; then
        echo \"error: split package set is not fully installed\" >&2
        exit 1
    fi
    if [ \"\$core_package\" != hidloom-core ] || [ \"\$installed_profile_package\" != \"\$profile_package\" ]; then
        echo \"error: unexpected split package names\" >&2
        exit 1
    fi
    if [ \"\$core_arch\" != arm64 ] || [ \"\$profile_arch\" != arm64 ]; then
        echo \"error: split package architecture mismatch: core=\$core_arch profile=\$profile_arch\" >&2
        exit 1
    fi
    if [ \"\$core_version\" != \"\$profile_version\" ]; then
        echo \"error: split package version mismatch: core=\$core_version profile=\$profile_version\" >&2
        exit 1
    fi
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
    run_ssh "
        set -eu
        restore_output() {
            /usr/bin/hidloom-ctrl output auto || true
        }
        trap restore_output EXIT HUP INT TERM
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
        restore_output
        trap - EXIT HUP INT TERM
        echo 'output status after restore:'
        cat /run/hidloom/outputd-status.json
    "
fi
