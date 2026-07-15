# Windows split keyboard identity real-device runbook

更新日: 2026-06-12

Windows IME / JIS keyboard identity route を実機で再開する時の手順です。

実機作業の固定入口は private workspace reference *(omitted from public export)* です。
この文書は、Windows host で `KC_HENKAN` / `KC_MUHENKAN` を helper アプリなしに使うため、
JIS 認識、US override、composite interface split を順に確認する runbook です。

2026-06-10 以降、Windows 側 helper アプリを通常利用の前提にしない。
Raw HID / custom HID receiver は診断用に留め、優先確認は standard keyboard HID と
US sub keyboard interface split に置く。

2026-06-12 時点の通常 UX 方針:

- Windows helperless 通常 UX は `KC_LANG1` / `KC_LANG2` を ImeOn/ImeOff として使う。
- `Alt + KC_KANA` / `Alt + KC_HENKAN` は Microsoft IME 側の該当設定を明示した host profile fallback に留める。
- global JIS layout は advanced profile として扱う。
- dedicated `KC_HENKAN` / `KC_MUHENKAN` 単体は Windows 通常 UX に採用しない。
- US sub keyboard interface / `0x87`-`0x98` route は Windows 解決策ではなく、別 OS 確認用として残す。

## 前提

- 現行 USB keyboard descriptor は Keyboard/Keypad usage `0x00`-`0xFF` を許可済み。
- `KC_HENKAN` は HID usage `0x8A`、`KC_MUHENKAN` は `0x8B` として出せる。
- Windows の global hardware keyboard layout を JIS / Japanese 側へ切り替えると、
  `KC_HENKAN` / `KC_MUHENKAN` は変換 / 無変換として有効になった。
- Windows の「接続済みキーボード レイアウトを使用する」または US 寄りの状態では、
  `KC_HENKAN` / `KC_MUHENKAN` は効かなかった。
- Microsoft IME の該当設定が ON の時、`Alt + KC_KANA` と `Alt + KC_HENKAN` は
  どちらもかな入力 / ローマ字入力 toggle として動作した。
- Kana LED bit は、かな入力 ON 直後ではなく、その後に 1 key 入力した時点で反応する場合がある。
  IME かな入力 toggle の即時 source of truth にはしない。
- `OverrideKeyboardType` / `OverrideKeyboardSubtype` は keyboard 側の HID report で
  直接申告する値ではなく、Windows 側の device instance registry / INF 設定として扱う。
  Zenn の JIS/US 共存事例でも、system layout を「接続済みキーボードレイアウトを使用する」にし、
  対象 keyboard device instance の `Device Parameters` へ `OverrideKeyboardType` /
  `OverrideKeyboardSubtype` を追加している。

## 今日の確認順

1. **Baseline**: 現在の connected layout / US 寄り状態で、main keyboard の挙動と device instance を記録する。
2. **作戦 A**: Windows に JIS として効く状態を作り、その上で対象 device instance へ US override を重ねられるか見る。
3. **作戦 B**: main keyboard と sub keyboard を composite 内で分け、片側だけ JIS override にできるかを見る。
4. **Rollback**: Windows layout / registry override / Pi gadget を元に戻せることを確認する。

作戦 A が通るなら、1つの device identity で「JIS key は効くが文字配列は US」を作れる可能性がある。
作戦 B が通るなら、main typing は US、IME 専用 interface は JIS として分離できる可能性がある。

## Baseline

### Pi 側

1. latest `main` であることを確認する。

```bash
git status -sb
git rev-parse --short HEAD
```

2. USB endpoint と descriptor を記録する。

```bash
ls -l /dev/hidg0 /dev/hidg1
test ! -e /dev/hidg2 || ls -l /dev/hidg2
test ! -e /dev/hidg4 || ls -l /dev/hidg4
od -An -tx1 -v /sys/kernel/config/usb_gadget/cqa02303v5/functions/hid.usb0/report_desc
```

3. 標準 keyboard report の dry-run を確認する。

```bash
python3 script/send_standard_keyboard_report.py KC_HENKAN --dry-run
python3 script/send_standard_keyboard_report.py KC_MUHENKAN --dry-run
python3 script/send_standard_keyboard_report.py KC_LANG1 --dry-run
python3 script/send_standard_keyboard_report.py KC_LANG2 --dry-run
```

期待値:

```text
KC_HENKAN   press=0100008a0000000000 release=010000000000000000
KC_MUHENKAN press=0100008b0000000000 release=010000000000000000
KC_LANG1    press=010000900000000000 release=010000000000000000
KC_LANG2    press=010000910000000000 release=010000000000000000
```

現在の `/dev/hidg0` は keyboard / mouse / consumer control の multi-report HID なので、
live USB へ送る report は先頭に keyboard Report ID `0x01` を付ける。
古い dedicated keyboard endpoint を直接見る時だけ `--no-report-id` を使う。
`hidloom-hidd` / legacy `usbd` compatible USB HID report broker を有効にした構成では、通常 smoke は `--transport auto` のまま
broker socket 経由で送り、`--transport direct --device /dev/hidg0` は Report ID 付き direct path の診断に限定する。

4. 送信 report の診断ログを有効にする場合は、`logicd-companion` に環境変数を追加して再起動する。

```bash
sudo systemctl edit logicd-companion
```

drop-in:

```ini
[Service]
Environment=LOGICD_HID_REPORT_LOG=1
```

反映:

```bash
sudo systemctl daemon-reload
sudo systemctl restart logicd-companion
journalctl -u logicd-companion -f
```

有効時は、USB gadget へ書く report ごとに次の形式で `len` と `hex` が出る。

```text
HID gadget write label=auto path=/dev/hidg0 len=9 hex=0100008a0000000000
```

通常運用へ戻す時は drop-in を削除する。

```bash
sudo systemctl revert logicd-companion
sudo systemctl daemon-reload
sudo systemctl restart logicd-companion
```

5. broker 経由の live smoke を行う場合は、現行 owner の `hidloom-hidd` と
   `hidloom-logicd-core.service` / `logicd-companion.service` が active であることを確認する。

```bash
systemctl is-active hidloom-hidd.service hidloom-logicd-core.service logicd-companion.service matrixd.service
systemctl is-active usbd.service || true
ls -l /tmp/usbd_hid_reports.sock /dev/hidg0 /dev/hidg1 /dev/hidg2
journalctl -u hidloom-hidd -u hidloom-logicd-core -u logicd-companion -f
```

### Windows 側

1. Device Manager で cqa02303v5 の keyboard device instance path を控える。
   `VID_1D6B&PID_0105` と `MI_00` を目印にする。
2. PowerShell 管理者で keyboard device の一覧を控える。

```powershell
Get-PnpDevice -Class Keyboard | Format-Table -AutoSize
Get-PnpDevice -PresentOnly | Where-Object InstanceId -like '*VID_1D6B*PID_0105*' | Format-List
```

3. 現在の Windows 設定を控える。
   - 設定 > 時刻と言語 > 言語と地域 > Microsoft IME > 全般
   - ハードウェアキーボードレイアウト
   - 「接続済みキーボード レイアウトを使用する」か、JIS / Japanese 側か
   - 「ハードウェア キーボードでかな入力を使う」
   - 「かな入力/ローマ字入力を Alt + カタカナひらがなローマ字キーで切り替える」

## 作戦 A: JIS 認識 + US override

目的は、Windows が JIS keyboard として処理する状態で `KC_HENKAN` / `KC_MUHENKAN` を有効にし、
その device instance に US 101/102 override を重ねた時、文字配列だけ US に戻せるかを見ること。

### A-1. JIS 側で再現確認

1. Windows のハードウェアキーボードレイアウトを JIS / Japanese 側にする。
2. Windows を再起動する。
3. Pi から標準 keyboard report を送る。compatible USB HID report broker が有効なら、既定の
   `--transport auto` で broker socket 経由になる。`/dev/hidg0` へ直接書く確認は
   `--transport direct --device /dev/hidg0` を明示した診断時だけにする。

```bash
python3 script/send_standard_keyboard_report.py KC_HENKAN
python3 script/send_standard_keyboard_report.py KC_MUHENKAN
python3 script/send_standard_keyboard_report.py KC_LANG1
python3 script/send_standard_keyboard_report.py KC_LANG2
```

4. 見ること:
   - `KC_HENKAN` が変換として効く。
   - `KC_MUHENKAN` が無変換として効く。
   - `KC_LANG1` / `KC_LANG2` が ImeOn/ImeOff として効く。
   - Caps が Caps Lock ではなく IME / 全角半角系へ寄るか。
   - Kana LED bit が返るか。返らない前提だが、log は見る。

### A-2. US override を重ねる

対象 device instance の `Device Parameters` に US 101/102 相当を設定する。
registry は Windows 側の危険領域なので、必ず対象 instance path を記録し、cqa02303v5 device だけに限定する。

概念値:

```text
OverrideKeyboardType    REG_DWORD  7
OverrideKeyboardSubtype REG_DWORD  0
```

実際の registry path は Device Manager で控えた instance path に対応する。
例:

```text
HKLM\SYSTEM\CurrentControlSet\Enum\HID\VID_1D6B&PID_0105&MI_00\...\Device Parameters
```

PowerShell / reg.exe で入れる場合は、`...\Device Parameters` までの path を実機の値に置き換える。

```powershell
reg add "HKLM\SYSTEM\CurrentControlSet\Enum\HID\VID_1D6B&PID_0105&MI_00\...\Device Parameters" /v OverrideKeyboardType /t REG_DWORD /d 7 /f
reg add "HKLM\SYSTEM\CurrentControlSet\Enum\HID\VID_1D6B&PID_0105&MI_00\...\Device Parameters" /v OverrideKeyboardSubtype /t REG_DWORD /d 0 /f
```

設定後、Windows を再起動する。

### A-3. 判定

| 観点 | 期待 |
| --- | --- |
| 変換 / 無変換 | `KC_HENKAN` / `KC_MUHENKAN` が JIS 時と同じく効く |
| 文字配列 | main typing / symbol layout が US に戻る |
| LANG1 / LANG2 | ImeOn/ImeOff として引き続き効く |
| Alt + KANA / HENKAN | Microsoft IME 設定が ON の時だけ、かな入力 / ローマ字入力 toggle fallback として効く |
| Caps | Caps Lock と IME 切替のどちらに寄るか記録する |
| Kana LED | かな入力 ON 後の次キー入力で返れば advisory state、返らなければ使わない |

A-3 が通れば、次はこの override を手動 registry ではなく extension INF で配れるかを検討する。
A-3 が通らない場合は、1 device での「JIS key 有効 + US symbol layout」は難しいと判断し、作戦 B へ進む。

## 作戦 B: JIS main + US sub composite

目的は、main keyboard を US profile のまま維持しつつ、追加 keyboard interface だけを
Windows 側で JIS / JP 106-109 として扱えるか確認すること。

INF 化は可能だが、Windows では INF が driver package として扱われるため、通常運用では
catalog 生成と署名がネックになる。まず `.reg` で `MI_02` の override が効くことを確認し、
効いた場合だけ extension INF 化を検討する。

2026-06-11 の実機結果では、`HID\...\MI_02` keyboard child と `USB\...\MI_02` parent の両方へ
`OverrideKeyboardType=7` / `OverrideKeyboardSubtype=2` を入れ、JP 側を boot keyboard に寄せても
`KC_HENKAN` / `KC_MUHENKAN` は効かなかった。以後この runbook は再現確認用として残し、
通常機能化の本命にはしない。最後に `LOGICD_USB_SPLIT_KEYBOARD_ROUTE=all` で全 keyboard report を
JP 側 `/dev/hidg2` へ送っても Windows は US 配列として動いたため、Windows での失敗原因は
送信 endpoint ではなく layout 判定 / override 適用範囲側にある。

現在の実機設定では、全キーではなく JP109/IME 系だけを JP 側へルートする。
対象は Keyboard/Keypad usage `0x87`-`0x98` で、`KC_RO`、`KC_KANA`、`KC_JYEN`、
`KC_HENKAN`、`KC_MUHENKAN`、`KC_LANG1`-`KC_LANG9` を含む。通常英数字は main US keyboard 側に残す。
この設定は Windows での解決策ではなく、Linux / macOS など別 OS での確認用として扱う。

USB composite device では PID は interface ごとではなく device 全体に1つだけなので、
main US interface だけを別 PID にすることはできない。Windows の device identity を逃がす実験では、
composite 全体の PID を一時的に変える。`setup_usb_gadget.sh` は `HIDLOOM_USB_PRODUCT_ID=0x0106`
のような env override を受け付ける。

例:

```ini
[Service]
Environment=HIDLOOM_USB_PRODUCT_ID=0x0106
```

この場合、Windows 側では `VID_1D6B&PID_0106` として別 device instance になる。
Vial / Raw HID の認識にも影響する可能性があるため、必ず opt-in の一時実験として扱う。

### Pi 側で見ること

1. default 起動で既存 interface が変わっていないことを確認する。

```bash
ls -l /dev/hidg0 /dev/hidg1
```

2. optional US sub keyboard interface を有効化する場合は、必ず opt-in にする。
   `HIDLOOM_USB_US_SUB_KEYBOARD=1` または `settings.usb_split_keyboard.enabled=true` の時だけ
   `hid.usb2` / `/dev/hidg2` を作る。既存の vendor-defined `windows_ime_custom_hid` と同時に有効化しない。

3. opt-in 後、追加 keyboard interface が見えるか確認する。

```bash
ls -l /dev/hidg0 /dev/hidg1 /dev/hidg2
```

4. 既存 endpoint smoke を先に行う。

- `/dev/hidg0`: main keyboard / mouse / consumer control multi-report
- `/dev/hidg1`: Vial Raw HID
- `/dev/hidg2`: US sub keyboard candidate

### Windows 側で見ること

1. Device Manager で keyboard device instance path を控える。
   `MI_00` 相当が main keyboard、追加 interface が `MI_02` 相当として別 keyboard instance になっているかを見る。
2. 追加 interface 側だけの `Device Parameters` に次を設定する。

```text
OverrideKeyboardType    REG_DWORD  7
OverrideKeyboardSubtype REG_DWORD  2
```

   手入力する場合は値名を `Override...` にする。`KeyboardTypeOverride` ではない。
   `.reg` を作る場合は、Device Manager でコピーした instance path を次の helper に渡す。

```bash
python3 build/generators/make_windows_keyboard_layout_override_reg.py \
  'HID\VID_1D6B&PID_0105&MI_02\...' \
  --layout jp_106 \
  --output windows-jp-ime-mi02.reg
```

   生成した `.reg` は Windows 上で実行する。

   同じ設定を INF 雛形にする場合は、`デバイス インスタンス パス` ではなく
   `ハードウェア ID` を使う。例:

```bash
python3 build/generators/make_windows_keyboard_layout_override_inf.py \
  'HID\VID_1D6B&PID_0105&MI_02' \
  --layout jp_106 \
  --extension-id 11111111-2222-3333-4444-555555555555 \
  --output hidloom-jp-ime-keyboard-layout-extension.inf
```

   生成される INF は extension INF の実験用雛形で、通常の Windows へ入れるには
   WDK の `infverif` / `inf2cat` 相当で検証し、catalog に署名する必要がある。
3. Windows を再起動する。
4. main keyboard 側で US symbol layout が変わっていないことを確認する。
5. US sub keyboard interface から JP109/IME 系 usage を送る。
   古い実験時点の `logicd` は `0x87`-`0x98` を `kind=us_sub_keyboard` として `/dev/hidg2` へ送っていた。
   現在の broker kind 名は `us_sub_keyboard`。
   代表例は `KC_RO`、`KC_KANA`、`KC_JYEN`、`KC_HENKAN`、`KC_MUHENKAN`、
   `KC_LANG1`-`KC_LANG9`。
6. `Alt + KC_KANA` / `Alt + KC_HENKAN` で IME かな入力が toggle するかを見る。
7. host LED log で Kana bit (`0x10`) が返るかを見る。ただし、IME かな入力 toggle と
   Kana LED が即時同期する保証はないため、返っても advisory state として扱う。
   かな入力 ON 直後に返らない場合は、続けて 1 key 入力してから Kana bit が変わるかを見る。

### 判定

| 結果 | 判断 |
| --- | --- |
| 追加 interface だけ JIS override が効き、main US layout が変わらない | extension INF による非常駐設定配布を検討する |
| 追加 interface が別 keyboard instance にならない | product_id / serial suffix で identity を分ける案へ戻る |
| JIS override が main keyboard まで巻き込む | composite split は通常運用に採用しない |
| 追加 interface からの `KC_HENKAN` / `KC_MUHENKAN` が効かない | Windows では dedicated 変換 / 無変換は fallback 扱いに戻す。別 OS では `0x87`-`0x98` route を継続確認する |
| `/dev/hidg2` を作れない | `<keyboard-host>` 既知制約として、product_id / serial profile 分離または既存 keyboard interface の切替実験に戻る |

## Rollback

### Windows

1. 追加した `OverrideKeyboardType` / `OverrideKeyboardSubtype` を削除するか、控えた元値へ戻す。
2. Device Manager で対象 cqa02303v5 keyboard device を uninstall し、USB を抜き差しして再列挙する。
3. ハードウェアキーボードレイアウトを「接続済みキーボード レイアウトを使用する」へ戻す。
4. Windows を再起動する。

### Pi

1. optional interface / custom HID opt-in を無効にする。
2. 通常の gadget 構成へ戻す。

```bash
sudo ./setup_usb_gadget.sh
ls -l /dev/hidg0 /dev/hidg1
test ! -e /dev/hidg2 || ls -l /dev/hidg2
test ! -e /dev/hidg4 || ls -l /dev/hidg4
```

3. 既存 smoke を見る。

- keyboard input
- mouse input
- Vial Raw HID
- consumer control

## 診断用 Raw / custom HID

この節は helper アプリ不要 route の本筋ではなく、Windows 側に任意 frame が届くかを見る診断用。

1. Pi 側で descriptor 候補を確認する。

```bash
python3 script/describe_windows_ime_custom_hid_descriptor.py
```

2. 出力された `hid.usb4` / `/dev/hidg4` / report length / descriptor を記録する。
3. 一時的な opt-in として `HIDLOOM_WINDOWS_IME_CUSTOM_HID=1` 付きで USB gadget を再生成する。
   `setup_usb_gadget.sh` は既存 gadget を壊す前に追加 HID function を probe し、
   拒否された場合は既存 gadget を残して終了する。

```bash
sudo HIDLOOM_WINDOWS_IME_CUSTOM_HID=1 ./setup_usb_gadget.sh
```

4. 既存 endpoint が残っていることを確認する。

```bash
ls -l /dev/hidg0 /dev/hidg1
test ! -e /dev/hidg2 || ls -l /dev/hidg2
```

5. custom HID 追加後に候補 device が見えることを確認する。

```bash
ls -l /dev/hidg4
```

6. Windows 側 receiver PoC では、受信 report を表示するだけにする。

```powershell
py -m pip install hidapi
py script\windows_ime_raw_hid_receiver_poc.py --count 2
```
7. Pi 側から Raw HID multiplex report を送る。

```bash
python3 script/send_windows_ime_raw_hid_frame.py KC_HENKAN
python3 script/send_windows_ime_raw_hid_frame.py KC_MUHENKAN
```

8. 既存機能の smoke を先に見る。

- keyboard input
- mouse input
- Vial Raw HID
- consumer control

## 合格条件

- 作戦 A では、JIS で `KC_HENKAN` / `KC_MUHENKAN` が効き、US override 後の文字配列差が記録される。
- 作戦 B では、main keyboard と US sub keyboard interface が別 Windows device instance として見えるかが記録される。
- どちらの作戦でも既存 keyboard / mouse / Vial / consumer control が壊れない。
- 診断用 Raw / custom HID を使う場合は、Windows 側で report 表示までに留め、IME 注入はしない。

## 失敗時に見ること

- Windows が device を再認識し直して Vial が見えなくなっていないか。
- `/dev/hidg1` Raw HID / Vial の report length が変わっていないか。
- `hid.usb2` を追加したことで symlink 順や device path を誤っていないか。
- custom HID receiver が report size 8 byte 前提で読んでいるか。

## 次に進む条件

作戦 A が通った場合は、US override を手動 registry から extension INF へ移せるかを検討する。
作戦 B の first slice は実装済み。通った場合は、JP 側 device instance への registry override を
extension INF で非常駐配布できるかを検討する。
どちらも通らない場合は、dedicated 変換 / 無変換 key は Windows helperless route の通常機能に採用せず、
`KC_LANG1` / `KC_LANG2`、`KC_SPC`、`KC_ENTER`、`KC_ESC` を中心に fallback UX を組む。
