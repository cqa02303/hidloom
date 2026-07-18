#!/bin/sh
# @label IP表示
# KC_SH3.sh — 現在の node 名と IP アドレスを OLED にアラート表示する
#
# このファイルは KC_SH3 キーが押された際に logicd によって実行されます。
# スクリプトの終了コード (exit code) は i2cd に通知されます。
#
# 配置先:
#   SD カード P3 パーティション: /mnt/p3/script/KC_SH3.sh  (優先)
#   開発環境フォールバック:      config/default/script/KC_SH3.sh

ascii_oled_text() {
    (
        export LC_ALL=C
        printf '%s' "$1" | tr -cd '\11\12\15\40-\176'
    )
}

# 接続中 Wi-Fi の SSID を取得（利用可能なコマンドを順に試す）
SSID=""
if command -v iwgetid >/dev/null 2>&1; then
    SSID=$(iwgetid -r 2>/dev/null)
fi
if [ -z "$SSID" ] && command -v nmcli >/dev/null 2>&1; then
    SSID=$(nmcli -t -f active,ssid dev wifi 2>/dev/null \
        | awk -F: '$1 == "yes" { sub(/^yes:/, ""); print; exit }')
fi
[ -z "$SSID" ] && SSID="N/A"
SSID=$(ascii_oled_text "$SSID")
[ -z "$SSID" ] && SSID="N/A"

NODE=$(hostname 2>/dev/null)
[ -z "$NODE" ] && NODE="N/A"
NODE=$(ascii_oled_text "$NODE")
[ -z "$NODE" ] && NODE="N/A"

# IP アドレスを取得（スペース区切りで複数ある場合は改行で結合）
IP=$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -v '^$' | head -3 | tr '\n' ' ' | sed 's/ $//')
[ -z "$IP" ] && IP="N/A"
IP=$(ascii_oled_text "$IP")
[ -z "$IP" ] && IP="N/A"

hidloom-notify alert "Node: ${NODE} SSID: ${SSID} IP: ${IP}" 7
exit $?
