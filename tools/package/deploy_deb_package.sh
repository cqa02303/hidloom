#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)

REMOTE=
DEB=
DRY_RUN=0
INSTALL=0
APT=0

usage() {
    cat <<'EOF'
usage: tools/package/deploy_deb_package.sh (--device 01|02 | --host USER@HOST) [options]

Copy a generated .deb to a Raspberry Pi and run a package install check.

Options:
  --device 01|02  target known device
  --host USER@HOST
  --deb PATH      package path; default latest build/packages/*.deb
  --dry-run       run install dry-run on the Pi
  --install       install the package on the Pi
  --apt           use apt-get for dependency-aware dry-run/install
  -h, --help      show this help

Use deb-unit-switch-* after --install when /etc systemd units still shadow the
package-owned units.
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
        --deb)
            DEB=${2:?missing --deb value}
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

if [ "$DRY_RUN" -eq "$INSTALL" ]; then
    echo "select exactly one of --dry-run or --install" >&2
    exit 2
fi

if [ -z "$DEB" ]; then
    best_deb=
    best_version=
    for candidate in "$REPO_ROOT"/build/packages/hidloom_*_arm64.deb; do
        if [ ! -f "$candidate" ]; then
            continue
        fi
        version=$(dpkg-deb -f "$candidate" Version 2>/dev/null || true)
        if [ -z "$version" ]; then
            continue
        fi
        if [ -z "$best_version" ] || dpkg --compare-versions "$version" gt "$best_version"; then
            best_version=$version
            best_deb=$candidate
        fi
    done
    DEB=$best_deb
fi

if [ -z "$DEB" ] || [ ! -f "$DEB" ]; then
    echo "package not found; run make deb-package first" >&2
    exit 1
fi

remote_deb="/tmp/$(basename "$DEB")"
echo "copying $DEB -> $REMOTE:$remote_deb"
scp "$DEB" "$REMOTE:$remote_deb"

ssh "$REMOTE" "
    set -eu
    dpkg-deb --info '$remote_deb'
    echo
    echo 'package key paths:'
    dpkg-deb --contents '$remote_deb' | grep -E './usr/lib/hidloom/bin/(hidloom-hidd|hidloom-usb-gadget-fast)|./usr/lib/hidloom/daemon/matrixd/matrixd|./lib/systemd/system/(hidloom-hidd|httpd|i2cd|ledd|btd|viald|hidloom-usb-gadget).service|./var/lib/hidloom/package-manifest.json' || true
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
    echo 'systemd unit shadow check:'
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
        fragment=\$(systemctl show -p FragmentPath --value \"\$unit\" 2>/dev/null || true)
        state=\$(systemctl show -p UnitFileState --value \"\$unit\" 2>/dev/null || true)
        case \"\$fragment\" in
            /etc/systemd/system/*)
                echo \"shadowed-by-etc: \$unit fragment=\$fragment state=\$state\"
                ;;
            '')
                echo \"not-loaded: \$unit state=\$state\"
                ;;
            *)
                echo \"ok-fragment: \$unit fragment=\$fragment state=\$state\"
                ;;
        esac
    done
    echo
    echo 'note: /etc/systemd/system units override package units under /lib/systemd/system.'
"

if [ "$INSTALL" -eq 1 ]; then
    echo "remote deb install complete: $REMOTE:$remote_deb"
else
    echo "remote deb dry-run complete: $REMOTE:$remote_deb"
fi
