#!/bin/sh
# @label 未割当
# KC_SH0.sh — 安全な未割当スクリプト
#
# このファイルは KC_SH0 キーが押された際に logicd によって実行されます。
# スクリプトの終了コード (exit code) は i2cd に通知されます。
#
# KC_SH0 はスクリプトエディタで最初に表示されるため、誤って「チェック実行」しても
# 危険な操作にならないよう no-op にしています。再起動は KC_SH10.sh を使います。
#
# 配置先:
#   SD カード P3 パーティション: /mnt/p3/script/KC_SH0.sh  (優先)
#   開発環境フォールバック:      config/default/script/KC_SH0.sh

echo "KC_SH0: safe no-op at $(date)"
exit 0
