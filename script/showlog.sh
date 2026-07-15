#!/bin/bash
# logicd / httpd のログを journalctl で表示するヘルパースクリプト

set -euo pipefail

# --- デフォルト設定 ---
SERVICE="logicd"   # 対象サービス: logicd / httpd / all
FOLLOW=0           # -f: リアルタイム追跡
LINES=50           # -n: 表示行数
SINCE=""           # --since: 開始時刻 (例: "1 hour ago")

usage() {
    cat <<USAGE
使い方: $(basename "$0") [オプション]

オプション:
  -s SERVICE   対象サービス: logicd / httpd / all  (デフォルト: logicd)
  -f           リアルタイムで追跡 (journalctl -f 相当)
  -n LINES     表示行数 (デフォルト: 50)
  -t SINCE     開始時刻 e.g. "10 minutes ago" / "today"
  -h           このヘルプを表示

例:
  $(basename "$0")                  # logicd の直近50行
  $(basename "$0") -f               # logicd をリアルタイム追跡
  $(basename "$0") -s httpd -n 100  # httpd の直近100行
  $(basename "$0") -s all -f        # 全サービスをリアルタイム追跡
  $(basename "$0") -t "5 minutes ago"  # 直近5分のログ
USAGE
    exit 0
}

# --- 引数解析 ---
while getopts ":s:fn:t:h" opt; do
    case $opt in
        s) SERVICE="$OPTARG" ;;
        f) FOLLOW=1 ;;
        n) LINES="$OPTARG" ;;
        t) SINCE="$OPTARG" ;;
        h) usage ;;
        :) echo "エラー: -$OPTARG にはオプション引数が必要です" >&2; exit 1 ;;
        \?) echo "エラー: 不明なオプション -$OPTARG" >&2; exit 1 ;;
    esac
done

# --- journalctl 引数を組み立て ---
ARGS=(--no-pager -l)

case "$SERVICE" in
    logicd) ARGS+=(-u logicd) ;;
    httpd)  ARGS+=(-u httpd) ;;
    all)    ARGS+=(-u logicd -u httpd) ;;
    *) echo "エラー: 不明なサービス '$SERVICE' (logicd / httpd / all)" >&2; exit 1 ;;
esac

[[ -n "$SINCE" ]] && ARGS+=(--since "$SINCE")
[[ "$FOLLOW" -eq 1 ]] && ARGS+=(-f) || ARGS+=(-n "$LINES")

exec journalctl "${ARGS[@]}"
