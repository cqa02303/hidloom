# Windows IME custom HID receiver PoC

更新日: 2026-06-10

Windows 側 receiver の PoC は、IME 注入を行わず、custom HID / Raw HID
report を受信して表示するだけにする。

この PoC は診断用であり、通常利用の採用方針ではない。helper アプリなしで使える
標準 keyboard HID route を優先する。

`<keyboard-host>` では 5本目の HID function が使えないため、現時点の PoC は
既存 Raw HID interface (`/dev/hidg1`, Windows 側 MI_01) の multiplex frame を読む。

## 目的

- Pi から送られる 32 byte Raw HID multiplex frame が Windows 側で見えることを確認する。
- 内側の 8 byte report を decode する。
- report の command id、press / release、sequence id、checksum を表示する。
- 受信確認前に `SendInput` / TSF / IME 操作を実行しない。

## Windows Raw HID receiver PoC

Windows 側で Vial を閉じてから実行する。

```powershell
py -m pip install hidapi
py script\windows_ime_raw_hid_receiver_poc.py --count 2
```

Pi 側の first slice は legacy `usbd` socket を使った診断 PoC として残っている。
現行既定 owner は `hidloom-hidd` なので、この経路を実運用へ進める場合は
`/tmp/usbd_windows_ime.sock` 相当を `hidloom-hidd` 側へ移植してから有効化する。
下記は legacy PoC を明示的に動かす場合だけ使う。

```bash
sudo systemctl edit usbd
# [Service]
# Environment=USBD_WINDOWS_IME_SOCKET_ENABLED=1

sudo systemctl restart usbd
python3 script/send_windows_ime_raw_hid_frame.py KC_HENKAN
```

PoC は `SendInput` / TSF / IME API を呼ばず、受信 frame を表示するだけにする。

## 内側の入力 report

`daemon/logicd/windows_ime_custom_hid.py` の encoder と同じ形式を使う。

| byte | meaning |
| --- | --- |
| 0 | magic `0xC1` |
| 1 | version `0x01` |
| 2 | command id |
| 3 | flags。bit0 が press |
| 4 | sequence id low |
| 5 | sequence id high |
| 6 | reserved |
| 7 | xor checksum over byte 0..6 |

## PoC の表示項目

- device path or device name
- raw bytes
- command id
- press / release
- sequence id
- checksum ok / ng
- timestamp

## command id の表示名

| command id | label |
| --- | --- |
| `0x10` | INT4 candidate |
| `0x11` | INT5 candidate |
| `0x12` | LANG1 candidate |
| `0x13` | LANG2 candidate |
| `0x20` | HENKAN candidate |
| `0x21` | MUHENKAN candidate |

## 合格条件

- [x] receiver が target device を開ける。
- [x] press と release の両方を表示できる。
- [x] sequence id が Pi 側 report と一致する。
- checksum error を検出できる。
- 受信だけの状態で IME や active application に副作用がない。

2026-06-10:

- Windows test hostでreceiverがMI_01を開けた。
- Pi 側から `KC_HENKAN` / `KC_MUHENKAN` を送信し、
  `HENKAN candidate` / `MUHENKAN candidate` の press / release が表示された。
- この段階では IME 注入は行っていない。

## まだしないこと

- `SendInput` を呼ばない。
- TSF / IME API を呼ばない。
- keyboard event として注入しない。
- receiver から Pi へ status を返さない。

## 次に進む条件

helper アプリなしで使える標準 keyboard HID route を再検証する。Raw HID receiver は
「Pi から Windows へ別経路のデータは届く」ことを確認する診断材料としてのみ扱う。
