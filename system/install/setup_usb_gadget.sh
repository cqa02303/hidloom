#!/bin/bash
# CQA02303v5 USB Gadget setup script.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONFIG_FILE="$REPO_ROOT/config/default/config.json"
GADGET_NAME="cqa02303v5"
NODE_NAME="$(uname -n)"

VENDOR_ID="0x1d6b"
PRODUCT_ID="0x0105"
MANUFACTURER="$NODE_NAME"
SERIAL_NUMBER="vial:f64c2b3c"
PRODUCT_NAME="$NODE_NAME"
HID_COUNTRY_CODE="0"
KEYBOARD_IDENTITY_STRINGS_PROFILE="${HIDLOOM_USB_KEYBOARD_IDENTITY_STRINGS:-default}"
KEYBOARD_ONLY_TEST_ENABLED="${HIDLOOM_USB_KEYBOARD_ONLY_TEST:-0}"
US_SUB_KEYBOARD_ENABLED="${HIDLOOM_USB_US_SUB_KEYBOARD:-0}"
WINDOWS_IME_CUSTOM_HID_ENABLED="${HIDLOOM_WINDOWS_IME_CUSTOM_HID:-0}"
HID_INTERFACE_STRINGS_ENABLED="${HIDLOOM_USB_HID_INTERFACE_STRINGS:-0}"
WINDOWS_IME_CUSTOM_HID_REPORT_LENGTH="8"
WINDOWS_IME_CUSTOM_HID_REPORT_DESC='\x06\x70\xff\x09\x01\xa1\x01\x15\x00\x26\xff\x00\x75\x08\x95\x08\x09\x02\x81\x02\x95\x08\x09\x03\x91\x02\xc0'
US_KEYBOARD_IDENTITY_STRING="${HIDLOOM_US_KEYBOARD_IDENTITY_STRING:-US101}"
US_SUB_KEYBOARD_IDENTITY_STRING="${HIDLOOM_US_SUB_KEYBOARD_IDENTITY_STRING:-US101}"
US_SUB_KEYBOARD_REPORT_LENGTH="8"
US_SUB_KEYBOARD_REPORT_DESC='\x05\x01\x09\x06\xa1\x01\x05\x07\x19\xe0\x29\xe7\x15\x00\x25\x01\x75\x01\x95\x08\x81\x02\x95\x01\x75\x08\x81\x03\x95\x06\x75\x08\x15\x00\x26\xff\x00\x05\x07\x19\x00\x2a\xff\x00\x81\x00\x05\x08\x19\x01\x29\x05\x15\x00\x25\x01\x75\x01\x95\x05\x91\x02\x75\x03\x95\x01\x91\x03\xc0'

echo "USB HID Keyboard Gadget Setup"

if [[ -f "$CONFIG_FILE" ]]; then
    echo "Loading config: $CONFIG_FILE"
    if command -v jq >/dev/null 2>&1; then
        eval "$(
            jq -r --arg product_name "$PRODUCT_NAME" '
                def sh($name; $value): $name + "=" + ($value | @sh);
                sh("VENDOR_ID"; .device.vendor_id // "0x1d6b"),
                sh("PRODUCT_ID"; .device.product_id // "0x0105"),
                sh("MANUFACTURER"; .device.manufacturer // "__HOSTNAME__"),
                sh("PRODUCT_NAME"; .device.product_name // $product_name),
                sh("SERIAL_NUMBER"; .device.serial_number // "vial:f64c2b3c"),
                sh("HID_COUNTRY_CODE"; .device.hid_country_code // .device.country_code // 0),
                sh("CONFIG_KEYBOARD_IDENTITY_STRINGS_PROFILE"; .settings.usb_keyboard_identity_strings.profile // "default"),
                sh("CONFIG_USB_JP_DRIVER_FALLBACK_STRINGS_ENABLED"; .settings.usb_jp_driver_fallback_strings.enabled // false),
                sh("CONFIG_WINDOWS_IME_CUSTOM_HID_ENABLED"; .settings.windows_ime_custom_hid.enabled // false),
                sh("CONFIG_US_SUB_KEYBOARD_ENABLED"; .settings.us_sub_keyboard.enabled // false),
                sh("CONFIG_US_SUB_KEYBOARD_IDENTITY_STRING"; .settings.us_sub_keyboard.identity_string // "US101"),
                sh("CONFIG_US_KEYBOARD_IDENTITY_STRING"; .settings.us_keyboard.identity_string // "US101")
            ' "$CONFIG_FILE"
        )"
        if [[ -z "${HIDLOOM_USB_KEYBOARD_IDENTITY_STRINGS:-}" ]]; then
            KEYBOARD_IDENTITY_STRINGS_PROFILE="$CONFIG_KEYBOARD_IDENTITY_STRINGS_PROFILE"
            if [[ -z "${HIDLOOM_USB_JP_DRIVER_FALLBACK_STRINGS:-}" ]] && [[ "$KEYBOARD_IDENTITY_STRINGS_PROFILE" == "default" ]]; then
                if [[ "$CONFIG_USB_JP_DRIVER_FALLBACK_STRINGS_ENABLED" == "true" ]]; then
                    KEYBOARD_IDENTITY_STRINGS_PROFILE="jp_106"
                fi
            fi
        fi
        if [[ -z "${HIDLOOM_WINDOWS_IME_CUSTOM_HID:-}" ]]; then
            WINDOWS_IME_CUSTOM_HID_ENABLED="$CONFIG_WINDOWS_IME_CUSTOM_HID_ENABLED"
        fi
        if [[ -z "${HIDLOOM_USB_US_SUB_KEYBOARD:-}" ]]; then
            US_SUB_KEYBOARD_ENABLED="$CONFIG_US_SUB_KEYBOARD_ENABLED"
        fi
        if [[ -z "${HIDLOOM_US_SUB_KEYBOARD_IDENTITY_STRING:-}" ]]; then
            US_SUB_KEYBOARD_IDENTITY_STRING="$CONFIG_US_SUB_KEYBOARD_IDENTITY_STRING"
        fi
        if [[ -z "${HIDLOOM_US_KEYBOARD_IDENTITY_STRING:-}" ]]; then
            US_KEYBOARD_IDENTITY_STRING="$CONFIG_US_KEYBOARD_IDENTITY_STRING"
        fi
    else
        VENDOR_ID=$(grep -o '"vendor_id": *"[^"]*"' "$CONFIG_FILE" 2>/dev/null | head -1 | sed 's/.*"vendor_id": *"\([^"]*\)".*/\1/' || echo "$VENDOR_ID")
        PRODUCT_ID=$(grep -o '"product_id": *"[^"]*"' "$CONFIG_FILE" 2>/dev/null | head -1 | sed 's/.*"product_id": *"\([^"]*\)".*/\1/' || echo "$PRODUCT_ID")
        MANUFACTURER=$(grep -o '"manufacturer": *"[^"]*"' "$CONFIG_FILE" 2>/dev/null | sed 's/.*"manufacturer": *"\([^"]*\)".*/\1/' || echo "$MANUFACTURER")
        PRODUCT_NAME=$(grep -o '"product_name": *"[^"]*"' "$CONFIG_FILE" 2>/dev/null | sed 's/.*"product_name": *"\([^"]*\)".*/\1/' || echo "$PRODUCT_NAME")
        SERIAL_NUMBER=$(grep -o '"serial_number": *"[^"]*"' "$CONFIG_FILE" 2>/dev/null | sed 's/.*"serial_number": *"\([^"]*\)".*/\1/' || echo "$SERIAL_NUMBER")
        raw_hid_country=$(grep -o '"hid_country_code": *"[^"]*"\|"hid_country_code": *[0-9][0-9]*\|"country_code": *"[^"]*"\|"country_code": *[0-9][0-9]*' "$CONFIG_FILE" 2>/dev/null | head -1 | sed 's/.*: *"\{0,1\}\([^",}]*\)"\{0,1\}.*/\1/' || true)
        if [[ -n "$raw_hid_country" ]]; then
            HID_COUNTRY_CODE="$raw_hid_country"
        fi
        if [[ -z "${HIDLOOM_USB_KEYBOARD_IDENTITY_STRINGS:-}" ]]; then
            raw_identity_profile=$(grep -o '"usb_keyboard_identity_strings"[[:space:]]*:[[:space:]]*{[^}]*"profile"[[:space:]]*:[[:space:]]*"[^"]*"' "$CONFIG_FILE" 2>/dev/null | head -1 | sed 's/.*"profile"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/' || true)
            if [[ -n "$raw_identity_profile" ]]; then
                KEYBOARD_IDENTITY_STRINGS_PROFILE="$raw_identity_profile"
            elif [[ -z "${HIDLOOM_USB_JP_DRIVER_FALLBACK_STRINGS:-}" ]] && grep -Eq '"usb_jp_driver_fallback_strings"[[:space:]]*:[[:space:]]*\{[^}]*"enabled"[[:space:]]*:[[:space:]]*true' "$CONFIG_FILE" 2>/dev/null; then
                KEYBOARD_IDENTITY_STRINGS_PROFILE="jp_106"
            fi
        fi
        if [[ -z "${HIDLOOM_WINDOWS_IME_CUSTOM_HID:-}" ]] && grep -Eq '"windows_ime_custom_hid"[[:space:]]*:[[:space:]]*\{[^}]*"enabled"[[:space:]]*:[[:space:]]*true' "$CONFIG_FILE" 2>/dev/null; then
            WINDOWS_IME_CUSTOM_HID_ENABLED=1
        fi
        if [[ -z "${HIDLOOM_USB_US_SUB_KEYBOARD:-}" ]] && grep -Eq '"us_sub_keyboard"[[:space:]]*:[[:space:]]*\{[^}]*"enabled"[[:space:]]*:[[:space:]]*true' "$CONFIG_FILE" 2>/dev/null; then
            US_SUB_KEYBOARD_ENABLED=1
        fi
        raw_us_sub_identity=$(grep -o '"us_sub_keyboard"[[:space:]]*:[[:space:]]*{[^}]*"identity_string"[[:space:]]*:[[:space:]]*"[^"]*"' "$CONFIG_FILE" 2>/dev/null | head -1 | sed 's/.*"identity_string"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/' || true)
        if [[ -z "${HIDLOOM_US_SUB_KEYBOARD_IDENTITY_STRING:-}" && -n "$raw_us_sub_identity" ]]; then
            US_SUB_KEYBOARD_IDENTITY_STRING="$raw_us_sub_identity"
        fi
        raw_us_identity=$(grep -o '"identity_string": *"[^"]*"' "$CONFIG_FILE" 2>/dev/null | head -1 | sed 's/.*"identity_string": *"\([^"]*\)".*/\1/' || true)
        if [[ -z "${HIDLOOM_US_KEYBOARD_IDENTITY_STRING:-}" && -n "$raw_us_identity" ]]; then
            US_KEYBOARD_IDENTITY_STRING="$raw_us_identity"
        fi
    fi
else
    echo "Warning: config not found; using defaults: $CONFIG_FILE"
fi

parse_u8() {
    local raw="$1"
    local value
    if [[ "$raw" =~ ^0[xX][0-9a-fA-F]+$ ]]; then
        value=$((16#${raw:2}))
    elif [[ "$raw" =~ ^[0-9]+$ ]]; then
        value=$((10#$raw))
    else
        echo "Error: invalid HID country code: $raw" >&2
        exit 1
    fi
    if (( value < 0 || value > 255 )); then
        echo "Error: HID country code out of range 0..255: $raw" >&2
        exit 1
    fi
    echo "$value"
}

parse_u16() {
    local name="$1"
    local raw="$2"
    local value
    if [[ "$raw" =~ ^0[xX][0-9a-fA-F]+$ ]]; then
        value=$((16#${raw:2}))
    elif [[ "$raw" =~ ^[0-9]+$ ]]; then
        value=$((10#$raw))
    else
        echo "Error: invalid ${name}: $raw" >&2
        exit 1
    fi
    if (( value < 0 || value > 65535 )); then
        echo "Error: ${name} out of range 0..65535: $raw" >&2
        exit 1
    fi
    printf '0x%04x\n' "$value"
}

parse_bool() {
    local raw
    raw="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
    case "$raw" in
        1|true|yes|on|enabled)
            echo 1
            ;;
        0|false|no|off|disabled|"")
            echo 0
            ;;
        *)
            echo "Error: invalid boolean value: $1" >&2
            exit 1
            ;;
    esac
}

if [[ -n "${HIDLOOM_USB_VENDOR_ID:-}" ]]; then
    VENDOR_ID="$HIDLOOM_USB_VENDOR_ID"
fi
if [[ -n "${HIDLOOM_USB_PRODUCT_ID:-}" ]]; then
    PRODUCT_ID="$HIDLOOM_USB_PRODUCT_ID"
fi
if [[ -n "${HIDLOOM_USB_MANUFACTURER:-}" ]]; then
    MANUFACTURER="$HIDLOOM_USB_MANUFACTURER"
fi
if [[ -n "${HIDLOOM_USB_PRODUCT_NAME:-}" ]]; then
    PRODUCT_NAME="$HIDLOOM_USB_PRODUCT_NAME"
fi
if [[ -n "${HIDLOOM_USB_SERIAL:-}" ]]; then
    SERIAL_NUMBER="$HIDLOOM_USB_SERIAL"
fi
if [[ -n "${HIDLOOM_USB_HID_COUNTRY_CODE:-}" ]]; then
    HID_COUNTRY_CODE="$HIDLOOM_USB_HID_COUNTRY_CODE"
fi

# Vial may display the USB product string when no Vial definition name is shown.
MANUFACTURER="${MANUFACTURER//__HOSTNAME__/$NODE_NAME}"
PRODUCT_NAME="${PRODUCT_NAME//__HOSTNAME__/$NODE_NAME}"
SERIAL_NUMBER="${SERIAL_NUMBER//__HOSTNAME__/$NODE_NAME}"
if [[ -n "${HIDLOOM_USB_SERIAL_SUFFIX:-}" ]]; then
    SERIAL_NUMBER="${SERIAL_NUMBER}:${HIDLOOM_USB_SERIAL_SUFFIX}"
fi

VENDOR_ID="$(parse_u16 "USB vendor ID" "$VENDOR_ID")"
PRODUCT_ID="$(parse_u16 "USB product ID" "$PRODUCT_ID")"
HID_COUNTRY_CODE="$(parse_u8 "$HID_COUNTRY_CODE")"
if [[ -n "${HIDLOOM_USB_JP_DRIVER_FALLBACK_STRINGS:-}" ]] && [[ -z "${HIDLOOM_USB_KEYBOARD_IDENTITY_STRINGS:-}" ]]; then
    if [[ "$(parse_bool "$HIDLOOM_USB_JP_DRIVER_FALLBACK_STRINGS")" -eq 1 ]]; then
        KEYBOARD_IDENTITY_STRINGS_PROFILE="jp_106"
    fi
fi
WINDOWS_IME_CUSTOM_HID_ENABLED="$(parse_bool "$WINDOWS_IME_CUSTOM_HID_ENABLED")"
KEYBOARD_ONLY_TEST_ENABLED="$(parse_bool "$KEYBOARD_ONLY_TEST_ENABLED")"
US_SUB_KEYBOARD_ENABLED="$(parse_bool "$US_SUB_KEYBOARD_ENABLED")"
HID_INTERFACE_STRINGS_ENABLED="$(parse_bool "$HID_INTERFACE_STRINGS_ENABLED")"

case "$KEYBOARD_IDENTITY_STRINGS_PROFILE" in
    default|"")
        KEYBOARD_IDENTITY_STRINGS_PROFILE="default"
        PRODUCT_NAME_JA="$PRODUCT_NAME"
        ;;
    us_101|101_us|us|US)
        KEYBOARD_IDENTITY_STRINGS_PROFILE="us_101"
        PRODUCT_NAME="${NODE_NAME} 101 US Keyboard"
        PRODUCT_NAME_JA="${NODE_NAME} 101英語キーボード"
        ;;
    jp_106|106_jp|jp|JP|jis|JIS)
        KEYBOARD_IDENTITY_STRINGS_PROFILE="jp_106"
        PRODUCT_NAME="${NODE_NAME} 106 JP Keyboard"
        PRODUCT_NAME_JA="${NODE_NAME} 106日本語キーボード"
        ;;
    *)
        echo "Error: invalid USB keyboard identity strings profile: $KEYBOARD_IDENTITY_STRINGS_PROFILE" >&2
        exit 1
        ;;
esac

COMPOSITE_PRODUCT_NAME="$PRODUCT_NAME"

echo "Using USB descriptor:"
echo "  Vendor ID:    $VENDOR_ID"
echo "  Product ID:   $PRODUCT_ID"
echo "  Manufacturer: $MANUFACTURER"
echo "  Product:      $PRODUCT_NAME"
echo "  Serial:       $SERIAL_NUMBER"
echo "  HID Country:  $HID_COUNTRY_CODE"
echo "  ID Strings:   $KEYBOARD_IDENTITY_STRINGS_PROFILE"
echo "  KBD only:     $KEYBOARD_ONLY_TEST_ENABLED"
echo "  US sub KBD:   $US_SUB_KEYBOARD_ENABLED"
echo "  Win IME HID:  $WINDOWS_IME_CUSTOM_HID_ENABLED"
echo "  HID if names: $HID_INTERFACE_STRINGS_ENABLED"
echo "  US identity:  $US_KEYBOARD_IDENTITY_STRING"
echo "  US sub id:    $US_SUB_KEYBOARD_IDENTITY_STRING"

apply_hid_country_code() {
    local function_dir="$1"
    local function_name="$2"
    local attr=""

    if [[ -e "$function_dir/country_code" ]]; then
        attr="$function_dir/country_code"
    elif [[ -e "$function_dir/bCountryCode" ]]; then
        attr="$function_dir/bCountryCode"
    fi

    if [[ -n "$attr" ]]; then
        echo "$HID_COUNTRY_CODE" > "$attr"
        echo "  ${function_name}: HID country code set to $HID_COUNTRY_CODE"
    elif [[ "$HID_COUNTRY_CODE" != "0" ]]; then
        echo "Warning: ${function_name} does not expose a configfs HID country code attribute; requested HID country code $HID_COUNTRY_CODE was not applied" >&2
    fi
}

preflight_extra_hid_functions() {
    local requested_extra=0
    if [[ "$US_SUB_KEYBOARD_ENABLED" -eq 1 ]]; then
        requested_extra=$((requested_extra + 1))
    fi
    if [[ "$WINDOWS_IME_CUSTOM_HID_ENABLED" -eq 1 ]]; then
        requested_extra=$((requested_extra + 1))
    fi
    if [[ "$requested_extra" -eq 0 ]]; then
        return
    fi
    if [[ ! -d "$GADGET_NAME" ]]; then
        return
    fi
    local existing_extra=0
    if [[ "$US_SUB_KEYBOARD_ENABLED" -eq 1 && -d "$GADGET_NAME/functions/hid.usb2" ]]; then
        existing_extra=$((existing_extra + 1))
    fi
    if [[ "$WINDOWS_IME_CUSTOM_HID_ENABLED" -eq 1 && -d "$GADGET_NAME/functions/hid.usb4" ]]; then
        existing_extra=$((existing_extra + 1))
    fi
    local probe_count=$((requested_extra - existing_extra))
    if (( probe_count <= 0 )); then
        return
    fi

    local probe_dirs=()
    local err_file
    err_file="$(mktemp)"
    local index
    for index in $(seq 1 "$probe_count"); do
        local probe_dir="$GADGET_NAME/functions/hid.hidloom_probe_$index"
        if ! mkdir "$probe_dir" 2>"$err_file"; then
            break
        fi
        probe_dirs+=("$probe_dir")
    done
    if [[ "${#probe_dirs[@]}" -eq "$probe_count" ]]; then
        local dir
        for dir in "${probe_dirs[@]}"; do
            rmdir "$dir" 2>/dev/null || true
        done
        rm -f "$err_file"
        return
    fi

    local dir
    for dir in "${probe_dirs[@]}"; do
        rmdir "$dir" 2>/dev/null || true
    done
    local err
    err="$(cat "$err_file" 2>/dev/null || true)"
    rm -f "$err_file"
    echo "Error: optional HID functions were requested, but this kernel refused the additional HID function count." >&2
    echo "       Existing USB gadget was left untouched." >&2
    if [[ -n "$err" ]]; then
        echo "       Probe error: $err" >&2
    fi
    echo "       Disable US sub keyboard or Windows IME custom HID on endpoint-limited devices." >&2
    exit 1
}

apply_hid_interface_strings() {
    local function_dir="$1"
    local function_name="$2"
    local identity="$3"
    local lang

    if [[ "$HID_INTERFACE_STRINGS_ENABLED" -ne 1 ]]; then
        return
    fi

    if [[ -z "$identity" ]]; then
        return
    fi

    for lang in 0x409 0x411; do
        if mkdir -p "$function_dir/strings/$lang" 2>/dev/null; then
            if ! printf '%s\n' "$identity" > "$function_dir/strings/$lang/interface" 2>/dev/null; then
                echo "Warning: ${function_name} does not expose an interface string for ${lang}; ${identity} was not applied" >&2
            fi
        else
            echo "Warning: ${function_name} does not accept interface strings for ${lang}; ${identity} was not applied" >&2
        fi
    done
}

cd /sys/kernel/config/usb_gadget/

preflight_extra_hid_functions

if [[ -d "$GADGET_NAME" ]]; then
    echo "Removing existing gadget: $GADGET_NAME"
    if [[ -f "$GADGET_NAME/UDC" ]]; then
        echo "" > "$GADGET_NAME/UDC" 2>/dev/null || true
    fi

    for fn in hid.usb0 hid.usb1 hid.usb2 hid.usb3 hid.usb4; do
        rm -f "$GADGET_NAME/configs/c.1/$fn" 2>/dev/null || true
    done

    rmdir "$GADGET_NAME/configs/c.1/strings/0x411" 2>/dev/null || true
    rmdir "$GADGET_NAME/configs/c.1/strings/0x409" 2>/dev/null || true
    rmdir "$GADGET_NAME/configs/c.1/strings/0x411" 2>/dev/null || true
    rmdir "$GADGET_NAME/configs/c.1" 2>/dev/null || true
    rmdir "$GADGET_NAME/configs" 2>/dev/null || true

    for fn in hid.usb0 hid.usb1 hid.usb2 hid.usb3 hid.usb4; do
        rmdir "$GADGET_NAME/functions/$fn" 2>/dev/null || true
    done

    rmdir "$GADGET_NAME/functions" 2>/dev/null || true
    rmdir "$GADGET_NAME/strings/0x411" 2>/dev/null || true
    rmdir "$GADGET_NAME/strings/0x409" 2>/dev/null || true
    rmdir "$GADGET_NAME/strings/0x411" 2>/dev/null || true
    rmdir "$GADGET_NAME/strings" 2>/dev/null || true
    rmdir "$GADGET_NAME" 2>/dev/null || true
fi

echo "Creating gadget: $GADGET_NAME"
mkdir -p "$GADGET_NAME"
cd "$GADGET_NAME"

echo "$VENDOR_ID" > idVendor
echo "$PRODUCT_ID" > idProduct
echo 0x0100 > bcdDevice
echo 0x0200 > bcdUSB

mkdir -p strings/0x409
echo "$SERIAL_NUMBER" > strings/0x409/serialnumber
echo "$MANUFACTURER" > strings/0x409/manufacturer
echo "$PRODUCT_NAME" > strings/0x409/product
mkdir -p strings/0x411
echo "$SERIAL_NUMBER" > strings/0x411/serialnumber
echo "$MANUFACTURER" > strings/0x411/manufacturer
echo "$PRODUCT_NAME_JA" > strings/0x411/product

# /dev/hidg0: keyboard + mouse + consumer control multi-report, or
# keyboard-only test mode for Windows keyboard.inf identity experiments.
mkdir -p functions/hid.usb0
cd functions/hid.usb0
echo 0 > protocol
echo 0 > subclass
echo 9 > report_length
apply_hid_country_code "$(pwd)" "hid.usb0"
if [[ "$KEYBOARD_ONLY_TEST_ENABLED" -eq 1 ]]; then
    echo -ne '\x05\x01\x09\x06\xA1\x01\x85\x01\x05\x07\x19\xE0\x29\xE7\x15\x00\x25\x01\x75\x01\x95\x08\x81\x02\x95\x01\x75\x08\x81\x03\x95\x06\x75\x08\x15\x00\x26\xFF\x00\x05\x07\x19\x00\x2A\xFF\x00\x81\x00\x05\x08\x19\x01\x29\x05\x15\x00\x25\x01\x75\x01\x95\x05\x91\x02\x75\x03\x95\x01\x91\x03\xC0' > report_desc
else
    echo -ne '\x05\x01\x09\x06\xA1\x01\x85\x01\x05\x07\x19\xE0\x29\xE7\x15\x00\x25\x01\x75\x01\x95\x08\x81\x02\x95\x01\x75\x08\x81\x03\x95\x06\x75\x08\x15\x00\x26\xFF\x00\x05\x07\x19\x00\x2A\xFF\x00\x81\x00\x05\x08\x19\x01\x29\x05\x15\x00\x25\x01\x75\x01\x95\x05\x91\x02\x75\x03\x95\x01\x91\x03\xC0\x05\x01\x09\x02\xA1\x01\x85\x02\x09\x01\xA1\x00\x05\x09\x19\x01\x29\x05\x15\x00\x25\x01\x75\x01\x95\x05\x81\x02\x75\x03\x95\x01\x81\x03\x05\x01\x09\x30\x09\x31\x09\x38\x15\x81\x25\x7F\x75\x08\x95\x03\x81\x06\xC0\xC0\x05\x0C\x09\x01\xA1\x01\x85\x03\x15\x00\x26\xFF\x03\x19\x00\x2A\xFF\x03\x75\x10\x95\x01\x81\x00\xC0' > report_desc
fi
if [[ "$US_SUB_KEYBOARD_ENABLED" -eq 1 ]]; then
    apply_hid_interface_strings "$(pwd)" "hid.usb0" "$US_KEYBOARD_IDENTITY_STRING"
fi
cd ../..

# /dev/hidg1: Raw HID / Vial
mkdir -p functions/hid.usb1
cd functions/hid.usb1
echo 0 > protocol
echo 0 > subclass
echo 32 > report_length
echo -ne '\x06\x60\xff\x09\x61\xa1\x01\x15\x00\x26\xff\x00\x75\x08\x95\x20\x09\x62\x81\x02\x95\x20\x09\x63\x91\x02\xc0' > report_desc
cd ../..

if [[ "$US_SUB_KEYBOARD_ENABLED" -eq 1 ]]; then
    # /dev/hidg2: optional US sub keyboard.  This is a real Keyboard/Keypad
    # HID interface so Windows can manage it separately from the JIS main path.
    mkdir -p functions/hid.usb2
    cd functions/hid.usb2
    echo 1 > protocol
    echo 1 > subclass
    echo "$US_SUB_KEYBOARD_REPORT_LENGTH" > report_length
    apply_hid_country_code "$(pwd)" "hid.usb2"
    echo -ne "$US_SUB_KEYBOARD_REPORT_DESC" > report_desc
    apply_hid_interface_strings "$(pwd)" "hid.usb2" "$US_SUB_KEYBOARD_IDENTITY_STRING"
    cd ../..
fi

if [[ "$WINDOWS_IME_CUSTOM_HID_ENABLED" -eq 1 ]]; then
    # Optional vendor-defined Windows IME custom HID report.
    mkdir -p functions/hid.usb4
    cd functions/hid.usb4
    echo 0 > protocol
    echo 0 > subclass
    echo "$WINDOWS_IME_CUSTOM_HID_REPORT_LENGTH" > report_length
    echo -ne "$WINDOWS_IME_CUSTOM_HID_REPORT_DESC" > report_desc
    cd ../..
fi

mkdir -p configs/c.1/strings/0x409
mkdir -p configs/c.1/strings/0x411
case "$KEYBOARD_IDENTITY_STRINGS_PROFILE" in
    us_101)
        CONFIG_KEYBOARD_LABEL="101 US Keyboard"
        CONFIG_KEYBOARD_LABEL_JA="101英語キーボード"
        ;;
    jp_106)
        CONFIG_KEYBOARD_LABEL="106 JP Keyboard"
        CONFIG_KEYBOARD_LABEL_JA="106日本語キーボード"
        ;;
    *)
        CONFIG_KEYBOARD_LABEL="HID Keyboard"
        CONFIG_KEYBOARD_LABEL_JA="HIDキーボード"
        ;;
esac

CONFIG_EXTRA_LABEL=""
if [[ "$KEYBOARD_ONLY_TEST_ENABLED" -eq 1 ]]; then
    CONFIG_EXTRA_LABEL="+KeyboardOnlyTest"
elif [[ "$US_SUB_KEYBOARD_ENABLED" -eq 1 && "$WINDOWS_IME_CUSTOM_HID_ENABLED" -eq 1 ]]; then
    CONFIG_EXTRA_LABEL="+UsSubKeyboard+WinImeCustom"
elif [[ "$US_SUB_KEYBOARD_ENABLED" -eq 1 ]]; then
    CONFIG_EXTRA_LABEL="+UsSubKeyboard"
elif [[ "$WINDOWS_IME_CUSTOM_HID_ENABLED" -eq 1 ]]; then
    CONFIG_EXTRA_LABEL="+WinImeCustom"
fi
echo "Config 1: ${CONFIG_KEYBOARD_LABEL}+Mouse+Consumer+RawHID${CONFIG_EXTRA_LABEL}" > configs/c.1/strings/0x409/configuration
echo "Config 1: ${CONFIG_KEYBOARD_LABEL_JA}+Mouse+Consumer+RawHID${CONFIG_EXTRA_LABEL}" > configs/c.1/strings/0x411/configuration
echo 250 > configs/c.1/MaxPower

ln -s functions/hid.usb0 configs/c.1/
ln -s functions/hid.usb1 configs/c.1/
if [[ "$US_SUB_KEYBOARD_ENABLED" -eq 1 ]]; then
    ln -s functions/hid.usb2 configs/c.1/
fi
if [[ "$WINDOWS_IME_CUSTOM_HID_ENABLED" -eq 1 ]]; then
    ln -s functions/hid.usb4 configs/c.1/
fi

UDC_NAME=$(ls /sys/class/udc/ | head -1)
if [[ -z "$UDC_NAME" ]]; then
    echo "Error: no UDC found" >&2
    exit 1
fi

echo "$UDC_NAME" > UDC
echo "USB HID gadget configured"
echo "  Product: $COMPOSITE_PRODUCT_NAME"
echo "  UDC:     $UDC_NAME"

expected_hidg=(/dev/hidg0 /dev/hidg1)
if [[ "$US_SUB_KEYBOARD_ENABLED" -eq 1 ]]; then
    expected_hidg+=(/dev/hidg2)
fi
if [[ "$WINDOWS_IME_CUSTOM_HID_ENABLED" -eq 1 ]]; then
    expected_hidg+=(/dev/hidg4)
fi

for _ in {1..20}; do
    all_ready=1
    for dev in "${expected_hidg[@]}"; do
        if [[ ! -c "$dev" ]]; then
            all_ready=0
            break
        fi
    done
    if [[ "$all_ready" -eq 1 ]]; then
        break
    fi
    sleep 0.05
done

for dev in "${expected_hidg[@]}"; do
    if [[ -c "$dev" ]]; then
        chgrp input "$dev" 2>/dev/null || true
        chmod 0660 "$dev" 2>/dev/null || true
        ls -l "$dev"
    else
        echo "Warning: expected HID device did not appear: $dev" >&2
    fi
done
