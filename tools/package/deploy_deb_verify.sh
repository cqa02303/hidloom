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
        hidloom-early-input-handoff-prepare.service \
        hidloom-early-input-handoff-finalize.service \
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
        systemctl show -p FragmentPath -p UnitFileState -p ActiveState -p SubState -p NRestarts -p Result -p ExecMainStatus \"\$unit\"
        result=\$(systemctl show -p Result --value \"\$unit\")
        if [ \"\$result\" = failed ]; then
            echo \"error: systemd unit failed: \$unit\" >&2
            exit 1
        fi
    done
    echo
    echo 'matrixd and early-handoff status:'
    sudo -n python3 - '$PROFILE' /usr/share/hidloom/profiles /run/hidloom /run/hidloom-early 10 <<'PY'
# HIDLOOM_DEPLOY_RUNTIME_STATUS_CHECK_BEGIN
import json
from pathlib import Path
import sys
import time


def load(path: Path) -> dict:
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise SystemExit(f'error: status is not an object: {path}')
    return value


profile_id = sys.argv[1]
profile_root = Path(sys.argv[2])
runtime_root = Path(sys.argv[3])
root = Path(sys.argv[4])
status_timeout = float(sys.argv[5])
if status_timeout <= 0:
    raise SystemExit('error: matrixd status timeout must be positive')
profile = load(profile_root / profile_id / 'profile.json')
if profile.get('id') != profile_id:
    raise SystemExit(f'error: installed profile identity mismatch: {profile}')
services = profile.get('services')
if not isinstance(services, dict):
    raise SystemExit(f'error: installed profile services are invalid: {profile}')
enabled = services.get('enable', [])
disabled = services.get('disable', [])
masked = services.get('mask', [])
if not all(isinstance(value, list) for value in (enabled, disabled, masked)):
    raise SystemExit(f'error: installed profile service policy is invalid: {services}')

matrix_unit = 'matrixd.service'
if matrix_unit in enabled:
    if matrix_unit in disabled or matrix_unit in masked:
        raise SystemExit(f'error: installed profile has conflicting matrixd policy: {services}')
    deadline = time.monotonic() + status_timeout
    matrix = None
    last_error = None
    while True:
        try:
            candidate = load(runtime_root / 'matrixd-status.json')
            logic = candidate.get('logic_socket', {})
            if (
                candidate.get('schema') == 'matrixd.status.v1'
                and candidate.get('process') is True
                and candidate.get('configured') is True
                and candidate.get('gpio_ready') is True
                and isinstance(logic, dict)
                and logic.get('connected') is True
            ):
                matrix = candidate
                break
            matrix = candidate
            last_error = None
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            last_error = f'{type(exc).__name__}: {exc}'
        if time.monotonic() >= deadline:
            raise SystemExit(
                f'error: matrixd status did not become ready: last={matrix} error={last_error}'
            )
        time.sleep(0.05)
    print(f'matrixd status: ready profile={profile_id}')
elif matrix_unit in disabled or matrix_unit in masked:
    print(f'matrixd status: not-applicable profile={profile_id}')
else:
    raise SystemExit(f'error: installed profile has no matrixd service policy: {services}')

ready = root / 'e3-input.ready'
prepared = root / 'e4-handoff.prepare.json'
complete = root / 'e4-handoff.complete.json'
if ready.exists():
    prepare_value = load(str(prepared))
    complete_value = load(str(complete))
    if prepare_value.get('schema') != 'hidloom.rpi-os-early-input-handoff.prepare.v1' or prepare_value.get('status') != 'prepared':
        raise SystemExit(f'error: E4 prepare evidence is incomplete: {prepare_value}')
    if complete_value.get('schema') != 'hidloom.rpi-os-early-input-handoff.complete.v1' or complete_value.get('status') != 'complete':
        raise SystemExit(f'error: E4 completion evidence is incomplete: {complete_value}')
    print('early handoff status: complete')
elif prepared.exists() or complete.exists():
    raise SystemExit('error: E4 evidence exists without an E3 ready marker')
else:
    print('early handoff status: not-applicable normal boot')
# HIDLOOM_DEPLOY_RUNTIME_STATUS_CHECK_END
PY
"

if [ "$RUN_SMOKE" -eq 1 ]; then
    run_ssh "
        set -eu
        cd /usr/lib/hidloom
        native_owner_smoke=\$(python3 - '$PROFILE' /usr/share/hidloom/profiles <<'PY'
# HIDLOOM_DEPLOY_NATIVE_SMOKE_POLICY_BEGIN
import json
from pathlib import Path
import sys


profile_id = sys.argv[1]
profile_path = Path(sys.argv[2]) / profile_id / 'profile.json'
profile = json.loads(profile_path.read_text(encoding='utf-8'))
if not isinstance(profile, dict) or profile.get('id') != profile_id:
    raise SystemExit(f'error: installed profile identity mismatch: {profile}')
services = profile.get('services')
if not isinstance(services, dict):
    raise SystemExit(f'error: installed profile services are invalid: {profile}')


def service_set(name: str):
    value = services.get(name, [])
    if not isinstance(value, list) or not all(isinstance(unit, str) for unit in value):
        raise SystemExit(f'error: installed profile service policy is invalid: {services}')
    return set(value)


enabled = service_set('enable')
blocked = service_set('disable') | service_set('mask')
native_units = {
    'hidloom-uidd.service',
    'hidloom-outputd.service',
    'hidloom-logicd-core.service',
    'matrixd.service',
}
if native_units <= enabled and not (native_units & blocked):
    print('required')
elif native_units <= blocked and not (native_units & enabled):
    print('skipped')
else:
    raise SystemExit(
        f'error: installed profile has ambiguous native-owner smoke policy: {services}'
    )
# HIDLOOM_DEPLOY_NATIVE_SMOKE_POLICY_END
PY
        )
        echo "native owner smoke policy: \$native_owner_smoke profile=$PROFILE"
        restore_output() {
            /usr/bin/hidloom-ctrl output auto || true
        }
        if [ "\$native_owner_smoke" = required ]; then
            trap restore_output EXIT HUP INT TERM
        fi
        # A bound configfs gadget is not yet usable until the physical host has
        # enumerated it and hidloom-hidd has completed both startup releases.
        # Sending Unix datagrams earlier only queues smoke frames behind the
        # blocking HID write, so fail before sending anything in that state.
        python3 - <<'PY'
import json
from pathlib import Path
import sys
import time

deadline = time.monotonic() + 10.0
last = 'not checked'
while time.monotonic() < deadline:
    try:
        udc = Path('/sys/kernel/config/usb_gadget/cqa02303v5/UDC').read_text().strip()
        state = (Path('/sys/class/udc') / udc / 'state').read_text().strip()
        status = json.loads(Path('/run/hidloom/hidd-status.json').read_text())
        counters = status.get('counters', {})
        endpoints = status.get('endpoints', {})
        startup = counters.get('startup_release_reports', -1)
        udc_label = udc if udc else 'unbound'
        last = f'udc={udc_label} state={state} startup_release_reports={startup}'
        if (
            udc
            and state in {'configured', 'suspended'}
            and status.get('process') is True
            and status.get('socket', {}).get('listening') is True
            and endpoints.get('hidg0', {}).get('open') is True
            and endpoints.get('hidg2', {}).get('open') is True
            and isinstance(startup, int)
            and startup >= 2
        ):
            print(f'hidd smoke readiness: {last}')
            break
    except (OSError, ValueError, TypeError) as exc:
        last = f'{type(exc).__name__}: {exc}'
    time.sleep(0.1)
else:
    print(f'error: hidd smoke not ready; no frames sent: {last}', file=sys.stderr)
    raise SystemExit(1)
PY
        python3 script/hidloom_hidd_live_smoke.py --delay 0.005 --malformed-count 1 --consumer-null-burst 3
        if [ \"\$native_owner_smoke\" = required ]; then
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
            python3 tools/logicd_core_native_owner_live_smoke.py --apply --json
            restore_output
            trap - EXIT HUP INT TERM
            echo 'output status after restore:'
            cat /run/hidloom/outputd-status.json
        else
            echo \"native owner smoke: skipped profile=$PROFILE policy=disabled-or-masked\"
        fi
    "
fi
