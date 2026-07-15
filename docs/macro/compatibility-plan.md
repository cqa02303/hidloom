# Macro Compatibility Plan

作成日: 2026-05-17
更新日: 2026-05-31

このメモは、KML / shell script / QMK macro 互換レイヤの役割分担を整理したものです。

## 現時点の決定

2026-05-31 時点では、マクロ系の実装対象は次のように分ける。

| 系統 | 現在の扱い | 理由 |
|---|---|---|
| `KC_SH0`-`KC_SH10` | 正規の script 実行経路 | HTTP Script editor、fresh install、C helper command が揃っている |
| Vial Macro buffer / `M0`-`M7` | 対応済みの互換入口 | raw buffer を `settings.vial_macro_buffer` に保存し、`MACRO:VIAL0`-`MACRO:VIAL7` へ変換して実行する |
| local `MACRO:name` | local config 専用の named macro | `config/default/config.json` / runtime config の `macros` を `daemon/logicd/macro.py` が実行する |
| KML | 実装前設計TODOへ昇格 | `macro/kml.py` を独自路線の runner として残し、`KC_KMLn` / HTTP editor 連携の境界を先に固定する |
| QMK macro compatible subset | 実装前設計TODOへ昇格 | `KC_QMn` / 外部 runner / parser subset / editor 連携の境界を先に固定する |
| Vial advanced macro 完全互換 | 実装前設計TODOへ昇格 | Vial Macro の基本 buffer 互換、KML / QMK macro、Dynamic Macro とは別物として扱う |

したがって、この TODO の結論は「KML と QMK macro syntax は混ぜない」
「実装済みの Vial Macro buffer 互換を正とする」
「`KC_KMLn` / `KC_QMn` は、実装前設計で runner / editor / test 境界を固定してから追加する」です。

## 実装済みの経路

```text
KC_SHn
  -> daemon/logicd/macro.py
  -> /mnt/p3/script/KC_SHn.sh or config/default/script/KC_SHn.sh
  -> shell process
  -> hidloom-key / hidloom-keytext / hidloom-oled / hidloom-notify / hidloom-ctrl
```

```text
M0-M7 in Vial
  -> viald/httpd import/export
  -> settings.vial_macro_buffer
  -> MACRO:VIAL0 ... MACRO:VIAL7
  -> daemon/logicd/macro.py token runner
```

```text
MACRO:name
  -> config macros dict
  -> daemon/logicd/macro.py
  -> key / delay / unicode / IME tokens
```

## 重要

```text
KML と QMK macro syntax は別物。
```

現在の:

```text
macro/kml.py
```

は:

```text
KML (Keyboard Macro Language)
```

専用 parser であり、QMK macro syntax parser ではない。

KML は:

- この project 独自
- shell / Python runner 前提
- text macro + key action sequence 用

として設計している。

一方 QMK macro syntax は:

- QMK firmware 側仕様
- Dynamic Macro
- Send String
- QK_MACRO
- Vial macro

など複数系統が存在する。

## 昇格後の方針

マクロ系は次の3系統に分ける。

| 系統 | 役割 | 方針 |
|---|---|---|
| Shell script | OS操作、外部コマンド、ネットワークやサービス操作 | 既存の `KC_SH0`-`KC_SH10` を継続 |
| KML | 独自路線の高機能マクロ言語 | 自由に拡張する。QMK互換を無理に背負わせない |
| QMK macro互換 | Vial/QMKと記述・概念を合わせる互換レイヤ | QMKでよく見る記述を外部runnerで解釈し、既存 `key_events.sock` へ流す |

QMK macro互換は `logicd` に内蔵しない。KMLと同じく外部runner方式にし、
`logicd` は custom keycode を受けたら対応ファイル/runnerを起動するだけにする。

## 現在の位置づけ

### KML

```text
KML
    ↓
macro/kml.py
    ↓
key event sequence
```

### QMK macro compatibility

現状:

```text
未実装。Vial Macro buffer 互換とは別枠の実装前設計TODO。
```

実装する場合は:

```text
QMK macro compatibility layer
```

を別 subsystem として扱う予定。

## 配置案

以下は `KC_KMLn` / `KC_QMn` の実装前設計TODOで固定する配置案です。

初期テンプレートは `config/default/macros/` に置く。

```text
config/default/
  macros/
    kml/
      example.kml
    qmk/
      example.qmk
```

実機で編集・上書きされる配置は `/mnt/p3` 側に置く。

```text
/mnt/p3/macros/kml/
/mnt/p3/macros/qmk/
```

優先順位は user-edited runtime macro を factory default より優先する。

1. `/mnt/p3/macros/<kind>/`
2. `config/default/macros/<kind>/`

`/mnt/p3/kml/`、`config/default/kml/`、`/mnt/p3/qmk_macro/`、`config/default/qmk_macro/` は初期採用しない。
既存 `script/` と同じ直下配置に見えるため、runner owner と syntax 境界が曖昧になる。

## 追加キーコード案

以下は未実装ですが、実装前設計TODOへ昇格済みの追加案です。
現在の正規入口は `KC_SH0`-`KC_SH10` と Vial Macro `M0`-`M7` です。
KML / QMK macro の first slice は fixed slot keycode を追加せず、
`KML(name)` / `QMK_MACRO(name)` の runtime action 名だけを扱う。

| キーコード | 対応ファイル | 用途 |
|---|---|---|
| `KML(name)` | `/mnt/p3/macros/kml/<name>.kml` / `config/default/macros/kml/<name>.kml` | KML runnerで実行 |
| `QMK_MACRO(name)` | `/mnt/p3/macros/qmk/<name>.qmk` / `config/default/macros/qmk/<name>.qmk` | QMK macro互換runnerで実行 |

将来 `KC_KMLn` / `KC_QMn` を追加する場合も、まず `0`-`7` の 8 slot / family から始める。
`KC_KML0`-`KC_KML10` / `KC_QM0`-`KC_QM10` や `0`-`15` の広い枠は初期採用しない。

既存:

| キーコード | 対応ファイル | 用途 |
|---|---|---|
| `KC_SH0` ... `KC_SH10` | `KC_SHn.sh` | shell scriptとして実行 |

## QMK macro互換の範囲

完全なQMK Cマクロ互換は目指さない。まずは `QMK macro compatible subset` として、
QMKでよく見る記述をテキストとしてパースする。

初期対応候補:

```c
SEND_STRING("hello");
TAP_CODE(KC_ENTER);
REGISTER_CODE(KC_LSFT);
TAP_CODE(KC_1);
UNREGISTER_CODE(KC_LSFT);
WAIT_MS(100);
```

最初の対応命令:

| 命令 | 動作 |
|---|---|
| `SEND_STRING("...")` | 文字列入力 |
| `TAP_CODE(KC_*)` | キーをtap |
| `TAP_CODE16(TO(n))` | QMK / Vial 互換 layer action をtap |
| `REGISTER_CODE(KC_*)` | キー押下 |
| `UNREGISTER_CODE(KC_*)` | キー離放 |
| `WAIT_MS(n)` | n ms待つ |

Touch panel layer switch から使う first use case では、既存の QMK / Vial 互換 `TO(n)` を macro 内から実行する。

```c
// /mnt/p3/macros/qmk/layer_kana.qmk
TAP_CODE(KC_LANG1);
WAIT_MS(0);
TAP_CODE16(TO(0));

// /mnt/p3/macros/qmk/layer_alpha.qmk
TAP_CODE(KC_LANG2);
WAIT_MS(0);
TAP_CODE16(TO(1));

// /mnt/p3/macros/qmk/layer_symbol.qmk
TAP_CODE(KC_LANG1);
WAIT_MS(0);
TAP_CODE16(TO(2));
```

`TO(n)` はすでに project 内で QMK / Vial 互換の layer action として扱っているため、独自別名 command は追加しない。
初期は Vial codec と同じ `0 <= n < 16` の `TO(n)` だけを `TAP_CODE16(...)` 経由で許可し、`MO` / `TG` / arbitrary action へは広げない。
この use case では `KC_LANG1` が日本語 / かな入力側、`KC_LANG2` が英数入力側へ寄せる IME mode tap です。
`WAIT_MS(n)` は QMK の `SEND_STRING(...)` 内の `SS_DELAY(ms)`、および QMK JSON macro の `{"action": "delay", "duration": ms}` に相当する timing step として扱う。
IME mode tap 直後の host 反映待ちに使い、初期値は `WAIT_MS(0)` として、実機確認で必要な場合だけ増やす。

Touch panel での表示は QMK macro file ではなく、touch panel profile 側の表示 override が owner です。

```json
{
  "action_labels": {
    "QMK_MACRO(layer_kana)": "あいう",
    "QMK_MACRO(layer_alpha)": "ABC",
    "QMK_MACRO(layer_symbol)": "☆123"
  }
}
```

この分離により、`QMK_MACRO(layer_kana)` は物理 keyboard でも同じ sequence を実行でき、
touch panel だけが `あいう` のような 800x480 向け表示を上書きできます。
macro runner は表示 label を解釈せず、HTTP / touch panel UI は macro sequence の中身を実行しません。

初期 subset の後に検討する候補:

- `SS_TAP(X_*)` など QMK SEND_STRING helper
- modifier付き記述
- `layer_on()` / `layer_off()` 相当
- simpleな `if` や状態分岐は当面対象外

## 実行経路

以下は `QMK_MACRO(name)` / `KML(name)` 実装時の想定です。現在は `KC_SHn` と
`MACRO:VIALn` / `MACRO:name` が実装済み経路です。

```text
matrixd/httpd/viald
  -> logicd keymap resolve
  -> QMK_MACRO(name) / KML(name)
  -> runner dry-run / execute
  -> events returned to logicd
  -> logicd output processor
  -> /dev/hidg0 Keyboard
```

runner は `/tmp/key_events.sock` へ直接書かない。
exit code と validation / runtime error の summary は `i2cd` へ通知するが、macro event 本体は通知しない。

## 実装時に更新する場所

`KML(name)` / `QMK_MACRO(name)` を実装対象に昇格した時に更新する。

- `daemon/logicd/macro.py` または runner wrapper: structured request / result と dry-run
- `macro/` または新規 module: KML runner / QMK macro compatible runner 本体
- `config/default/macros/kml/`, `config/default/macros/qmk/`: 初期テンプレート
- HTTP viewer: read-only file picker と validation / dry-run 結果表示
- tests: parser、runner dry-run、action validation、配置優先順位、`key_events.sock` 非直書き

first slice では以下を更新しない。

- `config/default/keycodes.json`: `KC_KMLn` / `KC_QMn` は追加しない
- `config/default/vial.json`: Vial custom keycode として表示しない
- `daemon/http/static/keyboard.js`: 通常 key picker へ slot keycode を追加しない

## 注意点

- KMLは独自路線として拡張する。
- QMK macro互換は、Vial/QMKと記述・概念を合わせるための互換レイヤとする。
- 現在 `macro/kml.py` が QMK macro syntax を解析しているわけではない。
- 「QMK Cをコンパイルして実行する」機能ではない。
- first slice では Vial GUI に custom keycode として見せない。Vial Macro機能そのものへの完全対応は別TODO。
