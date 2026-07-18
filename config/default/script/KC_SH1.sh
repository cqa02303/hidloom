#!/bin/sh
# @label ledd トグル
# KC_SH1.sh — ledd トグル（動作中は停止、停止中は起動）
#
# このファイルは KC_SH1 キーが押された際に logicd によって実行されます。
# スクリプトの終了コード (exit code) は i2cd に通知されます。
#
# 配置先:
#   SD カード P3 パーティション: /mnt/p3/script/KC_SH1.sh  (優先)
#   開発環境フォールバック:      config/default/script/KC_SH1.sh

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ -n "${HIDLOOM_REPO_ROOT:-}" ]; then
    REPO_DIR="$HIDLOOM_REPO_ROOT"
else
    REPO_DIR="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
fi
PATH="${REPO_DIR}/bin:${PATH}"
export PATH

PREVIOUS_LED_STATE_FILE="${LED_VIDEO_PREVIOUS_STATE_FILE:-/tmp/hidloom_led_video_prev_led_state.json}"

notify() {
    level="$1"
    message="$2"
    seconds="$3"
    if command -v hidloom-notify >/dev/null 2>&1; then
        hidloom-notify "${level}" "${message}" "${seconds}" || true
    fi
}

restore_saved_led_state() {
    if command -v hidloom-ctrl >/dev/null 2>&1; then
        hidloom-ctrl json '{"t":"LED","op":"vialrgb_reset"}'
    fi
}

restore_previous_led_state() {
    if ! command -v hidloom-ctrl >/dev/null 2>&1; then
        echo "KC_SH1: hidloom-ctrl not found; previous LED state was not restored"
        return 1
    fi
    if [ ! -f "${PREVIOUS_LED_STATE_FILE}" ]; then
        echo "KC_SH1: previous LED state not found; restoring saved LED state"
        restore_saved_led_state
        return $?
    fi
    request="$(
        /usr/bin/python3 - "${PREVIOUS_LED_STATE_FILE}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    state = json.load(f)
mode = int(state["mode"])
if mode == 1002:
    raise SystemExit(2)
request = {
    "t": "LED",
    "op": "vialrgb",
    "mode": mode,
    "speed": int(state["speed"]),
    "h": int(state["h"]),
    "s": int(state["s"]),
    "v": int(state["v"]),
    "save": False,
}
print(json.dumps(request, separators=(",", ":")))
PY
    )" || {
        echo "KC_SH1: previous LED state invalid; restoring saved LED state"
        rm -f "${PREVIOUS_LED_STATE_FILE}"
        restore_saved_led_state
        return $?
    }
    if hidloom-ctrl json "${request}"; then
        rm -f "${PREVIOUS_LED_STATE_FILE}"
        return 0
    fi
    return 1
}

# LED demo が実行中の場合は終了する。direct backend は終了時に元の LED effect へ戻す。
LED_DEMO_PROC='tools/demo/play_led_(video|pattern)\.py'
LED_DEMO_WAS_RUNNING=0
if pgrep -f "${LED_DEMO_PROC}" > /dev/null 2>&1; then
    echo "KC_SH1: killing LED demo player"
    notify alert "LED DEMO STOP" 2
    pkill -TERM -f "${LED_DEMO_PROC}"
    sleep 1
    LED_DEMO_WAS_RUNNING=1
fi
if [ "${LED_DEMO_WAS_RUNNING}" -eq 1 ] || [ -f "${PREVIOUS_LED_STATE_FILE}" ]; then
    restore_previous_led_state || notify warning "LED RESTORE FAILED" 3
fi

# ledd サービスのトグル
if systemctl is-active --quiet ledd; then
    echo "KC_SH1: ledd is running — stopping"
    notify alert "LEDD STOP" 2
    systemctl stop ledd
    exit 0
else
    echo "KC_SH1: ledd is stopped — starting"
    notify alert "LEDD START" 2
    systemctl start ledd
    exit 0
fi
