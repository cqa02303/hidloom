#!/usr/bin/env sh
set -eu

BACKUP_ROOT=${HIDLOOM_SYSTEMD_UNIT_BACKUP_ROOT:-/var/backups/hidloom/systemd-pre-deb}
SYSTEMD_ETC_DIR=${HIDLOOM_SYSTEMD_ETC_DIR:-/etc/systemd/system}
SYSTEMD_PACKAGE_DIR=${HIDLOOM_SYSTEMD_PACKAGE_DIR:-/lib/systemd/system}
DRY_RUN=0
RESTART=0
PROFILE=

usage() {
    cat <<'EOF'
usage: tools/package/switch_deb_systemd_units.sh [options]

Move rehearsal-generated /etc systemd units out of the way so Debian package
units under /lib/systemd/system become active.

Options:
  --dry-run          show actions without changing files
  --restart          restart package-managed services after switching
  --profile ID       final profile application (default: installed marker)
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
        --profile)
            PROFILE=${2:?missing --profile value}
            shift 2
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

if [ "$RESTART" -eq 1 ] && [ -z "$PROFILE" ]; then
    PROFILE=$(python3 -c 'import json; from pathlib import Path; print(json.loads(Path("/mnt/p3/device_profile.json").read_text())["id"])') || {
        echo "cannot determine installed profile; supply --profile ID" >&2
        exit 2
    }
fi
case "$PROFILE" in
    *[!A-Za-z0-9.+-]*) echo "invalid profile: $PROFILE" >&2; exit 2 ;;
esac
if [ "$RESTART" -eq 1 ] && [ -z "$PROFILE" ]; then
    echo "--restart requires an installed profile or --profile ID" >&2
    exit 2
fi

apply_selected_profile() {
    if [ "$RESTART" -ne 1 ]; then
        return
    fi
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "dry-run: would apply profile $PROFILE after migration without an earlier restart"
    else
        migration_phase="final profile application: $PROFILE"
        hidloom-profile "$PROFILE" --apply --backup --restart
    fi
}

if [ "$DRY_RUN" -ne 1 ] && [ "$(id -u)" -ne 0 ]; then
    echo "non-dry-run switch must run as root" >&2
    exit 1
fi

units="
btd.service
hidloom-bluetooth-unblock.service
hidloom-early-input-handoff-prepare.service
hidloom-early-input-handoff-finalize.service
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
    fragment=$(systemctl show -p FragmentPath --value "$unit")
    state=$(systemctl show -p UnitFileState --value "$unit")
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
    apply_selected_profile
    exit 0
fi

if [ "$DRY_RUN" -eq 1 ]; then
    echo "dry-run: would copy /etc units to $backup_dir and remove the /etc copies"
    echo "dry-run: would run systemctl daemon-reload and restore previous unit enable states"
    apply_selected_profile
    exit 0
fi

install -d -m 755 "$BACKUP_ROOT"
backup_dir=$(mktemp -d "$BACKUP_ROOT/$timestamp.XXXXXX")
state_file="$backup_dir/unit-states.tsv"
: > "$state_file"
echo "unit migration receipt: $state_file"
migration_phase=backup
trap 'migration_result=$?
    if [ "$migration_result" -ne 0 ]; then
        echo "unit migration incomplete: $migration_phase (exit $migration_result)" >&2
        echo "retained backup and unit state receipt: $backup_dir / $state_file" >&2
        echo "recovery: inspect the receipt; restore its backed-up unit files to $SYSTEMD_ETC_DIR, run systemctl daemon-reload, and restore the recorded enable/mask policy before restarting" >&2
        echo "installed package versions are unchanged by this recovery; no automatic package downgrade or service rollback was performed" >&2
    fi
    exit "$migration_result"' 0
for unit in $units; do
    etc_unit="$SYSTEMD_ETC_DIR/$unit"
    migration_phase="capture unit state: $unit"
    state=$(systemctl show -p UnitFileState --value "$unit")
    printf '%s\t%s\n' "$unit" "${state:-unknown}" >> "$state_file"
    if [ -f "$etc_unit" ]; then
        migration_phase="backup/remove unit: $unit"
        cp -a "$etc_unit" "$backup_dir/$unit"
        rm -f "$etc_unit"
    fi
done

migration_phase=daemon-reload
systemctl daemon-reload
while IFS="$(printf '\t')" read -r unit state; do
    migration_phase="restore unit state: $unit ($state)"
    case "$state" in
        enabled)
            systemctl enable "$unit"
            ;;
        enabled-runtime)
            systemctl enable --runtime "$unit"
            ;;
        linked)
            systemctl link "$SYSTEMD_PACKAGE_DIR/$unit"
            ;;
        linked-runtime)
            systemctl link --runtime "$SYSTEMD_PACKAGE_DIR/$unit"
            ;;
        disabled|indirect)
            systemctl disable "$unit"
            ;;
        masked)
            systemctl mask "$unit"
            ;;
        masked-runtime)
            systemctl mask --runtime "$unit"
            ;;
        static|generated|transient|unknown|"")
            :
            ;;
        *)
            echo "note: preserving unknown UnitFileState for $unit: $state"
            ;;
    esac
done < "$state_file"

apply_selected_profile

echo "migrated /etc units to package units"
echo "backup dir: $backup_dir"
echo "rollback: copy $backup_dir/*.service back to $SYSTEMD_ETC_DIR, run systemctl daemon-reload, then restart services"
