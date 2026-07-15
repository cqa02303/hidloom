# Timed Tap / Morse behavior plan

更新日: 2026-05-29

Tap Dance へ押下時間分岐を混ぜず、独立した `MORSE(name)` behavior として扱う方針です。
短押しを dot、長押しを dash として sequence を作り、timeout、leaf 到達、または force-commit 到達で action を確定します。

## 目的

- Tap count ではなく、押している時間の短長で分岐する。
- `.` / `-` の並びで action を選ぶ。
- 分岐先が `KC_NO` / `KC_NONE` / 未定義なら cancel にする。
- `max_depth` を設定ごとに変えられるようにする。
- それ以上の枝がなければ自動確定し、枝があっても強制確定したい場合だけ `force_commit` を指定できるようにする。
- 将来 Web UI で分岐ツリーを見ながら編集し、モールス自体の学習にも使えるようにする。

## Action

```text
MORSE(main)
MORSE(nav)
```

`MORSE(name)` は既存の `TD(name)` とは別物です。
Tap Dance は連打回数、Morse behavior は押下時間列で分岐します。

## 設定案

`settings.interaction.morse_behaviors` に置く想定です。

```json
{
  "settings": {
    "interaction": {
      "morse_behaviors": {
        "main": {
          "dot_threshold": 0.18,
          "sequence_timeout": 0.70,
          "max_depth": 4,
          "force_commit": [".-"],
          "map": {
            ".": "KC_E",
            "-": "KC_T",
            "..": "KC_I",
            ".-": "KC_A",
            ".-.": "KC_R",
            "-.": "KC_N",
            "--": "KC_M",
            "...": "KC_S",
            "---": "KC_O"
          }
        }
      }
    }
  }
}
```

`force_commit` は「その sequence に到着した時点で、下に枝があっても打ち切って確定する」指定です。
たとえば `.-` を force commit にすると、より深い `.-.` が定義されていても `.-` 到着時点で `KC_A` を確定します。
旧メモで使っていた `terminal` / `terminal_sequences` は互換 alias として読み取れますが、新しい設定では `force_commit` を使います。

## 判定

- press 時刻を保存する。
- release 時刻との差分が `dot_threshold` 以下なら `.`。
- `dot_threshold` より長ければ `-`。
- sequence が `max_depth` を超えたら cancel。
- sequence が action を持ち、`force_commit` に含まれていれば即 commit。
- sequence が action を持ち、より長い prefix がなければ自動 leaf として即 commit。
- sequence が action を持ち、より長い prefix があれば timeout まで待つ。
- timeout 時に action があれば commit、なければ cancel。
- action が `KC_NO` / `KC_NONE` / 空扱いなら cancel。

## Web UI 方針

Morse behavior は、単なる表形式よりも分岐ツリー表示が向いています。
編集 UI は Keymap editor とは別の Interaction / Advanced panel に置く候補です。

### Tree view

```text
main
├─ .  KC_E
│  ├─ .  KC_I
│  │  └─ .  KC_S
│  └─ -  KC_A  [force_commit]
│     └─ .  KC_R
└─ -  KC_T
   ├─ .  KC_N
   └─ -  KC_M
      └─ -  KC_O
```

表示したい情報:

- sequence: `.` / `-` の並び
- assigned action
- cancel branch: 未設定、`KC_NO`、`KC_NONE`
- leaf / prefix / force_commit / cancel の状態
- depth と `max_depth`
- dot / dash threshold
- timeout

### Editing flow

1. `MORSE(name)` behavior を選ぶ。
2. `dot_threshold`、`sequence_timeout`、`max_depth` を編集する。
3. tree の各 node に action を割り当てる。
4. その node に到着したら枝があっても確定する場合は `force_commit` を有効にする。
5. `KC_NO` / `KC_NONE` は cancel として表示する。
6. 未設定 branch は薄い cancel node として表示する。
7. key picker は既存の action picker を使う。
8. 変更前に preview / validation を表示する。

### Learning aid

モールス入力の練習にも使えるよう、将来は以下を検討します。

- 最後に入力した sequence を `.-` のように表示する。
- dot / dash 判定結果をリアルタイム表示する。
- 短点/長点の境界に近い入力を warning 表示する。
- 入力した sequence がどの tree branch にいるか highlight する。
- force_commit 到着で即確定したことを表示する。
- commit / cancel の結果を OLED / LED / WebSocket event に出す。

## 実装段階

### Phase 1: core / validation

済み:

- `logicd.morse_behavior` を追加。
- `MORSE(name)` parser を追加。
- dot / dash 判定、prefix 待ち、leaf commit、force-commit、cancel、可変 `max_depth` を core test で固定。
- `interaction_config` で `MORSE(name)` action と `morse_behaviors` を validation 対象に追加。
- `force_commit` の validation を追加。
- `terminal` / `terminal_sequences` は互換 alias として読み取り可能。

### Phase 2: InteractionEngine wiring

済み:

- `InteractionEngine.__init__` に `morse_behaviors` を追加。
- `MORSE(name)` press で runtime.press(now) する。
- release で runtime.release(now) する。
- committed action があれば `_tap_events(action, row, col, source="morse")` を返す。
- needs_timeout の場合は `InteractionTimer(kind="morse")` を積む。
- timeout で commit / cancel する。
- config reload / reset 時に pending sequence を破棄する。
- force_commit sequence が deeper prefix を持っていても即 commit することを InteractionEngine test で固定。

未接続:

- HTTP UI での編集。
- debug / WebSocket / OLED / LED feedback。

### Phase 3: Web UI

候補:

- read-only tree inspector から開始する。
- 次に action picker を使った editor にする。
- 編集結果は existing interaction settings API に載せる。
- `KC_NO` / `KC_NONE` は cancel branch として色分けする。
- force_commit node は badge / icon で見える化する。

## 注意

- Tap Dance と同じ key に `MORSE(name)` を割り当てる場合、Tap Dance とは排他にする。
- timeout を長くしすぎると通常入力が遅く感じる。
- force_commit を多用すると深い sequence へ進めなくなるため、Web UI で到達不能 branch を警告する。
- max_depth を深くしすぎると学習には良いが、確定待ちや誤入力が増える。
- daemon restart / config reload 時は pending sequence を必ず破棄する。
