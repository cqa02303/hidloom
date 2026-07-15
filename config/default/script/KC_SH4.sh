#!/bin/sh
# @label VialRGB preview
# KC_SH4.sh — HTTP/Vial の LED Effect リストを順番に確認する
#
# このファイルは KC_SH4 キーが押された際に logicd によって実行されます。
# 長めの確認処理なので、実体はバックグラウンドで起動します。
#
# 配置先:
#   SD カード P3 パーティション: /mnt/p3/script/KC_SH4.sh  (優先)
#   開発環境フォールバック:      config/default/script/KC_SH4.sh

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ -n "${HIDLOOM_REPO_ROOT:-}" ]; then
    REPO_DIR="$HIDLOOM_REPO_ROOT"
else
    REPO_DIR="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
fi
LOG_FILE="/tmp/vialrgb_preview.log"

if pgrep -f 'preview_vialrgb_effects.py' >/dev/null 2>&1; then
    echo "KC_SH4: preview already running"
    hidloom-notify alert "VialRGB preview は実行中です" 2 || true
    exit 0
fi

echo "KC_SH4: starting full VialRGB effect preview; log=${LOG_FILE}"
hidloom-notify alert "VialRGB preview を開始します" 2 || true
cd "${REPO_DIR}" || exit 1
nohup /usr/bin/python3 script/preview_vialrgb_effects.py --seconds 5 --restore >"${LOG_FILE}" 2>&1 &
exit 0
