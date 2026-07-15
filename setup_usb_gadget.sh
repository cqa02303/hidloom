#!/bin/bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${HIDLOOM_USB_GADGET_SETUP_BACKEND:-shell}" == "native" ]]; then
    helper="$REPO_ROOT/bin/hidloom-usb-gadget-fast"
    if [[ ! -x "$helper" ]]; then
        echo "Error: native USB gadget helper is not executable: $helper" >&2
        echo "Run system/install/setup_fresh_rpi.sh or tools/hidloom_usb_gadget_fast/build.sh first." >&2
        exit 1
    fi
    exec "$helper" "$@"
fi
exec "$REPO_ROOT/system/install/setup_usb_gadget.sh" "$@"
