#!/bin/sh
# @label PTY Mirror
# KC_SH7.sh — sessiond PTY terminal mirror M0 を開始する
#
# 安全な text editor 入力欄を US sub keyboard endpoint の入力先として focus してから押します。
# M0 は軽作業用です。終了は bash 上で `exit` を入力するか、KC_SH7/operator escape で止めます。

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ -n "${HIDLOOM_REPO_ROOT:-}" ]; then
    REPO_ROOT="$HIDLOOM_REPO_ROOT"
elif [ -f "/usr/lib/hidloom/tools/sessiond_ctl.py" ]; then
    REPO_ROOT="/usr/lib/hidloom"
elif [ -f "${SCRIPT_DIR}/../../../tools/sessiond_ctl.py" ]; then
    REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../../.." && pwd)"
else
    REPO_ROOT="/usr/lib/hidloom"
fi
SOCKET="${SESSIOND_SOCKET:-/tmp/sessiond.sock}"
SESSIOND_LOG="${SESSIOND_LOG:-/tmp/sessiond.log}"
SESSIOND_IDLE_EXIT_SEC="${SESSIOND_IDLE_EXIT_SEC:-10}"
SESSIOND_USER="${SESSIOND_USER:-}"

sessiond_status() {
    python3 "$REPO_ROOT/tools/sessiond_ctl.py" --socket "$SOCKET" --read-timeout 0.4 status >/dev/null 2>&1
}

sessiond_user() {
    if [ -n "$SESSIOND_USER" ]; then
        printf '%s\n' "$SESSIOND_USER"
        return
    fi
    if [ "$(id -u)" -eq 0 ]; then
        stat -c '%U' "$REPO_ROOT" 2>/dev/null || printf 'pi\n'
        return
    fi
    id -un
}

start_sessiond() {
    user="$(sessiond_user)"
    if [ -e "$SOCKET" ] && [ ! -S "$SOCKET" ]; then
        echo "sessiond socket path exists and is not a socket: $SOCKET" >&2
        return 1
    fi
    if [ "$(id -u)" -eq 0 ] && [ -S "$SOCKET" ]; then
        rm -f "$SOCKET"
    fi

    if [ "$(id -u)" -eq 0 ] && [ "$user" != "root" ]; then
        nohup sudo -u "$user" env \
            PYTHONPATH="$REPO_ROOT/daemon:$REPO_ROOT" \
            HIDLOOM_REPO_ROOT="$REPO_ROOT" \
            python3 -m sessiond.sessiond --socket "$SOCKET" \
                --exit-when-idle-sec "$SESSIOND_IDLE_EXIT_SEC" >"$SESSIOND_LOG" 2>&1 &
    else
        nohup env \
            PYTHONPATH="$REPO_ROOT/daemon:$REPO_ROOT" \
            HIDLOOM_REPO_ROOT="$REPO_ROOT" \
            python3 -m sessiond.sessiond --socket "$SOCKET" \
                --exit-when-idle-sec "$SESSIOND_IDLE_EXIT_SEC" >"$SESSIOND_LOG" 2>&1 &
    fi

    i=0
    while [ "$i" -lt 20 ]; do
        if sessiond_status; then
            return 0
        fi
        sleep 0.1
        i=$((i + 1))
    done
    return 1
}

hidloom-notify alert "PTY START" 1.5 2>/dev/null || true

if ! sessiond_status; then
    if ! start_sessiond; then
        hidloom-notify warning "PTY ERROR" 3 2>/dev/null || true
        exit 1
    fi
fi

if python3 "$REPO_ROOT/tools/sessiond_ctl.py" \
    --socket "$SOCKET" \
    start \
    --shell bash \
    --columns 120 \
    --rows 35 \
    --source KC_SH7
then
    exit 0
fi

hidloom-notify warning "PTY ERROR" 3 2>/dev/null || true
exit 1
