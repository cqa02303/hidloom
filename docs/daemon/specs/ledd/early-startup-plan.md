# ledd Early Startup Plan

作成日: 2026-06-21

## 目的

`ledd` を `logicd-companion` より前に起動し、keyboard hot path の確立を待つ間も低負荷の起動中エフェクトを表示する。
`logicd-companion` が起動して `/tmp/ledd_events.sock` を listen した後は、既存の初期同期で保存済みの本来 Lighting state に上書きする。

## 現状

現在の `ledd.service` は `After=logicd-companion.service` / `Requires=logicd-companion.service` を持つ。
そのため late services timer で `ledd` を起動するまで LED は動かず、`logicd-companion` が先に立つことも要求される。

`i2cd.service` はすでに `After=local-fs.target` だけで早期起動し、OLED hardware / boot status を自分で扱う。
`logicd-companion` から layer / mode / daemon status / alert が届いたら表示内容を更新するため、早期表示 daemon と runtime state owner が分離できている。

## 方針

`ledd` も `i2cd` と同じ責務分担へ寄せる。

| 領域 | owner |
| --- | --- |
| LED hardware, LED chain order, startup effect | `ledd` |
| runtime Lighting state, VialRGB mode, layer state, lock state | `logicd-companion` |
| physical key hot path | `matrixd -> logicd-core-rs -> hidloom-outputd -> hidloom-hidd` |

`ledd` 起動時に必要な正本は `config/default/ledd.json` だけにする。
起動中エフェクトに必要な情報は LED 数、物理順序、brightness、color order、startup effect 設定だけである。
keymap 由来の semantic role / layer overlay / lock state / current VialRGB state は、`logicd-companion` 接続後に反映する。

## First Slice

1. `ledd.service` から `logicd-companion.service` への hard dependency を外す。
2. `ledd.service` は `After=local-fs.target` で早期起動する。
3. `hidloom-late-services.service` は `ledd.service` を起動しない。`ledd` は通常 boot path で起動済みとする。
4. `ledd.json` に `startup_effect` を追加する。
5. `ledd` は起動直後に低輝度 VialRGB breathing を開始する。
6. `logicd_receiver` は従来通り `/tmp/ledd_events.sock` へ再接続を続ける。
7. `logicd-companion` は ledd 接続時に semantic role snapshot、semantic keymap snapshot、既存の初期同期を送る。

既存の `logicd-companion` 初期同期は次を送る。

1. semantic role snapshot
2. semantic keymap snapshot
3. layer state
4. output mode
5. current VialRGB state
6. active overlay states

このため startup breathing は、`logicd-companion` 起動後に保存済み `/mnt/p3/led_state.json` または default Lighting state で上書きされる。
keymap-derived layer overlay も `ledd` 起動時の file fallback ではなく、接続後の `semantic_keymap` で復帰する。

## Startup Effect

初期値は低負荷・低輝度にする。

```json
"startup_effect": {
  "enabled": true,
  "kind": "vialrgb",
  "mode": 6,
  "speed": 48,
  "h": 140,
  "s": 120,
  "v": 32
}
```

`mode=6` は VialRGB breathing。
起動中の視認性を出しつつ、LED 電流と CPU 負荷を抑えるため `v` は 24-48 程度を基本にする。

## Later Slice

2026-06-21 に semantic role 定義の first step も `logicd-companion` push 型へ寄せた。

- `logicd-companion -> ledd` の `semantic_roles` snapshot message を追加。
- `ledd` は `semantic_roles` snapshot と `semantic_keymap` snapshot を合成して runtime semantic config にする。
- HTTP Lighting role editor 保存後の `LEDD_RELOAD` は、`ledd` file reload ではなく `logicd-companion` からの snapshot 再送を正経路にする。

`ledd` 側の semantic role file reload と keymap file fallback は互換・診断用 mode として残す。
残りは実機で、早期 startup effect が `logicd-companion` 接続後の semantic snapshot / saved VialRGB state で
自然に上書きされ、Multisplash / reactive LED が復帰することを確認する。

## OLED との関係

`i2cd` はすでに早期起動済みで、OLED / ADS1115 / low-rate boot status を自分で扱う。
`ledd` と `i2cd` は I/O が分かれている。

| daemon | 主な hardware | 起動時負荷 |
| --- | --- | --- |
| `i2cd` | I2C OLED / ADS1115 | OLED redraw, analog polling |
| `ledd` | GPIO12 LED strip | LED frame update |

同時に早期起動しても IPC 経路は衝突しない。
ただし電源・CPU 余裕を見るため、startup effect は低輝度・低 FPS から始める。

## 実機メモ

2026-07-02 に、起動中の breathing で LED 色が激しく乱れる症状は LED 端子の
はんだ不良で再現していた。ランドとの接続だけでは不安定で、端子周囲を
取り囲むように広くはんだを乗せると解消した。startup effect は症状を
見えやすくする trigger になり得るが、この症状はまず DIN / VDD / GND の
接触、共通 GND、電源余裕、データ線の機械的安定性を確認する。

## 確認項目

- `ledd.service` が `logicd-companion.service` なしで起動する。
- `ledd` が `/tmp/ledd_events.sock` 未作成時に落ちず、再接続待ちする。
- `logicd-companion` 起動後、`ledd` が接続して current VialRGB state で startup effect を上書きする。
- `logicd-companion` 起動後、`ledd` が `semantic_roles` / `semantic_keymap` snapshot を受けて reactive / layer overlay を復帰する。
- `i2cd.service` の起動順・OLED 表示に regress がない。
- `matrixd -> logicd-core-rs -> hidloom-outputd -> hidloom-hidd` hot path の boot timing に regress がない。
