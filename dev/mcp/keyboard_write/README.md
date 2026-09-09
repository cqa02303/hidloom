# Keyboard write MCP companion

`server.py` は、既存の read-only `keyboard` MCP を変更せずに併用する
`keyboard-write` 用の guarded stdio server です。logicdのcontrol coordinatorを通して
実行ownerへ世代条件付き操作を送り、次の5 toolだけを公開します。

| tool | 動作 |
| --- | --- |
| `get_control_status` | keymap digest、active layer、pressed matrix、output readinessを集約する |
| `plan_key_tap` | 1 matrix位置の安全性とdynamic確認句をdry-runする |
| `send_key_tap` | allowlist済み文字キーまたはEscを1回だけtapする |
| `plan_keymap_change` | 1 layer / 1 matrix位置の変更と復旧候補をdry-runする |
| `apply_keymap_change` | 同じ1位置をlogicdへ反映し、同期保存とreadbackを行う |

`send_key_tap` と `apply_keymap_change` は、直前のfull keymap SHA-256とplanが返した
確認句の完全一致が必須です。任意command、任意path、全keymap上書き、service restart、
Bluetooth操作、reboot / shutdownは提供しません。

tapの確認句はownerの起動世代・keymap/layer/output revisionと新しいnonceを含みます。
同じ確認句の再送は同一operationとして扱い、新しいtapには新しいplanを使います。
native ownerが押下前の条件確認と時間指定の解除を担当し、MCP終了後も解除を行います。
応答損失時は同じoperationの結果を照会し、不明な結果を「未実行」と扱いません。
Python単独ownerはguarded tap非対応を明示しますが、通常のWeb入力sessionは利用できます。

```bash
python3 script/test_mcp_keyboard_write_server.py
python3 script/test_mcp_native_owner.py
python3 dev/mcp/keyboard_write/server.py --stdio
```

登録・操作・rollback手順は
[keyboard-write-mcp-server.md](../../../docs/ops/keyboard-write-mcp-server.md)を参照してください。
