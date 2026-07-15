# ledd Direct Frame Socket Plan

更新日: 2026-05-21

`tools/demo/play_led_video.py` や direct LED pattern の性能改善のため、`viald -> logicd -> ledd` の長い経路を通さず、producer から `ledd` へ 1 frame 分の LED データを直接送る内部高速 path の設計メモ。

## 結論

`tools/demo/play_led_video.py` など内部 LED pattern 再生では、VialRGB direct 互換経路とは別に、`ledd` に近い位置へ直接接続する。

```text
tools/demo/play_led_video.py --backend ledd-direct
  ↓ /tmp/ledd_direct_frame.sock
1 packet = 1 full LED frame
  ↓
ledd
  ↓
LED strip
```

従来の `direct` backend は以下のように長くなりやすい。

```text
tools/demo/play_led_video.py --backend direct
  ↓
viald
  ↓
logicd
  ↓
ledd
  ↓
LED strip
```

この経路は互換性には良いが、高 FPS の LED pattern では以下の overhead が増えやすい。

- Python 側 write 回数
- JSON encode / decode
- daemon 間 socket hop
- logicd の中継負荷
- 細かい chunk の frame boundary 管理

そのため、内部高速再生では `producer -> ledd` の専用経路を追加する。

## 現在の実装状況

済み:

- `daemon/ledd/direct_frame.py` に packet header / encode / decode / validation helper を追加
- `script/test_ledd_direct_frame.py` に normal / invalid packet validation test を追加
- `daemon/ledd/direct_frame_socket.py` に `/tmp/ledd_direct_frame.sock` scaffold を追加
- `ledd.py` から direct-frame receiver thread を起動するようにした
- `script/test_ledd_direct_frame_socket.py` に socket scaffold helper test を追加
- `AnimationManager.apply_direct_frame()` を追加し、validated frame を LED buffer へ反映するようにした
- `script/test_ledd_direct_frame_apply.py` に RGB / GRB / stale frame / LED count mismatch の apply test を追加
- `tools/demo/play_led_video.py --backend ledd-direct` を追加し、1 frame = 1 `LDF1` packet で送信できるようにした
- `script/test_led_video_ledd_direct.py` に producer 側 packet 生成 test を追加

未実装:

- direct-frame active 中の producer disconnect fallback
- FPS / CPU / dropped frame の実測

## 既存経路との関係

### 残すもの

- VialRGB direct 互換経路
- 通常 LED effect
- HTTP / logicd 経由の LED 制御

### 追加したもの

- `ledd` direct-frame socket
- 1 packet = 1 full LED frame
- `tools/demo/play_led_video.py --backend ledd-direct`

互換経路と高速経路は目的が異なる。

```text
VialRGB direct compatible path:
  compatibility / existing protocol priority

ledd direct-frame path:
  internal performance / frame throughput priority
```

## Socket 方針

socket:

```text
/tmp/ledd_direct_frame.sock
```

`ledd` が listen し、producer が接続して frame を送る。
受信 packet は validate され、問題なければ `AnimationManager.apply_direct_frame()` で LED buffer へ反映される。

producer 側は `tools/demo/play_led_video.py --backend ledd-direct --ledd-socket /tmp/ledd_direct_frame.sock` で接続する。

## Packet 仕様

`daemon/ledd/direct_frame.py` で固定した初期 binary packet 仕様:

```text
magic:      4 bytes   "LDF1"
frame_id:   4 bytes   unsigned little-endian
led_count:  2 bytes   unsigned little-endian
format:     1 byte    0 = RGB, 1 = GRB
flags:      1 byte    reserved
payload:    led_count * 3 bytes
```

helper:

```text
ledd.direct_frame.encode_direct_frame()
ledd.direct_frame.decode_direct_frame()
ledd.direct_frame.pack_rgb_triples()
```

socket scaffold helper:

```text
ledd.direct_frame_socket.direct_frame_receiver()
ledd.direct_frame_socket.handle_direct_frame_client()
ledd.direct_frame_socket.record_direct_frame_packet()
```

producer helper:

```text
tools.demo.play_led_video.bgr_to_rgb_payload()
tools.demo.play_led_video.send_ledd_direct_frame()
```

validation 方針:

- magic を検証する
- packet length を検証する
- `led_count` が正の値であることを検証する
- `expected_led_count` が指定された場合は一致を必須にする
- `payload == led_count * 3 bytes` を必須にする
- unsupported format は拒否する
- invalid packet は log して無視する

## ledd 側の責務

`ledd` は direct-frame socket で受け取った frame を検証して適用する。

責務:

- magic / header length / payload length 検証
- `led_count` が現在の LED 数と合うか検証
- `frame_id` による古い frame / 重複 frame の扱い
- `format` に応じた RGB / GRB 変換
- 不正 packet は log に出して無視
- first direct-frame で現在の animation を停止し direct mode に入る
- frame payload を LED buffer に反映して `show()` する

残りの設計:

- producer 切断時に通常 effect へ戻すか、最後の frame を維持するか
- direct-frame active 中に HTTP / VialRGB / animation 切替が来た時の優先順位をさらに明文化する

## producer 側の責務

`tools/demo/play_led_video.py` など producer は 1 frame ごとに full LED payload を作って送る。

責務:

- frame_id を単調増加させる
- 全 LED 分の payload を 1 packet にまとめる
- 送信失敗時は次 frame へ進むか停止するか policy を持つ
- FPS / dropped frame / write latency を測る

現在の `tools/demo/play_led_video.py --backend ledd-direct` は以下を行う。

- OpenCV の BGR frame を LED 物理順に sample する
- BGR を RGB payload に変換する
- `LDF1` packet を生成する
- `/tmp/ledd_direct_frame.sock` へ `sendall()` する
- packets/s は 1 frame あたり 1 packet として表示する

## frame drop 方針

LED 動画再生では、古い frame を遅れて表示するより、最新 frame を優先した方が自然。

実装済み:

- `frame_id <= last_frame_id` の frame は stale frame として無視する

検討中:

- ledd 側で処理中に次 frame が来た場合、古い frame を捨てるか検討する
- producer 側は送信詰まり時に frame skip できるようにする
- `frame_id` を log / metrics に出せるようにする

## 互換性方針

- 既存 VialRGB direct 互換 protocol は壊さない
- 既存 direct frame chunk は当面残す
- 新 socket は内部高速 path として追加する
- `tools/demo/play_led_video.py` は `direct` と `ledd-direct` の両 backend を持つ

## 計測項目

導入前後で以下を比較する。

- FPS
- dropped frame
- producer CPU 使用率
- ledd CPU 使用率
- write 回数 / 秒
- socket write latency
- LED 実表示の滑らかさ

## 実装順

### Phase 1: 仕様とテスト helper

済み:

- packet header 定義
- encode / decode helper
- validation test
- invalid packet test

### Phase 2: ledd direct-frame socket scaffold

済み:

- `/tmp/ledd_direct_frame.sock` listen scaffold
- packet を受けて validate
- log / metrics 反映

### Phase 3: ledd frame apply

済み:

- full frame を LED buffer へ反映
- RGB / GRB payload を扱う
- stale frame を無視する
- LED count mismatch を防御的に無視する

残り:

- producer disconnect 時の fallback を整理
- direct-frame active 中の effect priority をさらに整理

### Phase 4: tools/demo/play_led_video.py 対応

済み:

- direct-frame socket へ 1 frame = 1 packet で送信
- fallback として既存 `direct` backend を残す
- producer 側 packet 生成 test を追加

残り:

- FPS / CPU / dropped frame を測定する

## 注意

- `ledd` が不正 packet で落ちないことを必須にする
- 既存 VialRGB direct / 通常 LED effect を壊さない
- 高速化 path は内部専用から始める
