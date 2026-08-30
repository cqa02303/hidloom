# Keyboard write MCP server

`dev/mcp/keyboard_write/server.py`は、read-onlyの`keyboard` MCPを変更せずに併用する
guarded stdio companionです。network listener、任意command、任意file write、service restart、
Bluetooth操作、reboot / shutdownは提供しません。

## Tool境界

| tool | 目的 | state change |
| --- | --- | --- |
| `get_control_status` | keymap digest、layer、pressed matrix、output readiness | なし |
| `plan_key_tap` | 1位置tapのallowlist・blocker・確認句を返す | なし |
| `send_key_tap` | 文字key / digit / Escを1回tapし、必ずreleaseを試行 | あり |
| `plan_keymap_change` | 1 layer / 1位置のbefore/afterとrollbackを返す | なし |
| `apply_keymap_change` | 1位置をlogicdへ反映・同期保存・readback | あり |

write toolは、直前planのfull keymap SHA-256を`expected_sha256`へ渡し、planが返したdynamic
確認句を`confirm`へ完全一致で渡した場合だけ実行します。matrixがidleでない、output targetが
`auto`でない、tap先actionがallowlist外、live keymapに未保存差分がある場合はfail closedです。
keymap保存またはreadbackが失敗した場合は同じ位置の元actionを反映・保存し、rollback readbackを返します。

## Host検証

```bash
python3 script/test_mcp_keyboard_write_server.py
python3 -m py_compile \
  dev/mcp/keyboard_write/server.py \
  script/test_mcp_keyboard_write_server.py
```

CLIでread-only statusだけを見る例:

```bash
PYTHONPATH=. python3 dev/mcp/keyboard_write/server.py --tool get_control_status
```

## SSH stdio profile

実機へHTTP MCP endpointを公開せず、SSH loginとremote user権限を認証境界にします。実機には
root所有のsystem serviceとして常駐させず、user所有のversioned releaseを`0700` directory / `0600`
fileで配置し、必要なCodex profileからだけ起動します。IP、SSH key、password、tokenは設定例やdocsへ
埋め込みません。

`PYTHONPATH=/usr/lib/hidloom:.`はpackage側のread-only MCPと
`daemon/http/keymap_actions.py`を明示的に解決するために必須です。versioned release単体に
これらのpackage payloadを重複copyしません。

```toml
[mcp_servers.keyboard_write]
command = "ssh"
args = [
  "-o", "BatchMode=yes",
  "-o", "ConnectTimeout=5",
  "keyboard.example",
  "cd /srv/hidloom-mcp/current && exec env PYTHONPATH=/usr/lib/hidloom:. python3 dev/mcp/keyboard_write/server.py --stdio",
]
startup_timeout_sec = 15
tool_timeout_sec = 60
enabled = true
```

通常のread-only serverとは登録名とprofileを分けます。write profileは安全な入力欄へfocusしている時、
またはkeymap変更を意図した時だけ有効にします。

## 操作順

1. read-only `keyboard` serverでpackage/profile/service/output healthを確認する。
2. `get_control_status`でkeymap digest、pressed state空、output `auto`を確認する。
3. tapなら`plan_key_tap`、keymapなら`plan_keymap_change`を呼ぶ。
4. planのposition、action、blocker 0、rollbackを人間が確認する。
5. state changeを意図する時だけfull digestとexact確認句をwrite toolへ渡す。
6. responseの`executed`、readback、pressed target clear、rollbackを確認する。
7. keymap試験では元actionへの逆変更を新しいplan / digest / 確認句で行い、元digestまたは元内容へ戻ったことを確認する。

`send_key_tap`はfocused hostへ文字を送るため、focusが不明ならplanで止めます。Enter、modifier、script、
shutdown、layer action、macroはtap allowlistへ含めません。

## Package / Buildroot境界

このcompanionは開発・保守用control planeであり、通常のRaspberry Pi OS core packageやoffline
Buildroot applianceへ常駐追加しません。sourceとtestは公開可能ですが、実機導入はversioned user releaseと
SSH stdio profileで行います。これにより正常時のkeyboard path、boot time、network exposureを変えません。

## 復旧

MCP processはstdio終了で停止し、service restartやrebootは不要です。key tap後にtarget位置がpressedのままなら
toolが1回だけbounded release retryを行います。それでもclearでなければwrite profileを終了し、read-only statusと
`release_all`の既存runbookで復旧します。keymap changeのrollbackが未検証なら追加変更を止め、runtime keymap backupと
logicd readbackを保全して手動判断へ移します。

関連:

- [keyboard-mcp-server.md](keyboard-mcp-server.md)
- [codex-ssh-stdio-mcp-profile.md](codex-ssh-stdio-mcp-profile.md)
- [../policy/mcp-write-capable-tool-design.md](../policy/mcp-write-capable-tool-design.md)
