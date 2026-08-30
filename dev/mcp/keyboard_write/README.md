# Keyboard write MCP companion

`server.py` は、既存の read-only `keyboard` MCP を変更せずに併用する
`keyboard-write` 用の guarded stdio server です。Web GUI と同じ logicd control / matrix
socket 経路を使い、次の5 toolだけを公開します。

| tool | 動作 |
| --- | --- |
| `get_control_status` | keymap digest、active layer、pressed matrix、output readinessを集約する |
| `plan_key_tap` | 1 matrix位置の安全性とdynamic確認句をdry-runする |
| `send_key_tap` | allowlist済み文字キーまたはEscを1回だけtapする |
| `plan_keymap_change` | 1 layer / 1 matrix位置の変更とrollbackをdry-runする |
| `apply_keymap_change` | 同じ1位置をlogicdへ反映し、同期保存とreadbackを行う |

`send_key_tap` と `apply_keymap_change` は、直前のfull keymap SHA-256とplanが返した
確認句の完全一致が必須です。任意command、任意path、全keymap上書き、service restart、
Bluetooth操作、reboot / shutdownは提供しません。

```bash
python3 script/test_mcp_keyboard_write_server.py
python3 dev/mcp/keyboard_write/server.py --stdio
```

登録・操作・rollback手順は
[keyboard-write-mcp-server.md](../../../docs/ops/keyboard-write-mcp-server.md)を参照してください。
