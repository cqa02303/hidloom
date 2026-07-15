#!/bin/bash
#
# kml.sh - KML (Keyboard Macro Language) 実行スクリプト
#
# Usage:
#   kml.sh <kml_file>              # KMLファイルを実行
#   kml.sh -c '<kml_string>'       # KML文字列を実行（シングルクォート推奨）
#   kml.sh --debug <kml_file>      # デバッグモード
#   kml.sh -c --debug '<kml_string>'
#
# Examples:
#   # ファイルから実行
#   kml.sh copy_paste.kml
#
#   # 文字列を直接実行（シェルエスケープに注意！）
#   kml.sh -c '\T180 \[Ctrl c \] \R8 [End] \n \[Ctrl v \]'
#
#   # デバッグモード
#   kml.sh --debug test.kml
#

# スクリプトのディレクトリを取得
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KML_PY="${SCRIPT_DIR}/kml.py"

# kml.pyが存在するか確認
if [ ! -f "$KML_PY" ]; then
    echo "Error: kml.py not found at $KML_PY" >&2
    exit 1
fi

# Pythonインタープリタを探す
if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON=python
else
    echo "Error: Python not found. Please install Python 3.x" >&2
    exit 1
fi

# kml.pyに引数をそのまま渡す
exec "$PYTHON" "$KML_PY" "$@"
