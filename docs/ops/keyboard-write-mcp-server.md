# Keyboard write MCP server

`dev/mcp/keyboard_write/server.py`は、read-onlyの`keyboard` MCPを変更せずに併用する
guarded stdio companionです。network listener、任意command、任意file write、service restart、
Bluetooth操作、reboot / shutdownは提供しません。

## Tool境界

| tool | 目的 | state change |
| --- | --- | --- |
| `get_control_status` | keymap digest、layer、pressed matrix、output readiness | なし |
| `plan_key_tap` | 1位置tapのallowlist・blocker・確認句を返す | なし |
| `send_key_tap` | ownerが文字key / digit / Escを1回tapし、解除を予約 | あり |
| `plan_keymap_change` | 1 layer / 1位置のbefore/afterと復旧候補を返す | なし |
| `apply_keymap_change` | 1位置をlogicdへ反映・同期保存・readback | あり |

write toolは、直前planのfull keymap SHA-256を`expected_sha256`へ渡し、planが返したdynamic
確認句を`confirm`へ完全一致で渡した場合だけ実行します。確認句には実行ownerの起動世代と
keymap/layer/output revisionが含まれ、tapにはplanごとのnonceも含まれます。同じ確認句の再送は
同一operationの結果を返し、改めて同じ位置をtapする場合は新しいplanを使います。

tapはcoordinatorの保存済みSHA/revision確認後に、native ownerの一つの処理内でaction、layer、
押下・委譲・予約中入力、output `auto`/readinessを再確認します。許可したactionを専用sourceで
押下し、5〜200msの範囲でowner自身が解除を予約します。途中の物理入力や制御変更より先に
合成入力を解除し、物理入力は保持します。Python単独ownerはguarded tap非対応を返します。
通常のWeb入力にはnative/Pythonとも明示的なsource sessionを提供します。

keymap変更は、full SHA、coordinator/owner世代、revisionを条件とする単一位置の
`KEYMAP_COMPARE_APPLY`で適用・同期保存します。保存やreadbackが失敗しても古いactionへの
無条件rollbackは行いません。保存済み・runtime適用済み・不明を分けて返します。

## Host検証

```bash
python3 script/test_mcp_keyboard_write_server.py
python3 script/test_mcp_native_owner.py
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
6. responseの`executed`、owner結果、readback、復旧候補を確認する。
7. keymap試験では元actionへの逆変更を新しいplan / digest / 確認句で行い、元digestまたは元内容へ戻ったことを確認する。

`send_key_tap`はfocused hostへ文字を送るため、focusが不明ならplanで止めます。Enter、modifier、script、
shutdown、layer action、macroはtap allowlistへ含めません。

`owner_result.state=started`はownerによる受付と解除予約、`released`はowner内での解除処理済みを
示します。いずれもUSB/BLE先のアプリケーションが受信した証明ではありません。通信不確実時は
同一operationの保持結果を照会し、結果も取得できない場合は`executed=null`を返します。

## Package / Buildroot境界

このcompanionは開発・保守用control planeであり、通常のRaspberry Pi OS core packageやoffline
Buildroot applianceへ常駐追加しません。sourceとtestは公開可能ですが、実機導入はversioned user releaseと
SSH stdio profileで行います。これにより正常時のkeyboard path、boot time、network exposureを変えません。

## 復旧

MCP processはstdio終了で停止し、native ownerの解除予約は継続します。応答損失を理由にraw P/Rを
再送しません。同じ確認句で照会・再送しても同じoperationに限定されます。owner再起動で保持結果を
失った場合は実行結果不明のまま扱い、安全なfocusと現在のhealthを確認してから次の新規planへ進みます。

keymapの部分失敗ではruntime keymapとowner readbackを保全します。元actionへ戻す場合も新しい
plan/digest/確認句による条件付き変更とし、その間の別clientの編集を上書きしません。

関連:

- [ADR-0024: 入力の順序・状態確認・解除](../policy/adr/0024-native-owner-transactions.md)
- [keyboard-mcp-server.md](keyboard-mcp-server.md)
- [codex-ssh-stdio-mcp-profile.md](codex-ssh-stdio-mcp-profile.md)
- [../policy/mcp-write-capable-tool-design.md](../policy/mcp-write-capable-tool-design.md)
