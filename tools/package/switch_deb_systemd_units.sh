#!/usr/bin/env sh
set -eu

BACKUP_ROOT=${HIDLOOM_SYSTEMD_UNIT_BACKUP_ROOT:-/var/backups/hidloom/systemd-pre-deb}
SYSTEMD_ETC_DIR=${HIDLOOM_SYSTEMD_ETC_DIR:-/etc/systemd/system}
SYSTEMD_PACKAGE_DIR=${HIDLOOM_SYSTEMD_PACKAGE_DIR:-/lib/systemd/system}
DRY_RUN=0
RESTART=0

usage() {
    cat <<'EOF'
usage: tools/package/switch_deb_systemd_units.sh [options]

Move rehearsal-generated /etc systemd units out of the way so Debian package
units under /lib/systemd/system become active.

Options:
  --dry-run          show actions without changing files
  --restart          restart package-managed services after switching
  --backup-root DIR  backup root; default /var/backups/hidloom/systemd-pre-deb
  -h, --help         show this help

Run this on the Raspberry Pi after hidloom.deb has been installed.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --restart)
            RESTART=1
            shift
            ;;
        --backup-root)
            BACKUP_ROOT=${2:?missing --backup-root value}
            shift 2
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

if [ "$DRY_RUN" -ne 1 ] && [ "$(id -u)" -ne 0 ]; then
    echo "non-dry-run switch must run as root" >&2
    exit 1
fi

units="
btd.service
hidloom-bluetooth-unblock.service
hidloom-hidd.service
hidloom-late-services.service
hidloom-late-services.timer
hidloom-uidd.service
hidloom-outputd.service
hidloom-logicd-core.service
hidloom-network-late.service
hidloom-network-late.timer
hidloom-power-shed.service
hidloom-touch-panel-profile.service
hidloom-usb-gadget.service
matrixd.service
logicd-companion.service
logicd.service
httpd.service
i2cd.service
ledd.service
ledd-shutdown.service
spid.service
usbd.service
viald.service
"

restart_units="
hidloom-usb-gadget.service
hidloom-hidd.service
hidloom-uidd.service
hidloom-outputd.service
hidloom-logicd-core.service
matrixd.service
logicd-companion.service
httpd.service
i2cd.service
ledd.service
btd.service
viald.service
"

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_dir="$BACKUP_ROOT/$timestamp"
missing_package=0
found_etc=0

echo "systemd deb unit switch preflight"
echo "etc unit dir: $SYSTEMD_ETC_DIR"
echo "package unit dir: $SYSTEMD_PACKAGE_DIR"
echo "backup dir: $backup_dir"

for unit in $units; do
    etc_unit="$SYSTEMD_ETC_DIR/$unit"
    package_unit="$SYSTEMD_PACKAGE_DIR/$unit"
    fragment=$(systemctl show -p FragmentPath --value "$unit" 2>/dev/null || true)
    state=$(systemctl show -p UnitFileState --value "$unit" 2>/dev/null || true)
    if [ -f "$etc_unit" ]; then
        found_etc=1
        if [ ! -f "$package_unit" ]; then
            missing_package=1
            echo "missing-package-unit: $unit package=$package_unit current_fragment=${fragment:-unknown} state=${state:-unknown}"
        else
            echo "will-backup-remove: $unit etc=$etc_unit package=$package_unit current_fragment=${fragment:-unknown} state=${state:-unknown}"
        fi
    elif [ -f "$package_unit" ]; then
        echo "already-package-unit: $unit package=$package_unit current_fragment=${fragment:-unknown} state=${state:-unknown}"
    else
        missing_package=1
        echo "missing-both-units: $unit current_fragment=${fragment:-unknown} state=${state:-unknown}"
    fi
done

if [ "$missing_package" -eq 1 ]; then
    echo "package units are missing; install the .deb before switching" >&2
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "dry-run: switch is blocked until package units exist"
        exit 0
    fi
    exit 1
fi

if [ "$found_etc" -eq 0 ]; then
    echo "no /etc units need migration"
    if [ "$RESTART" -eq 1 ]; then
        if [ "$DRY_RUN" -eq 1 ]; then
            echo "dry-run: would restart package-managed services"
        else
            systemctl restart $restart_units
            echo "restarted package-managed services"
        fi
    fi
    exit 0
fi

if [ "$DRY_RUN" -eq 1 ]; then
    echo "dry-run: would copy /etc units to $backup_dir and remove the /etc copies"
    echo "dry-run: would run systemctl daemon-reload and restore previous unit enable states"
    if [ "$RESTART" -eq 1 ]; then
        echo "dry-run: would restart package-managed services"
    fi
    exit 0
fi

install -d -m 755 "$backup_dir"
state_file="$backup_dir/unit-states.tsv"
: > "$state_file"
for unit in $units; do
    etc_unit="$SYSTEMD_ETC_DIR/$unit"
    state=$(systemctl show -p UnitFileState --value "$unit" 2>/dev/null || true)
    printf '%s\t%s\n' "$unit" "${state:-unknown}" >> "$state_file"
    if [ -f "$etc_unit" ]; then
        cp -a "$etc_unit" "$backup_dir/$unit"
        rm -f "$etc_unit"
    fi
done

systemctl daemon-reload
while IFS="$(printf '\t')" read -r unit state; do
    case "$state" in
        enabled|enabled-runtime|linked|linked-runtime)
            systemctl enable "$unit" >/dev/null 2>&1 || true
            ;;
        disabled|indirect)
            systemctl disable "$unit" >/dev/null 2>&1 || true
            ;;
        masked|masked-runtime)
            systemctl mask "$unit" >/dev/null 2>&1 || true
            ;;
        static|generated|transient|unknown|"")
            :
            ;;
        *)
            echo "note: preserving unknown UnitFileState for $unit: $state"
            ;;
    esac
done < "$state_file"

if [ "$RESTART" -eq 1 ]; then
    systemctl restart $restart_units
fi

echo "migrated /etc units to package units"
echo "backup dir: $backup_dir"
echo "rollback: copy $backup_dir/*.service back to $SYSTEMD_ETC_DIR, run systemctl daemon-reload, then restart services"
