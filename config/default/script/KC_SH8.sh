#!/bin/sh
# @label matrixd診断
# KC_SH8.sh — matrixd/input diagnostics snapshot
#
# キー取りこぼしや ghost が再発した直後に押すための診断採取スクリプトです。
# 既定では 30 秒間 key_events / ledd_events を監視し、直近 10 分の journal、
# matrixd 設定、systemd unit、process snapshot などを Markdown に保存します。
#
# 配置先:
#   SD カード P3 パーティション: /mnt/p3/script/KC_SH8.sh  (優先)
#   開発環境フォールバック:      config/default/script/KC_SH8.sh

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ -n "${HIDLOOM_REPO_ROOT:-}" ]; then
    REPO_ROOT="$HIDLOOM_REPO_ROOT"
elif [ -f "/usr/lib/hidloom/tools/matrixd_diagnostics_snapshot.py" ]; then
    REPO_ROOT="/usr/lib/hidloom"
elif [ -f "${SCRIPT_DIR}/../../../tools/matrixd_diagnostics_snapshot.py" ]; then
    REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../../.." && pwd)"
else
    REPO_ROOT="/usr/lib/hidloom"
fi
OUT_DIR="${MATRIXD_DIAG_DIR:-/mnt/p3/matrixd-diagnostics}"
DURATION="${MATRIXD_DIAG_DURATION:-30}"
SINCE="${MATRIXD_DIAG_SINCE:-10 minutes ago}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${OUT_DIR}/matrixd-diagnostics-KC_SH8-${STAMP}.md"

mkdir -p "$OUT_DIR"
hidloom-notify alert "MATRIX DIAG START" "$DURATION" 2>/dev/null || true

python3 "$REPO_ROOT/tools/matrixd_diagnostics_snapshot.py" \
    --duration "$DURATION" \
    --since "$SINCE" \
    --output "$OUT"
code=$?

if [ "$code" -eq 0 ]; then
    echo "KC_SH8: matrixd diagnostics saved: $OUT"
    hidloom-notify alert "MATRIX DIAG SAVED" 5 2>/dev/null || true
    exit 0
fi

echo "KC_SH8: matrixd diagnostics failed: exit=${code} output=${OUT}" >&2
hidloom-notify warning "MATRIX DIAG FAILED: ${code}" 5 2>/dev/null || true
exit "$code"
