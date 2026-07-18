# Device-side Codex keyboard extension possibilities

更新日: 2026-07-18

## 位置づけ

キーボード内の Raspberry Pi OS で Codex CLI / Codex app-server を動かし、
HIDloom を対話的に診断・設定・拡張する可能性を、遠い将来の Wishlist として残す。

これは実装計画、採用決定、package 搭載要求ではない。現行の標準運用は引き続き
private workspace reference *(omitted from public export)* の
desktop Codex + SSH / read-only Keyboard MCP とする。具体的な利用需要、資源計測、
安全境界、受け入れ条件が揃うまで TODO へ昇格しない。

## 中心となる考え方

Codex をキー入力ごとの判断経路には入れず、低頻度の control plane として使う。
通常入力の hot path は常に次だけで完結させる。

```text
matrixd -> logicd-core-rs -> hidloom-outputd -> hidloom-hidd / btd / uidd
```

Codex、認証、network、app-server、管理 UI のいずれかが停止しても、通常の
keyboard / mouse / consumer input は継続できなければならない。

## 想定する役割分担

| surface | 将来用途 | 境界 |
| --- | --- | --- |
| `codex exec` | 一回完結の health 診断、log 要約、keymap review、macro 候補生成、package 更新前検査 | 明示された workspace と sandbox 内で実行し、通常入力には依存させない |
| `codex app-server` | touch / OLED / remote client からの会話、thread 継続、streaming progress、diff と approval の表示 | local Unix socket を第一候補とし、LAN へ直接公開しない |
| read-only `keyboard` MCP | 既存の status、keymap、route、runtime、checkout 診断 | 現行の read-only 境界を維持する |
| 将来の `keyboard-write` MCP | bounded な draft 適用、preview、rollback 付き操作 | 別 server、dry-run default、allowlist、物理承認、post-smoke を必須にする |
| host bridge | foreground app、選択文字列、project context を明示的に渡す | keyboard 単体では host の画面、clipboard、選択範囲を読めないことを前提にする |

Codex app-server は rich client 用の JSON-RPC interface であり、一般公開する
keyboard HTTP API の代替ではない。現行資料では thread / turn、streaming event、
approval、conversation history を扱える一方、WebSocket transport は experimental とされる。
remote 接続が必要になっても、まず Unix socket、localhost、SSH tunnel を検討し、
non-loopback listen は authentication と TLS の設計完了後だけを候補にする。

参考:

- [Codex App Server](https://learn.chatgpt.com/docs/app-server)
- [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
- [Keyboard MCP Server](../ops/keyboard-mcp-server.md)
- [MCP write-capable tool design](../policy/mcp-write-capable-tool-design.md)

## 機能の可能性

### 対話型 keymap / interaction 設計

- 「Caps は短押し Esc、長押し Ctrl」のような自然言語要求から draft を生成する。
- 現在の keymap、layer、conditional / oneshot / locked state、Vial 表現可能範囲を読んで
  変更候補と影響範囲を説明する。
- production runtime へ直接書かず、shadow profile、schema validation、virtual matrix test、
  diff review、backup、rollback を経て適用する。

### 自然言語 macro 設計

- `MACRO:name`、named text、KML / QMK-compatible subset の候補を生成する。
- 任意 shell を AI macro として登録せず、declarative action、文字数、tap 数、timeout、
  output route を allowlist で制限する。
- focused host が不明な実文字送信や Enter は実行しない。

### Keyboard 整備士 / 自己診断

- 既存 read-only MCP tool から service、socket、HID endpoint、output route、runtime keymap、
  journal excerpt を集約し、原因候補と次の read-only check を説明する。
- 例として「特定キーだけ反応しない」「USB と OLED の表示が食い違う」などを、
  matrix / core / broker / host の層に分けて診断する。
- restart や設定変更を提案する場合も、実行は write-capable 境界へ分離する。

### 安全な自己変更 UI

- touch panel に agent response、進捗、diff、test result、rollback plan を表示する。
- 最終適用は UI click だけでなく、専用の物理 key chord / long hold を要求する案を検討する。
- 適用前 snapshot、適用後 health check、失敗時の自動 restore を一組にする。

### 使用傾向に基づく layout 提案

- 入力本文を保存せず、matrix position ごとの count、hold time、誤打後の訂正傾向など、
  privacy-preserving telemetry だけから配置候補を提案する。
- telemetry の既定は off とし、保存期間、削除、export、個人情報境界を先に決める。
- 自動で layout を変更せず、提案と simulation に留める。

### Host context を使う AI key

- host bridge が利用者の明示操作で渡した選択文字列を、要約、翻訳、校正、code review し、
  preview 後に host へ返す。
- foreground application に応じた profile 候補を提示する。
- keyboard 側から host screen や clipboard を無断取得しない。prompt injection を含む
  host content は untrusted input として扱う。

### 保守・開発支援

- package 更新前の変更 review、test 選択、release note draft、health snapshot 比較を行う。
- 実機固有の checkout や `/mnt/p3` を直接開発 workspace にせず、clean dedicated worktree、
  staged artifact、package-first update を維持する。
- 自己更新の自動適用、git push、release 公開はこの Wishlist の範囲に含めない。

## 採用しない構成

- 物理 key event ごとに Codex / cloud response を待つ。
- Codex service を `keyboard_ready` または `input-to-HID ready` の依存関係にする。
- `danger-full-access` と approval 無効を常用する。
- 任意 shell、任意 file write、任意 git 操作を keyboard UI から実行可能にする。
- app-server / MCP を認証なしで LAN または internet へ公開する。
- user が確認していない host input field へ文字、shortcut、Enter を送る。
- 入力内容、credential、full Bluetooth address、長い log body を会話履歴へ無制限に残す。

## OS / Buildroot 判断

- 検討対象は Raspberry Pi OS の optional package / optional service に限定する。
- 常駐を前提にせず、手動起動、socket activation、要求時起動、停止後の通常入力継続を比較する。
- Buildroot M6 は offline keyboard appliance のまま維持し、Codex CLI、app-server、認証情報、
  cloud network dependency は搭載しない。
- 将来、Codex 非搭載でも利用できる declarative macro / draft validation / rollback helper が
  生まれた場合、その agent-independent 部分だけを Buildroot へ搭載する価値を別途評価する。

## TODO 昇格条件

次をすべて満たすまで W3 のまま維持する。

1. desktop Codex + SSH では満たしにくい、device-side 実行固有の利用シナリオが一つ以上ある。
2. 対象 device の CPU、memory、storage、idle / active power、起動競合を計測できる。
3. install / update / disable / uninstall、auth、`CODEX_HOME`、secret storage の運用が書ける。
4. hot path 非依存、read-only first slice、network 非公開を自動テストまたは構成検査で固定できる。
5. write-capable 操作には dry-run、allowlist、物理承認、snapshot、post-smoke、rollback がある。
6. privacy、conversation retention、host context、prompt injection の境界が決まっている。
7. Raspberry Pi OS package としての直近利用価値が、容量・保守・攻撃面の増加を上回る。

最初に昇格するとしても、first slice は既存 read-only Keyboard MCP を使う
「対話型 Keyboard 整備士」とし、keymap write、host key send、service restart、常駐 daemon は含めない。
