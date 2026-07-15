#!/bin/bash
# キーボード入力送信テストスクリプト

if [ ! -c "/dev/hidg0" ]; then
    echo "❌ /dev/hidg0が見つかりません"
    echo "   まず './setup_usb_gadget.sh' を実行してください"
    exit 1
fi

# 引数チェック
if [ $# -eq 0 ]; then
    echo "使用法: $0 <キー>"
    echo "例:"
    echo "  $0 a        # 'a'キーを送信"
    echo "  $0 hello    # 'hello'を型入力"
    echo "  $0 enter    # Enterキーを送信"
    echo "  $0 space    # スペースキーを送信"
    exit 1
fi

# キーコード変換関数
get_keycode() {
    case "$1" in
        a) echo "\\x00\\x00\\x04\\x00\\x00\\x00\\x00\\x00" ;;
        b) echo "\\x00\\x00\\x05\\x00\\x00\\x00\\x00\\x00" ;;
        c) echo "\\x00\\x00\\x06\\x00\\x00\\x00\\x00\\x00" ;;
        h) echo "\\x00\\x00\\x0b\\x00\\x00\\x00\\x00\\x00" ;;
        e) echo "\\x00\\x00\\x08\\x00\\x00\\x00\\x00\\x00" ;;
        l) echo "\\x00\\x00\\x0f\\x00\\x00\\x00\\x00\\x00" ;;
        o) echo "\\x00\\x00\\x12\\x00\\x00\\x00\\x00\\x00" ;;
        space) echo "\\x00\\x00\\x2c\\x00\\x00\\x00\\x00\\x00" ;;
        enter) echo "\\x00\\x00\\x28\\x00\\x00\\x00\\x00\\x00" ;;
        *) echo "" ;;
    esac
}

# キーリリース（全て0）
KEY_RELEASE="\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00"

# 引数が"hello"や複数文字の場合
if [ ${#1} -gt 1 ] && [ "$1" != "space" ] && [ "$1" != "enter" ]; then
    echo "文字列 '$1' を送信します..."
    for ((i=0; i<${#1}; i++)); do
        char="${1:$i:1}"
        keycode=$(get_keycode "$char")
        if [ -n "$keycode" ]; then
            echo -ne "$keycode" > /dev/hidg0
            usleep 50000  # 50ms待機
            echo -ne "$KEY_RELEASE" > /dev/hidg0
            usleep 20000  # 20ms待機
        fi
    done
else
    # 単一キー
    keycode=$(get_keycode "$1")
    if [ -n "$keycode" ]; then
        echo "キー '$1' を送信します..."
        echo -ne "$keycode" > /dev/hidg0
        usleep 100000  # 100ms待機
        echo -ne "$KEY_RELEASE" > /dev/hidg0
    else
        echo "❌ 未対応のキー: '$1'"
        exit 1
    fi
fi

echo "✅ 送信完了"
