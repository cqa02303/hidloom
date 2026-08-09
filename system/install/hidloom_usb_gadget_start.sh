#!/bin/bash
set -euo pipefail

# systemd-only front end for adopting an early-initramfs gadget.  The manual
# setup_usb_gadget.sh entry point keeps its explicit recreate semantics.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EARLY_MARKER="${HIDLOOM_EARLY_GADGET_MARKER:-/run/hidloom-early/gadget-bound.json}"
EARLY_ACCEPTED_MANIFEST="${HIDLOOM_EARLY_ACCEPTED_MANIFEST:-/var/lib/hidloom/early-boot/early-image.accepted.json}"
EARLY_RUNTIME_CONTRACT="${HIDLOOM_EARLY_RUNTIME_CONTRACT:-/run/hidloom-early/contract.json}"
EARLY_CONFIGFS_ROOT="${HIDLOOM_EARLY_CONFIGFS_ROOT:-/sys/kernel/config/usb_gadget}"
EARLY_GADGET_NAME="${HIDLOOM_EARLY_GADGET_NAME:-cqa02303v5}"
EARLY_GADGET_PATH="$EARLY_CONFIGFS_ROOT/$EARLY_GADGET_NAME"
EARLY_ADOPTER="${HIDLOOM_EARLY_GADGET_ADOPTER:-$REPO_ROOT/tools/rpi_os_early_gadget_adopt.py}"

require_adopter() {
    if [[ ! -f "$EARLY_ADOPTER" || -L "$EARLY_ADOPTER" ]]; then
        echo "Error: early USB gadget adopter is unavailable or unsafe: $EARLY_ADOPTER" >&2
        return 78
    fi
}

stop_gadget() {
    if [[ ! -e "$EARLY_GADGET_PATH" && ! -L "$EARLY_GADGET_PATH" ]]; then
        if [[ -e "$EARLY_MARKER" || -L "$EARLY_MARKER" ]]; then
            echo "Error: early marker exists but the gadget is absent during stop" >&2
            return 78
        fi
        return 0
    fi
    if [[ ! -d "$EARLY_GADGET_PATH" || -L "$EARLY_GADGET_PATH" ]]; then
        echo "Error: refusing to stop an unsafe USB gadget path: $EARLY_GADGET_PATH" >&2
        return 78
    fi
    local udc_path="$EARLY_GADGET_PATH/UDC"
    if [[ ! -f "$udc_path" || -L "$udc_path" ]]; then
        echo "Error: refusing to write an unsafe USB gadget UDC: $udc_path" >&2
        return 78
    fi
    if ! printf '\n' >"$udc_path" 2>/dev/null; then
        echo "Error: failed to unbind USB gadget UDC: $udc_path" >&2
        return 78
    fi
    local live_udc
    if ! live_udc="$(/bin/cat -- "$udc_path")"; then
        echo "Error: failed to read USB gadget UDC after unbind: $udc_path" >&2
        return 78
    fi
    if [[ -n "$live_udc" ]]; then
        echo "Error: USB gadget remained bound after stop: $live_udc" >&2
        return 78
    fi
    if [[ ! -e "$EARLY_MARKER" && ! -L "$EARLY_MARKER" ]]; then
        return 0
    fi

    require_adopter || return $?
    /usr/bin/python3 -S "$EARLY_ADOPTER" clear-marker-after-unbind \
        --marker "$EARLY_MARKER" \
        --runtime-contract "$EARLY_RUNTIME_CONTRACT" \
        --configfs-root "$EARLY_CONFIGFS_ROOT" \
        --gadget-name "$EARLY_GADGET_NAME" \
        --expected-owner-uid "${HIDLOOM_EARLY_EXPECTED_OWNER_UID:-0}"
}

if [[ "${1:-}" == "--stop" ]]; then
    if [[ "$#" -ne 1 ]]; then
        echo "Error: --stop does not accept additional arguments" >&2
        exit 78
    fi
    stop_gadget
    exit $?
fi

# The normal boot path has neither object and must not pay Python startup cost.
if [[ ! -e "$EARLY_MARKER" && ! -L "$EARLY_MARKER" && ! -e "$EARLY_GADGET_PATH" && ! -L "$EARLY_GADGET_PATH" ]]; then
    exec "$REPO_ROOT/setup_usb_gadget.sh" "$@"
fi

require_adopter || exit $?

set +e
/usr/bin/python3 -S "$EARLY_ADOPTER" verify \
    --marker "$EARLY_MARKER" \
    --accepted-manifest "$EARLY_ACCEPTED_MANIFEST" \
    --runtime-contract "$EARLY_RUNTIME_CONTRACT" \
    --configfs-root "$EARLY_CONFIGFS_ROOT" \
    --proc-root "${HIDLOOM_EARLY_PROC_ROOT:-/proc}" \
    --sys-root "${HIDLOOM_EARLY_SYS_ROOT:-/sys}" \
    --dev-root "${HIDLOOM_EARLY_DEV_ROOT:-/dev}" \
    --package-root "${HIDLOOM_EARLY_PACKAGE_ROOT:-/}" \
    --profile-root "${HIDLOOM_EARLY_PROFILE_ROOT:-/usr/share/hidloom/profiles}" \
    --runtime-profile-marker "${HIDLOOM_EARLY_RUNTIME_PROFILE_MARKER:-/mnt/p3/device_profile.json}" \
    --helper "${HIDLOOM_EARLY_INSTALLED_HELPER:-$REPO_ROOT/bin/hidloom-usb-gadget-fast}" \
    --gadget-name "$EARLY_GADGET_NAME" \
    --expected-owner-uid "${HIDLOOM_EARLY_EXPECTED_OWNER_UID:-0}"
adopter_status=$?
set -e

case "$adopter_status" in
    0)
        echo "Early USB gadget adopted without configfs mutation"
        exit 0
        ;;
    10)
        exec "$REPO_ROOT/setup_usb_gadget.sh" "$@"
        ;;
    *)
        echo "Error: refusing to recreate unverifiable early USB gadget (adopter exit $adopter_status)" >&2
        exit "$adopter_status"
        ;;
esac
