#!/bin/sh
# @label LED video 再生
# KC_SH2.sh — ledd direct-frame 経路で demo video を再生する
#
# このファイルは KC_SH2 キーが押された際に logicd によって実行されます。
# スクリプトの終了コード (exit code) は i2cd に通知されます。
#
# 配置先:
#   SD カード P3 パーティション: /mnt/p3/script/KC_SH2.sh  (優先)
#   開発環境フォールバック:      config/default/script/KC_SH2.sh

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ -n "${HIDLOOM_REPO_ROOT:-}" ]; then
    REPO_DIR="$HIDLOOM_REPO_ROOT"
else
    REPO_DIR="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
fi
PATH="${REPO_DIR}/bin:${PATH}"
export PATH

PLAYER="${REPO_DIR}/tools/demo/play_led_video.py"
VIDEO="${REPO_DIR}/demo/assets/led_video_demo.mp4"
MAX_BRIGHTNESS="${LED_VIDEO_MAX_BRIGHTNESS:-64}"
LOG_FILE="${LED_VIDEO_LOG:-/tmp/hidloom_led_video_demo.log}"
PREVIOUS_LED_STATE_FILE="${LED_VIDEO_PREVIOUS_STATE_FILE:-/tmp/hidloom_led_video_prev_led_state.json}"
SAVED_LED_STATE_FILE="${LED_VIDEO_SAVED_STATE_FILE:-/mnt/p3/led_state.json}"
DIRECT_MULTISPLASH_MODE="${LED_VIDEO_VIALRGB_MODE:-1002}"
export DIRECT_MULTISPLASH_MODE

notify() {
    level="$1"
    message="$2"
    seconds="$3"
    if command -v hidloom-notify >/dev/null 2>&1; then
        hidloom-notify "${level}" "${message}" "${seconds}" || true
    fi
}

save_current_led_state() {
    if ! command -v hidloom-ctrl >/dev/null 2>&1; then
        echo "KC_SH2: hidloom-ctrl not found; previous LED state was not saved"
        return 1
    fi
    tmp="${PREVIOUS_LED_STATE_FILE}.$$"
    if hidloom-ctrl led get >"${tmp}"; then
        mv "${tmp}" "${PREVIOUS_LED_STATE_FILE}"
        return 0
    fi
    rm -f "${tmp}"
    echo "KC_SH2: failed to save previous LED state"
    return 1
}

restore_saved_led_state() {
    if command -v hidloom-ctrl >/dev/null 2>&1; then
        hidloom-ctrl json '{"t":"LED","op":"vialrgb_reset"}'
    fi
}

restore_previous_led_state() {
    if ! command -v hidloom-ctrl >/dev/null 2>&1; then
        echo "KC_SH2: hidloom-ctrl not found; previous LED state was not restored"
        return 1
    fi
    if [ ! -f "${PREVIOUS_LED_STATE_FILE}" ]; then
        echo "KC_SH2: previous LED state not found; restoring saved LED state"
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
        echo "KC_SH2: previous LED state invalid; restoring saved LED state"
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

select_direct_multisplash() {
    if ! command -v hidloom-ctrl >/dev/null 2>&1; then
        echo "KC_SH2: hidloom-ctrl not found; Direct Multisplash mode was not selected"
        return 1
    fi
    request="$(
        /usr/bin/python3 - "${SAVED_LED_STATE_FILE}" <<'PY'
import json
import os
import sys


def byte_env(name: str, default: int) -> int:
    value = int(os.environ.get(name, default))
    return max(0, min(255, value))


mode = int(os.environ.get("DIRECT_MULTISPLASH_MODE", "1002"))
speed = 128
h = 80
s = 255
v = 128
try:
    with open(sys.argv[1], encoding="utf-8") as f:
        saved = json.load(f)
    if int(saved.get("mode", -1)) == mode:
        speed = int(saved.get("speed", speed))
        h = int(saved.get("h", h))
        s = int(saved.get("s", s))
        v = int(saved.get("v", v))
except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError):
    pass

request = {
    "t": "LED",
    "op": "vialrgb",
    "mode": mode,
    "speed": byte_env("LED_VIDEO_VIALRGB_SPEED", speed),
    "h": byte_env("LED_VIDEO_VIALRGB_H", h),
    "s": byte_env("LED_VIDEO_VIALRGB_S", s),
    "v": byte_env("LED_VIDEO_VIALRGB_V", v),
    "save": False,
}
print(json.dumps(request, separators=(",", ":")))
PY
    )" || return 1
    hidloom-ctrl json "${request}"
}

# 既に LED video demo が実行中なら終了する
LED_VIDEO_PROC='tools/demo/play_led_video\.py'
if pgrep -f "${LED_VIDEO_PROC}" > /dev/null 2>&1; then
    echo "KC_SH2: killing existing play_led_video.py"
    notify alert "LED video を停止します" 2
    pkill -TERM -f "${LED_VIDEO_PROC}"
    sleep 1
    restore_previous_led_state || notify warning "LED effect を戻せません" 3
    exit 0
fi

# demo video を ledd direct-frame 経路で再生（バックグラウンド実行）
if [ ! -f "${VIDEO}" ]; then
    echo "KC_SH2: missing ${VIDEO}; run demo/prepare_led_video.py first"
    notify warning "LED video demo が見つかりません" 4
    exit 1
fi
echo "KC_SH2: starting play_led_video.py with ${VIDEO} max_brightness=${MAX_BRIGHTNESS}"
save_current_led_state || true
if select_direct_multisplash; then
    echo "KC_SH2: selected Direct Multisplash mode=${DIRECT_MULTISPLASH_MODE}"
else
    notify warning "Direct Multisplash へ切替できません" 3
fi
notify alert "LED video demo を再生します" 2
cd "${REPO_DIR}" && /usr/bin/python3 "${PLAYER}" "${VIDEO}" --backend ledd-direct --max-brightness "${MAX_BRIGHTNESS}" >"${LOG_FILE}" 2>&1 &
exit 0
