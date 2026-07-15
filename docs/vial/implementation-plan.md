# Vial 実装計画

## 目的

Vial 対応を段階的に実装し、問題を transport / protocol / state / persistence に分離して検証する。

2026-06-21 現在、Vial 対応は実装済みで、Raw HID bridge の既定 owner は legacy `usbd` ではなく
native `hidloom-hidd` です。この文書は段階実装時の計画を残しつつ、現行 owner 境界を注記します。

## 前提

- USB interface は次の順に再編する。

| Device | 役割 |
|---|---|
| `/dev/hidg0` | Keyboard / Mouse / Consumer Control multi-report |
| `/dev/hidg1` | Raw HID / Vial |
| `/dev/hidg2` | US sub keyboard endpoint |

- `hidloom-hidd` は USB I/O の橋渡しだけを行う。legacy `usbd` は rollback / A/B 診断用に残す。
- `viald` は Vial protocol adapter とする。
- キーマップ状態の正本は native `logicd-core-rs` と `logicd-companion` の control plane で分担する。
- LED 状態の正本は companion / runtime files とし、描画は `ledd` が担当する。
- VialRGB は `viald -> logicd-companion -> ledd` で処理する。

## Stage 0: USB gadget 再編

### 変更対象

- `setup_usb_gadget.sh`
- `config/default/config.json`
- `daemon/logicd/config_loader.py`
- `README.md`
- `USB_GADGET_SETUP.md`

### 完了条件

- `/dev/hidg0` と `/dev/hidg1` が作られる。
- keyboard / mouse / consumer control が新しい番号で動く。
- `/dev/hidg1` が Raw HID として列挙される。

## Stage 1: Raw HID bridge

### 変更対象

- `tools/hidloom_hidd/`
- `system/systemd/hidloom-hidd.service`
- `daemon/viald/viald.py`
- `system/systemd/viald.service`

### 完了条件

- `/dev/hidg1 <-> hidloom-hidd <-> viald` で 32 byte packet が往復する。
- 連続 packet でフレーミングが崩れない。
- `viald` 再起動後に `hidloom-hidd` が再接続できる。

## Stage 2: Vial detect

### 変更対象

- `daemon/viald/protocol.py`
- `daemon/viald/README.md`

### 完了条件

- Vial GUI がデバイスを検出する。
- デバイスが `config/default/vial.json` を返す。
- Vial GUI にレイアウトが表示される。

## Stage 3: Dynamic keymap GET

### 変更対象

- `daemon/viald/protocol.py`
- `daemon/viald/keycode_codec.py`

### 完了条件

- `viald` が `logicd` の `{"t":"G"}` を利用して現在キーマップを取得する。
- Vial GUI の表示と `getkeymap.sh` の結果が一致する。

## Stage 4: Dynamic keymap SET

### 変更対象

- `daemon/viald/protocol.py`
- `daemon/viald/keycode_codec.py`

### 完了条件

- Vial GUI の 1 キー変更が `logicd` の `{"t":"M", ...}` に反映される。
- 実打鍵結果が変更後のキーマップになる。
- Web UI と Vial GUI が同じ状態を表示する。

## Stage 5: Keymap persistence

### 変更対象

- `daemon/logicd/logicd.py`
- 必要なら `daemon/logicd/keymap_store.py`
- `daemon/logicd/README.md`

### 完了条件

- `logicd` に保存 API がある。
- Vial で変更したキーマップが `/mnt/p3/keymap.json` に保存される。
- 再起動後も変更が保持される。

## Stage 6: VialRGB

### 変更対象

- `daemon/viald/protocol.py`
- `daemon/logicd/logicd.py`
- `daemon/ledd/ledd.py`
- `daemon/ledd/animations/*`
- `daemon/ledd/README.md`

### 完了条件

- VialRGB effect selection が `logicd` を経由して `ledd` に届く。
- brightness / color / speed が反映される。
- direct frame が反映される。
- VialRGB effect 識別子は upstream の表現に合わせる。
- 独自 effect は Vial 未使用の識別子空間に追加する。

## 先送り項目

- Vial security / unlock
- macro / tap dance / advanced feature の完全互換
- VialRGB の effect 全網羅
- LED state の永続化
- custom keycodes の GUI 露出

## 実装順の理由

1. USB transport を先に通し、descriptor と framing の問題を隔離する。
2. `viald` は最初 `logicd` 非依存で動かし、Vial detect を単独で成立させる。
3. GET の後に SET を実装し、表示と状態の整合を確認してから永続化へ進む。
4. VialRGB は transport と keymap が安定してから追加する。

## 関連文書

- [../daemon/specs/viald/architecture.md](../daemon/specs/viald/architecture.md)
- [lighting/vialrgb-protocol.md](../lighting/vialrgb-protocol.md)
- [research/vialrgb-upstream.md](../research/vialrgb-upstream.md)
