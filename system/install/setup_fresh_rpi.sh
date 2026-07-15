#!/bin/bash
# Fresh Raspberry Pi OS bootstrap for HIDloom.
#
# Usage:
#   sudo ./setup_fresh_rpi.sh
#   sudo ./setup_fresh_rpi.sh --prepare-only
#   sudo ./setup_fresh_rpi.sh --no-reboot
#   sudo ./setup_fresh_rpi.sh --no-bluetooth
#   sudo ./setup_fresh_rpi.sh --no-matrixd
#   sudo ./setup_fresh_rpi.sh --no-peripherals
#   sudo ./setup_fresh_rpi.sh --touch-panel-only
#   sudo ./setup_fresh_rpi.sh --touch-panel-only --touch-panel-profile osoyoo-4.3
#   sudo ./setup_fresh_rpi.sh --board-version ver0.1 --prototype

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BOOT_CONFIG=""
PREPARE_ONLY=0
NO_REBOOT=0
BOARD_VERSION="ver1.0"
BOARD_VERSION_EXPLICIT=0
BOARD_PROTOTYPE=0
NO_BLUETOOTH=0
NO_MATRIXD=0
NO_PERIPHERALS=0
TOUCH_PANEL_PROFILE="auto"

usage() {
    cat <<'EOF'
Usage: setup_fresh_rpi.sh [OPTIONS]

Prepare Raspberry Pi OS for HIDloom or perform the legacy checkout bootstrap.

Options:
  --prepare-only          Configure the OS without building project binaries,
                          initializing runtime state, or installing systemd units
  --no-reboot             Do not reboot when setup completes
  --no-bluetooth          Disable Bluetooth in boot and runtime policy
  --no-matrixd            Use the legacy Python input path without matrixd
  --no-peripherals        Skip OLED/LED Python packages and peripheral services
  --touch-panel-only      Select touch-panel-only legacy checkout setup
  --touch-panel-profile P Select the touch-panel profile
  --board-version VERSION Select a board profile for legacy checkout setup
  --prototype             Allow a prototype board profile
  -h, --help              Show this help and exit

The standard package-first fresh install uses --prepare-only. Project binaries
must be cross-built on the x86_64 build host and installed as split Debian
packages after the preparation reboot.
EOF
}

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        --prepare-only)
            PREPARE_ONLY=1
            shift
            ;;
        --no-reboot)
            NO_REBOOT=1
            shift
            ;;
        --no-bluetooth)
            NO_BLUETOOTH=1
            shift
            ;;
        --no-matrixd)
            NO_MATRIXD=1
            shift
            ;;
        --no-peripherals)
            NO_PERIPHERALS=1
            shift
            ;;
        --touch-panel-only)
            NO_BLUETOOTH=1
            NO_MATRIXD=1
            NO_PERIPHERALS=1
            shift
            ;;
        --touch-panel-profile)
            TOUCH_PANEL_PROFILE="${2:-}"
            if [[ -z "$TOUCH_PANEL_PROFILE" ]]; then
                echo "--touch-panel-profile requires a value" >&2
                exit 1
            fi
            shift 2
            ;;
        --board-version)
            BOARD_VERSION="${2:-}"
            if [[ -z "$BOARD_VERSION" ]]; then
                echo "--board-version requires a value" >&2
                exit 1
            fi
            BOARD_VERSION_EXPLICIT=1
            shift 2
            ;;
        --prototype)
            BOARD_PROTOTYPE=1
            shift
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

log()  { printf '\n==> %s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }

systemctl_disable_now() {
    local timeout_sec="${HIDLOOM_SYSTEMCTL_TIMEOUT_SEC:-30}"
    if command -v timeout >/dev/null 2>&1; then
        timeout "${timeout_sec}s" systemctl disable --now "$@"
    else
        systemctl disable --now "$@"
    fi
}

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        echo "This script must be run as root: sudo $0" >&2
        exit 1
    fi
}

detect_boot_config() {
    if [[ -f /boot/firmware/config.txt ]]; then
        BOOT_CONFIG=/boot/firmware/config.txt
    elif [[ -f /boot/config.txt ]]; then
        BOOT_CONFIG=/boot/config.txt
    else
        echo "Could not find Raspberry Pi boot config.txt" >&2
        exit 1
    fi
}

detect_boot_cmdline() {
    if [[ -f /boot/firmware/cmdline.txt ]]; then
        BOOT_CMDLINE=/boot/firmware/cmdline.txt
    elif [[ -f /boot/cmdline.txt ]]; then
        BOOT_CMDLINE=/boot/cmdline.txt
    else
        echo "Could not find Raspberry Pi cmdline.txt" >&2
        exit 1
    fi
}

ensure_line() {
    local file="$1"
    local line="$2"
    touch "$file"
    grep -qxF "$line" "$file" || echo "$line" >> "$file"
}

comment_line() {
    local file="$1"
    local line="$2"
    if grep -qxF "$line" "$file"; then
        sed -i "s|^${line}$|#${line}|" "$file"
    fi
}

set_prefixed_line() {
    local file="$1"
    local prefix="$2"
    local line="$3"
    touch "$file"
    if grep -qE "^#?${prefix}" "$file"; then
        sed -i -E "0,/^#?${prefix}.*/s//${line}/" "$file"
    else
        echo "$line" >> "$file"
    fi
}

ensure_cmdline_csv_values() {
    local file="$1"
    local key="$2"
    local values_csv="$3"
    local current line new value

    touch "$file"
    line="$(tr '\n' ' ' <"$file" | sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//')"
    current="$(printf '%s\n' "$line" | tr ' ' '\n' | awk -F= -v key="$key" '$1 == key {print $2; exit}')"
    new="$current"
    IFS=',' read -r -a values <<<"$values_csv"
    for value in "${values[@]}"; do
        case ",$new," in
            *",$value,"*) ;;
            *) new="${new:+$new,}$value" ;;
        esac
    done
    if [[ -z "$current" ]]; then
        printf '%s %s=%s\n' "$line" "$key" "$new" >"$file"
    else
        printf '%s\n' "$line" | sed -E "s/(^| )${key}=[^ ]*/ ${key}=${new}/; s/^ //" >"$file"
    fi
}

remove_cmdline_token() {
    local file="$1"
    local token="$2"
    local line

    touch "$file"
    line="$(tr '\n' ' ' <"$file" | sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//')"
    printf '%s\n' "$line" | tr ' ' '\n' | awk -v token="$token" '$0 != token' | paste -sd' ' - >"$file"
}

install_apt_packages() {
    log "Installing apt packages"
    local packages=(
        build-essential
        fbterm
        fonts-dejavu-mono
        fonts-noto-cjk
        i2c-tools
        jq
        python3
        python3-dev
        python3-pip
        rfkill
        socat
        wireless-tools
    )
    if [[ "$PREPARE_ONLY" -eq 0 ]]; then
        packages+=(
            cargo
            git
            python3-aiohttp
            python3-dbus-next
            python3-numpy
            python3-opencv
            python3-pil
            python3-venv
            rustc
        )
    fi
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y "${packages[@]}"
}

install_python_packages() {
    if [[ "$NO_PERIPHERALS" -eq 1 ]]; then
        log "Skipping peripheral Python packages"
        return
    fi

    log "Installing Python packages not provided by the project"
    python3 -m pip install --break-system-packages --upgrade \
        luma.oled \
        rpi_ws281x
}

configure_boot_and_modules() {
    log "Configuring Raspberry Pi interfaces and kernel modules"

    if command -v raspi-config >/dev/null 2>&1; then
        raspi-config nonint do_i2c 0 || warn "raspi-config failed to enable I2C; falling back to config.txt"
    fi

    ensure_line "$BOOT_CONFIG" "dtparam=i2c_arm=on"
    ensure_line "$BOOT_CONFIG" "dtparam=spi=on"
    set_prefixed_line "$BOOT_CONFIG" "dtparam=audio=" "dtparam=audio=off"
    set_prefixed_line "$BOOT_CONFIG" "dtoverlay=vc4-kms-v3d" "dtoverlay=vc4-kms-v3d,noaudio"
    set_prefixed_line "$BOOT_CONFIG" "camera_auto_detect=" "camera_auto_detect=0"
    set_prefixed_line "$BOOT_CONFIG" "display_auto_detect=" "display_auto_detect=0"
    set_prefixed_line "$BOOT_CONFIG" "disable_splash=" "disable_splash=1"
    ensure_cmdline_csv_values "$BOOT_CMDLINE" "module_blacklist" "snd_bcm2835,snd_soc_hdmi_codec"
    remove_cmdline_token "$BOOT_CMDLINE" "modules-load=dwc2,libcomposite"
    ensure_line "$BOOT_CONFIG" "enable_uart=1"
    comment_line "$BOOT_CONFIG" "dtoverlay=dwc2,dr_mode=host"
    ensure_line "$BOOT_CONFIG" "dtoverlay=dwc2,dr_mode=peripheral"
    ensure_line "$BOOT_CONFIG" "dtoverlay=i2c3,pins_4_5"
    ensure_line "$BOOT_CONFIG" "dtoverlay=pwm,pin=12,func=4"
    if [[ "$NO_BLUETOOTH" -eq 1 ]]; then
        ensure_line "$BOOT_CONFIG" "dtoverlay=disable-bt"
    fi

    mkdir -p /etc/modules-load.d
    cat >/etc/modules-load.d/hidloom.conf <<'EOF'
i2c-dev
dwc2
libcomposite
uinput
EOF
    cat >/etc/modprobe.d/hidloom-no-audio.conf <<'EOF'
# The keyboard controller does not use ALSA. Keep analog and HDMI audio
# providers from creating sound cards during boot.
blacklist snd_bcm2835
blacklist snd_soc_hdmi_codec
install snd_bcm2835 /bin/false
install snd_soc_hdmi_codec /bin/false
EOF
}

configure_device_permissions() {
    log "Configuring device permissions"

    cat >/etc/udev/rules.d/99-hidg.rules <<'EOF'
SUBSYSTEM=="hidg", KERNEL=="hidg*", GROUP="input", MODE="0660"
EOF

    if [[ -n "${SUDO_USER:-}" ]] && id "$SUDO_USER" >/dev/null 2>&1; then
        usermod -aG input "$SUDO_USER" || warn "Failed to add $SUDO_USER to input group"
    fi

    udevadm control --reload-rules || warn "Failed to reload udev rules"
    udevadm trigger --subsystem-match=hidg || true
}

configure_local_console_font() {
    if [[ -z "${SUDO_USER:-}" ]] || ! id "$SUDO_USER" >/dev/null 2>&1; then
        warn "Skipping local console fbterm profile setup; SUDO_USER is not available"
        return
    fi

    log "Configuring local UTF-8 console font for $SUDO_USER"

    local user_home profile tmp
    user_home="$(getent passwd "$SUDO_USER" | cut -d: -f6)"
    if [[ -z "$user_home" || ! -d "$user_home" ]]; then
        warn "Skipping local console fbterm profile setup; home directory not found for $SUDO_USER"
        return
    fi

    profile="$user_home/.profile"
    tmp="$(mktemp)"
    touch "$profile"
    awk '
        BEGIN { skip = 0 }
        /^# HIDLOOM FBTERM START$/ { skip = 1; next }
        /^# HIDLOOM FBTERM END$/ { skip = 0; next }
        skip == 0 { print }
    ' "$profile" > "$tmp"
    cat >> "$tmp" <<'EOF'

# HIDLOOM FBTERM START
# Auto-start fbterm for local UTF-8 CJK console on virtual terminals.
# Keep a Latin monospace font first so ASCII is not stretched by CJK cell metrics;
# Japanese glyphs fall back to Noto CJK.
if [ -z "${SSH_CONNECTION:-}" ] && [ -z "${FBTERM:-}" ] && [ "${TERM:-}" = "linux" ] && [ -x /usr/bin/fbterm ] && tty | grep -Eq "^/dev/tty[1-6]$"; then
    exec /usr/bin/fbterm --font-names="DejaVu Sans Mono,Noto Sans Mono CJK JP,Noto Sans CJK JP,monospace" --font-size=28
fi
# HIDLOOM FBTERM END
EOF
    cat "$tmp" > "$profile"
    rm -f "$tmp"
    chown "$SUDO_USER:$SUDO_USER" "$profile"

    local autologin_dropin="/etc/systemd/system/getty@tty1.service.d/autologin.conf"
    if [[ -f "$autologin_dropin" ]] && grep -q -- "--autologin" "$autologin_dropin"; then
        local backup="${autologin_dropin}.hidloom-before-fbterm"
        warn "Disabling tty1 autologin drop-in for fbterm local console stability: $autologin_dropin"
        cp -a "$autologin_dropin" "$backup"
        rm -f "$autologin_dropin"
        rmdir /etc/systemd/system/getty@tty1.service.d 2>/dev/null || true
        systemctl daemon-reload || warn "Failed to reload systemd after disabling tty1 autologin"
        systemctl reset-failed getty@tty1.service 2>/dev/null || true
    fi
}

build_matrixd() {
    if [[ "$NO_MATRIXD" -eq 1 ]]; then
        log "Skipping matrixd build"
        return
    fi

    log "Building matrixd"
    make -C "$REPO_ROOT/daemon/matrixd"
}

build_c_helpers() {
    log "Building C helper commands"
    chmod +x "$REPO_ROOT/tools/hidloom_send/build.sh"
    "$REPO_ROOT/tools/hidloom_send/build.sh"
    chmod +x "$REPO_ROOT/tools/hidloom_usb_gadget_fast/build.sh"
    "$REPO_ROOT/tools/hidloom_usb_gadget_fast/build.sh"
    chmod +x "$REPO_ROOT/tools/hidloom_hidd/build.sh"
    "$REPO_ROOT/tools/hidloom_hidd/build.sh"
    chmod +x "$REPO_ROOT/tools/hidloom_uidd/build.sh"
    "$REPO_ROOT/tools/hidloom_uidd/build.sh"
    chmod +x "$REPO_ROOT/tools/hidloom_outputd/build.sh"
    "$REPO_ROOT/tools/hidloom_outputd/build.sh"
    chmod +x "$REPO_ROOT/tools/hidloom_logicd_core/build.sh"
    "$REPO_ROOT/tools/hidloom_logicd_core/build.sh"
}

compile_python_bytecode() {
    log "Precompiling Python bytecode"
    python3 -m compileall -q \
        "$REPO_ROOT/daemon" \
        "$REPO_ROOT/hidloom_paths.py" \
        "$REPO_ROOT/script_metadata.py" \
        "$REPO_ROOT/vialrgb_effects.py" || warn "Python bytecode precompile failed"
}

restore_repo_user_ownership() {
    if [[ -z "${SUDO_USER:-}" ]] || ! id "$SUDO_USER" >/dev/null 2>&1; then
        return
    fi

    log "Restoring repository build artifact ownership for $SUDO_USER"
    chown -R "$SUDO_USER:$SUDO_USER" \
        "$REPO_ROOT/bin" \
        "$REPO_ROOT/daemon/matrixd/matrixd" \
        "$REPO_ROOT/tools/hidloom_send/.build" \
        "$REPO_ROOT/tools/hidloom_usb_gadget_fast/.build" \
        "$REPO_ROOT/tools/hidloom_hidd/target" \
        "$REPO_ROOT/tools/hidloom_uidd/target" \
        "$REPO_ROOT/tools/hidloom_outputd/target" \
        "$REPO_ROOT/tools/hidloom_logicd_core/target" 2>/dev/null || true
    find "$REPO_ROOT/daemon" -type d -name __pycache__ -prune \
        -exec chown -R "$SUDO_USER:$SUDO_USER" {} + 2>/dev/null || true
    if [[ -d "$REPO_ROOT/__pycache__" ]]; then
        chown -R "$SUDO_USER:$SUDO_USER" "$REPO_ROOT/__pycache__" 2>/dev/null || true
    fi
}

prepare_runtime_files() {
    log "Preparing runtime directories and scripts"
    chmod +x "$REPO_ROOT/system/install/setup_usb_gadget.sh"
    chmod +x "$REPO_ROOT/script/select_touch_panel_profile.py"
    chmod +x "$REPO_ROOT/tools/hidloom_send/build.sh"
    chmod +x "$REPO_ROOT/tools/hidloom_usb_gadget_fast/build.sh"
    chmod +x "$REPO_ROOT/tools/hidloom_hidd/build.sh"
    chmod +x "$REPO_ROOT/tools/hidloom_uidd/build.sh"
    chmod +x "$REPO_ROOT/tools/hidloom_outputd/build.sh"
    chmod +x "$REPO_ROOT/tools/hidloom_logicd_core/build.sh"
    chmod +x "$REPO_ROOT"/config/default/script/KC_SH*.sh 2>/dev/null || true

    mkdir -p /mnt/p3/script
    cp -a "$REPO_ROOT"/config/default/script/. /mnt/p3/script/
    chmod +x /mnt/p3/script/KC_SH*.sh 2>/dev/null || true
    chmod 0644 /mnt/p3/keymap.json 2>/dev/null || true
}

install_touch_panel_profile() {
    if [[ "$NO_MATRIXD" -eq 0 ]]; then
        return
    fi

    log "Installing touch panel keymap profile"
    printf '%s\n' "$TOUCH_PANEL_PROFILE" > /mnt/p3/touch_panel_profile_request
    "$REPO_ROOT/script/select_touch_panel_profile.py" \
        --repo-root "$REPO_ROOT" \
        --runtime-dir /mnt/p3 \
        --profile-file /mnt/p3/touch_panel_profile_request

    mkdir -p /etc/systemd/system/logicd.service.d
    cat >/etc/systemd/system/logicd.service.d/touch-panel-matrix.conf <<'EOF'
[Service]
Environment=LOGICD_MATRIX_ROWS=16
Environment=LOGICD_MATRIX_COLS=16
EOF
}

apply_board_profile_if_requested() {
    log "Applying board profile $BOARD_VERSION$([[ "$BOARD_VERSION_EXPLICIT" -eq 1 ]] || echo " (default)")"
    local args=(
        "$REPO_ROOT/script/apply_board_profile.py"
        "$BOARD_VERSION"
        --repo-conf
        --write-marker
        --device-name
        "$(hostname)"
        --reset-runtime-keymap
    )
    if [[ "$BOARD_PROTOTYPE" -eq 1 ]]; then
        args+=(--prototype)
    fi
    python3 "${args[@]}"
}

install_unit_from_repo() {
    local src="$1"
    local dst="/etc/systemd/system/$(basename "$src")"
    sed \
        -e "s|@HIDLOOM_REPO_ROOT@|$REPO_ROOT|g" \
        -e "s|/home/USERNAME/hidloom|$REPO_ROOT|g" \
        "$src" > "$dst"
}

install_services() {
    log "Installing systemd units"
    install_unit_from_repo "$REPO_ROOT/system/systemd/hidloom-power-shed.service"
    install_unit_from_repo "$REPO_ROOT/system/systemd/hidloom-usb-gadget.service"
    install_unit_from_repo "$REPO_ROOT/system/systemd/hidloom-touch-panel-profile.service"
    install_unit_from_repo "$REPO_ROOT/system/systemd/hidloom-bluetooth-unblock.service"
    install_unit_from_repo "$REPO_ROOT/system/systemd/i2cd.service"
    install_unit_from_repo "$REPO_ROOT/system/systemd/logicd.service"
    install_unit_from_repo "$REPO_ROOT/system/systemd/logicd-companion.service"
    install_unit_from_repo "$REPO_ROOT/system/systemd/matrixd.service"
    install_unit_from_repo "$REPO_ROOT/system/systemd/ledd.service"
    install_unit_from_repo "$REPO_ROOT/system/systemd/ledd-shutdown.service"
    install_unit_from_repo "$REPO_ROOT/system/systemd/httpd.service"
    install_unit_from_repo "$REPO_ROOT/system/systemd/viald.service"
    install_unit_from_repo "$REPO_ROOT/system/systemd/usbd.service"
    install_unit_from_repo "$REPO_ROOT/system/systemd/hidloom-hidd.service"
    install_unit_from_repo "$REPO_ROOT/system/systemd/hidloom-uidd.service"
    install_unit_from_repo "$REPO_ROOT/system/systemd/hidloom-outputd.service"
    install_unit_from_repo "$REPO_ROOT/system/systemd/hidloom-logicd-core.service"
    install_unit_from_repo "$REPO_ROOT/system/systemd/hidloom-late-services.service"
    install_unit_from_repo "$REPO_ROOT/system/systemd/hidloom-late-services.timer"
    install_unit_from_repo "$REPO_ROOT/system/systemd/hidloom-network-late.service"
    install_unit_from_repo "$REPO_ROOT/system/systemd/hidloom-network-late.timer"
    install_unit_from_repo "$REPO_ROOT/system/systemd/btd.service"

    systemctl daemon-reload
    local units=(
        hidloom-power-shed.service
        hidloom-usb-gadget.service
        hidloom-hidd.service
        hidloom-late-services.timer
        hidloom-network-late.timer
    )
    if [[ "$NO_MATRIXD" -eq 1 ]]; then
        units+=(logicd.service)
    else
        units+=(
            hidloom-uidd.service
            hidloom-outputd.service
            hidloom-logicd-core.service
            matrixd.service
            logicd-companion.service
        )
    fi
    if [[ "$NO_PERIPHERALS" -eq 0 ]]; then
        units+=(
            i2cd.service
            ledd.service
            ledd-shutdown.service
        )
    fi
    systemctl enable "${units[@]}"
    if [[ "$NO_MATRIXD" -eq 1 ]]; then
        systemctl_disable_now matrixd.service hidloom-outputd.service hidloom-uidd.service hidloom-logicd-core.service logicd-companion.service hidloom-touch-panel-profile.service hidloom-late-services.service httpd.service viald.service 2>/dev/null || true
    else
        systemctl_disable_now logicd.service hidloom-touch-panel-profile.service hidloom-late-services.service httpd.service viald.service 2>/dev/null || true
    fi
    if [[ "$NO_PERIPHERALS" -eq 1 ]]; then
        systemctl_disable_now i2cd.service ledd.service ledd-shutdown.service 2>/dev/null || true
    fi
    if [[ "$NO_BLUETOOTH" -eq 1 ]]; then
        systemctl_disable_now bluetooth.service hidloom-bluetooth-unblock.service btd.service 2>/dev/null || true
    else
        systemctl_disable_now bluetooth.service hidloom-bluetooth-unblock.service btd.service 2>/dev/null || true
    fi
    # Keep NetworkManager available for Wi-Fi recovery on fresh Raspberry Pi OS
    # images. hidloom-network-late.timer may still start it asynchronously,
    # but setup must not disable the OS-managed Wi-Fi path or hide saved
    # connection profiles from the operator.

    mkdir -p /etc/systemd/system/logicd.service.d
    cat >/etc/systemd/system/logicd.service.d/runtime-dependents.conf <<EOF
[Unit]
Wants=$([[ "$NO_MATRIXD" -eq 1 ]] && echo "dev-hidg0.device" || echo "dev-hidg0.device matrixd.service")
EOF

    if [[ -f /usr/lib/systemd/system/ssh.service ]]; then
        # Preserve the OS ssh unit while dropping only network.target ordering.
        sed \
            -e 's/^After=network.target nss-user-lookup.target auditd.service$/After=nss-user-lookup.target auditd.service/' \
            /usr/lib/systemd/system/ssh.service > /etc/systemd/system/ssh.service
        rm -f /etc/systemd/system/ssh.service.d/hidloom-no-network-order.conf
    fi
    if [[ -f /usr/lib/systemd/system/systemd-user-sessions.service ]]; then
        # User sessions must not pull late networking back into multi-user.
        sed \
            -e 's/^After=remote-fs.target nss-user-lookup.target network.target home.mount$/After=remote-fs.target nss-user-lookup.target home.mount/' \
            /usr/lib/systemd/system/systemd-user-sessions.service > /etc/systemd/system/systemd-user-sessions.service
    fi

    systemctl daemon-reload
}

configure_late_service_policy() {
    log "Configuring late-service policy"
    mkdir -p /etc/systemd/system/hidloom-late-services.service.d
    cat >/etc/systemd/system/hidloom-late-services.service.d/setup-options.conf <<EOF
[Service]
Environment=HIDLOOM_LATE_BLUETOOTH=$([[ "$NO_BLUETOOTH" -eq 1 ]] && echo 0 || echo 1)
EOF
    systemctl daemon-reload || warn "Failed to reload systemd after configuring late-service policy"
}

install_bluetooth_hid_dropins() {
    if [[ "$NO_BLUETOOTH" -eq 1 ]]; then
        log "Skipping Bluetooth HID systemd drop-ins"
        return
    fi

    log "Installing Bluetooth HID systemd drop-ins"

    mkdir -p /etc/systemd/system/btd.service.d
    cat >/etc/systemd/system/btd.service.d/hogp.conf <<'EOF'
[Service]
Environment=BTD_BACKEND=bluez
Environment=BTD_BLUEZ_ENABLE=1
Environment=BTD_GATT_ADAPTER=bluez-dbus
Environment=BTD_ADVERTISING_ADAPTER=bluez-dbus
Environment=BTD_ADVERTISING_MODE=pairing
Environment=BTD_ADVERTISING_MONITOR_INTERVAL=1
Environment=BTD_ADVERTISING_IDLE_MONITOR_INTERVAL=60
Environment=BTD_GATT_SECURITY=encrypt
Environment=BTD_PAIRING_MODE=0
Environment=BTD_PAIRING_ADAPTER=bluetoothctl
Environment=BTD_PAIRING_AGENT=DisplayYesNo
Environment=BTD_STATUS_INTERVAL=30
Environment=BTD_DISCONNECT_MONITOR_INTERVAL=2
Environment=BTD_DISCONNECT_IDLE_MONITOR_INTERVAL=60
Environment=BTD_STUCK_RECONNECT_POLLS=3
Environment=BTD_STUCK_RECONNECT_COOLDOWN=30
Environment=BTD_RECONNECT_NOTIFY_GRACE=2.0
Environment=BTD_OUTPUT_ON_CONNECT=bt
Environment=BTD_OUTPUT_ON_DISCONNECT=auto
Environment=BTD_MOUSE_COALESCE_INTERVAL=0.020
Environment=BTD_MOUSE_SMALL_COALESCE_INTERVAL=0.040
Environment=BTD_MOUSE_SMALL_COALESCE_THRESHOLD=4
Environment=BTD_MOUSE_FAST_HOLD=0.12
Environment=BTD_KEYBOARD_REPEAT_INTERVAL=0.090
EOF

    local logic_unit
    for logic_unit in logicd.service logicd-companion.service; do
        mkdir -p "/etc/systemd/system/$logic_unit.d"
        cat >"/etc/systemd/system/$logic_unit.d/bt-output.conf" <<'EOF'
[Service]
Environment=LOGICD_OUTPUTS=auto
Environment=LOGICD_AUTO_BT_FALLBACK=1
EOF
        cat >"/etc/systemd/system/$logic_unit.d/bt-pairing.conf" <<'EOF'
[Service]
Environment=BTD_PAIRING_AGENT=DisplayYesNo
Environment=BTD_PAIRING_PASSKEY_FILE=/tmp/btd_pairing_passkey.txt
Environment=BT_PAIRING_DISCOVERABLE=0
EOF
    done
}

configure_bluetooth_power() {
    if [[ "$NO_BLUETOOTH" -eq 1 ]]; then
        log "Disabling Bluetooth"

        systemctl_disable_now \
            bluetooth.service \
            btd.service \
            hidloom-bluetooth-unblock.service 2>/dev/null || true
        systemctl_disable_now hciuart.service 2>/dev/null || true

        if command -v rfkill >/dev/null 2>&1; then
            rfkill block bluetooth || warn "Failed to block Bluetooth with rfkill"
        else
            warn "rfkill command not found; Bluetooth may remain unblocked until reboot"
        fi
        return
    fi

    log "Unblocking Bluetooth"

    if command -v rfkill >/dev/null 2>&1; then
        rfkill unblock bluetooth || warn "Failed to unblock Bluetooth with rfkill"
    else
        warn "rfkill command not found; Bluetooth may remain blocked"
    fi
}

configure_systemd_watchdog() {
    log "Disabling systemd hardware watchdog for keyboard-controller reboots"

    # Some Raspberry Pi OS images enable the Broadcom hardware watchdog by
    # default. If shutdown or Wi-Fi bring-up stalls during a normal reboot, the
    # watchdog can reset the board again and look like a reboot loop. This
    # keyboard controller is normally recoverable by power cycling, so prefer a
    # quiet reboot path over automatic watchdog resets.
    mkdir -p /etc/systemd/system.conf.d
    cat >/etc/systemd/system.conf.d/90-hidloom-disable-watchdog.conf <<'EOF'
[Manager]
RuntimeWatchdogSec=off
RebootWatchdogSec=off
KExecWatchdogSec=off
EOF
}

configure_system_logging() {
    log "Configuring persistent system journal"

    # Keep previous-boot logs so reboot and Bluetooth reconnect failures can be
    # diagnosed after power cycling.
    mkdir -p /etc/systemd/journald.conf.d /var/log/journal
    cat >/etc/systemd/journald.conf.d/90-hidloom-persistent.conf <<'EOF'
[Journal]
Storage=persistent
SystemMaxUse=64M
RuntimeMaxUse=32M
EOF
}

optimize_system_services() {
    log "Disabling optional desktop/server services"

    if [[ "${HIDLOOM_KEEP_DESKTOP:-0}" == "1" ]]; then
        warn "HIDLOOM_KEEP_DESKTOP=1 set; leaving desktop-related services enabled."
        return
    fi

    # Netplan warns and regenerates noisy state when YAML files are readable by
    # non-root users. Tighten generated/default files before NetworkManager uses
    # them during subsequent boots.
    find /etc/netplan /lib/netplan -maxdepth 1 -type f -name '*.yaml' -exec chmod 600 {} + 2>/dev/null || true

    # Raspberry Pi OS desktop images start several services that are useful for
    # an interactive desktop but expensive on a 512 MB keyboard controller.
    local units=(
        accounts-daemon.service
        alsa-restore.service
        alsa-state.service
        avahi-daemon.service
        avahi-daemon.socket
        cloud-config.service
        cloud-final.service
        cloud-init-hotplugd.socket
        cloud-init-local.service
        cloud-init-main.service
        cloud-init-network.service
        cloud-init.target
        cups.path
        cups.service
        cups.socket
        glamor-test.service
        lightdm.service
        NetworkManager-wait-online.service
        nfs-blkmap.service
        plymouth-quit-wait.service
        plymouth-quit.service
        plymouth-read-write.service
        plymouth-start.service
        rp1-test.service
        rpcbind.service
        rpcbind.socket
        sound.target
        sysstat-collect.timer
        sysstat-summary.timer
        sysstat-rotate.timer
        udisks2.service
        wayvnc-control.service
    )

    local unit
    for unit in "${units[@]}"; do
        if systemctl list-unit-files "$unit" >/dev/null 2>&1; then
            systemctl_disable_now "$unit" || warn "Failed to disable $unit"
        fi
    done

    local masked_units=(
        alsa-restore.service
        alsa-state.service
        sound.target
    )
    for unit in "${masked_units[@]}"; do
        systemctl mask "$unit" >/dev/null 2>&1 || warn "Failed to mask $unit"
    done

    # Prevent audio user services from starting for SSH/user sessions. These are
    # pulled in by desktop images and are not used by the keyboard controller.
    local user_units=(
        pipewire.service
        pipewire.socket
        pipewire-pulse.service
        pipewire-pulse.socket
        wireplumber.service
    )
    for unit in "${user_units[@]}"; do
        systemctl --global mask "$unit" >/dev/null 2>&1 || warn "Failed to mask user unit $unit"
    done

    systemctl set-default multi-user.target || warn "Failed to set default target"
}

print_summary() {
    log "Setup complete"
    if [[ "$PREPARE_ONLY" -eq 1 ]]; then
        cat <<EOF
Repository:      $REPO_ROOT
Boot config:     $BOOT_CONFIG
Mode:            platform preparation only
Project build:   skipped; build split Debian packages on the x86_64 host
Runtime files:   not changed
Systemd units:   package-managed units not installed or replaced
Bluetooth:       $([[ "$NO_BLUETOOTH" -eq 1 ]] && echo "disabled (dtoverlay=disable-bt, radio blocked)" || echo "prepared for late service startup")

After reboot, install matching hidloom-core and device-profile packages in one
apt transaction, then run:
  sudo hidloom-profile <profile> --apply --backup --restart
EOF
        return
    fi
    local enabled_units
    local logic_status_units
    enabled_units="hidloom-usb-gadget, hidloom-hidd, hidloom-late-services.timer, hidloom-network-late.timer"
    if [[ "$NO_PERIPHERALS" -eq 0 ]]; then
        enabled_units="${enabled_units}, i2cd, ledd, ledd-shutdown"
    fi
    if [[ "$NO_MATRIXD" -eq 0 ]]; then
        enabled_units="${enabled_units}, hidloom-uidd, hidloom-outputd, hidloom-logicd-core, matrixd, logicd-companion"
        logic_status_units="hidloom-uidd hidloom-outputd hidloom-logicd-core matrixd logicd-companion"
    else
        enabled_units="${enabled_units}, logicd"
        logic_status_units="logicd"
    fi
    if [[ "$NO_BLUETOOTH" -eq 0 ]]; then
        enabled_units="${enabled_units}"
    fi
    cat <<EOF
Repository:      $REPO_ROOT
Boot config:     $BOOT_CONFIG
Script dir:      /mnt/p3/script
Board profile:   $BOARD_VERSION$([[ "$BOARD_VERSION_EXPLICIT" -eq 1 ]] || echo " default")
Enabled units:   $enabled_units
Bluetooth:       $([[ "$NO_BLUETOOTH" -eq 1 ]] && echo "disabled (dtoverlay=disable-bt, services disabled)" || echo "late via hidloom-late-services.timer")
Matrix scan:     $([[ "$NO_MATRIXD" -eq 1 ]] && echo "disabled (touch/http input only)" || echo "enabled")
Peripherals:     $([[ "$NO_PERIPHERALS" -eq 1 ]] && echo "disabled (i2cd/ledd services disabled)" || echo "enabled (i2cd/ledd early)")
Touch profile:   $([[ "$NO_MATRIXD" -eq 1 ]] && echo "$TOUCH_PANEL_PROFILE" || echo "not installed")
Disabled extras: accounts-daemon, avahi-daemon, cups, glamor-test, lightdm,
                 nfs-blkmap, rpcbind, rp1-test, sysstat timers,
                 udisks2, wayvnc-control
                 pipewire, pipewire-pulse, wireplumber user services
Systemd watchdog: disabled by /etc/systemd/system.conf.d/90-hidloom-disable-watchdog.conf
Persistent journal: /etc/systemd/journald.conf.d/90-hidloom-persistent.conf
                 Set HIDLOOM_KEEP_DESKTOP=1 when running setup to keep desktop services.

After reboot, useful checks:
  systemctl status hidloom-usb-gadget i2cd $logic_status_units ledd httpd viald usbd btd --no-pager
  ls -l /dev/hidg0 /dev/hidg1
  i2cdetect -y 1
EOF
}

main() {
    require_root
    detect_boot_config
    detect_boot_cmdline
    install_apt_packages
    install_python_packages
    configure_boot_and_modules
    configure_device_permissions
    configure_local_console_font
    if [[ "$PREPARE_ONLY" -eq 0 ]]; then
        build_matrixd
        build_c_helpers
        compile_python_bytecode
        restore_repo_user_ownership
        prepare_runtime_files
        apply_board_profile_if_requested
        install_touch_panel_profile
        install_services
    else
        log "Skipping project build, runtime initialization, and unit installation"
    fi
    configure_late_service_policy
    install_bluetooth_hid_dropins
    configure_bluetooth_power
    configure_systemd_watchdog
    configure_system_logging
    optimize_system_services
    print_summary

    if [[ "$NO_REBOOT" -eq 0 ]]; then
        log "Rebooting to apply boot-time USB/I2C settings"
        systemctl reboot
    else
        warn "Reboot skipped. Reboot manually before expecting USB gadget / I2C to work."
    fi
}

main "$@"
