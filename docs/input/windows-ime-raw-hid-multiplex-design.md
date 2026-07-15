# Windows IME Raw HID Multiplex Design

更新日: 2026-06-21

`<keyboard-host>` では USB gadget の 5本目の HID function (`hid.usb4`) が
`No such device` で拒否された。Windows IME custom HID route は、
新しい `/dev/hidg4` endpoint ではなく、既存 `/dev/hidg1` Raw HID / Vial
endpoint を安全に multiplex できるかを次候補にする。

## 観測

- 2026-06-21 現在の endpoint は `/dev/hidg0` Keyboard / Mouse / Consumer Control multi-report、
  `/dev/hidg1` Raw HID / Vial、`/dev/hidg2` US sub keyboard。
- `/dev/hidg1` の runtime owner は legacy `usbd` ではなく `hidloom-hidd`。
- `HIDLOOM_WINDOWS_IME_CUSTOM_HID=1 ./setup_usb_gadget.sh` で `hid.usb4` を probe すると、
  kernel / configfs が追加 HID function を拒否した。
- guard 追加後は、拒否時に既存 gadget を壊さず早期終了できる。

## 方針

Raw HID multiplex は、既存 Vial Raw HID protocol と衝突しないことを最優先にする。
Vial GUI が開いている時に予期しない packet を流すと誤動作の可能性があるため、
first slice は read-only design と receiver PoC の device selection に留める。

候補:

1. `/dev/hidg1` に vendor-defined IME frame を流す。
2. `hidloom-hidd` が Vial packet と IME packet を識別し、Vial 以外の frame を Windows receiver 向けに送る。
3. Windows receiver は Raw HID interface を開き、IME frame magic を持つ report だけを処理する。

## Frame 候補

既存 Raw HID report length は 32 byte。
Windows IME custom HID の 8 byte report を payload として包む。

```text
byte 0..3   magic: CQA1
byte 4      channel: 0x10 (windows_ime)
byte 5      payload length: 8
byte 6..13  windows_ime_custom_hid 8 byte report
byte 14..30 reserved zero
byte 31     xor checksum over byte 0..30
```

## 実装ゲート

- Vial Raw HID の既存 host smoke が壊れないこと。
- Vial GUI 接続中に unsolicited input report を送らない、または receiver profile 有効時だけ送ること。
- receiver が起動していない時は no-op / warning にすること。
- `logicd` から直接 `/dev/hidg1` へ書かず、Raw HID owner (`hidloom-hidd`) の socket/API 経由にすること。

## 次の first slice

1. Raw HID IME frame encode / decode helper を追加する。
2. `hidloom-hidd` に write-only local socket を追加し、Vial bridge と同じ fd owner から `/dev/hidg1` へ送る。
3. default disabled にし、receiver available 前は送らない。
4. Windows receiver PoC は IME 注入せず、Raw HID frame を表示するだけにする。

2026-06-10 first slice:

- `daemon/logicd/windows_ime_raw_hid.py` で 32 byte frame encode / decode helper を追加した。
- `script/test_windows_ime_raw_hid.py` で magic、channel、payload、reserved zero、checksum を固定した。
- legacy `usbd` に default disabled の datagram socket `/tmp/usbd_windows_ime.sock` を追加した。
  `USBD_WINDOWS_IME_SOCKET_ENABLED=1` の時だけ socket を開き、受け取った 32 byte frame を
  Vial bridge と同じ `/dev/hidg1` fd owner から write lock 付きで送る。
- `script/send_windows_ime_raw_hid_frame.py` は IME action を 32 byte Raw HID frame に包み、
  legacy `usbd` の local socket へ送る。
- `script/windows_ime_raw_hid_receiver_poc.py` は Windows host 側で Raw HID interface
  MI_01 を開き、受け取った frame を表示するだけにする。
- まだ logicd output router や receiver availability status には接続しない。
- 現行既定 owner は `hidloom-hidd` なので、この PoC 経路を実運用へ進める場合は
  `/tmp/usbd_windows_ime.sock` 相当を `hidloom-hidd` 側へ移植してから有効化する。
