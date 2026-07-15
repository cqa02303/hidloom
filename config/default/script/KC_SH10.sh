#!/bin/sh
# @label 再起動
# KC_SH10.sh — システム再起動
#
# このファイルは KC_SH10 キーが押された際に logicd によって実行されます。
# スクリプトの終了コード (exit code) は i2cd に通知されます。
#
# KC_SH0 はスクリプトエディタで最初に表示されるため安全な no-op とし、
# 誤実行時の影響が大きい再起動は KC_SH10 に置いています。
#
# 配置先:
#   SD カード P3 パーティション: /mnt/p3/script/KC_SH10.sh  (優先)
#   開発環境フォールバック:      config/default/script/KC_SH10.sh

echo "KC_SH10: system reboot at $(date)"
hidloom-notify warning "システムを再起動します" 2 || true
sleep 1
systemctl reboot
exit 0
