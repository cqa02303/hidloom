# bin

実機で直接呼ぶ生成済み補助コマンドを置くフォルダです。

現在は `tools/hidloom_send/build.sh` と `tools/hidloom_hidd/build.sh` が以下を生成します。

- `bin/hidloom-key`
- `bin/hidloom-keytext`
- `bin/hidloom-oled`
- `bin/hidloom-notify`
- `bin/hidloom-ctrl`
- `bin/hidloom-hidd`

生成物は git 管理外です。ソースは `tools/hidloom_send/` と `tools/hidloom_hidd/` にあります。
各build wrapperはhard cut前の旧名binaryを`bin/`とcross-build出力から除去してからcanonical名をinstallします。
手動監査と安全な除去は`python3 tools/generated_binary_hygiene.py [--clean]`で実行できます。

KC_SHn script の実行時は、`logicd` がこの `bin/` を `PATH` の先頭に追加します。
script からは `bin/` prefix なしで `hidloom-notify` や `hidloom-ctrl` を呼べます。

`hidloom-hidd` は systemd unit から呼ぶ native HID report broker です。Python `usbd` と
同じ broker socket を使うため、通常は `hidloom-hidd.service` 経由で owner を切り替えます。
