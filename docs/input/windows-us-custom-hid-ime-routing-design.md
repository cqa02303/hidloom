# Windows US custom HID IME routing design

更新日: 2026-06-13

Windows 11 の US keyboard 設定で、標準 keyboard HID report の `INT4` / `INT5` / `LANG1` / `LANG2` が期待通り IME 操作として処理されない場合の代替設計です。

2026-06-10 の方針更新: Windows 側 helper アプリを通常利用の前提にしない。custom / Raw HID
receiver route は診断用または最終 fallback に留め、まず標準 keyboard HID route で
helper なしに成立する条件を再検証する。

## 結論

2026-06-12 方針固定: Windows helperless の通常 UX は `KC_LANG1` / `KC_LANG2`
による ImeOn/ImeOff を第一候補にする。`Alt + KC_KANA` と `Alt + KC_HENKAN` は
Microsoft IME 側の「かな入力/ローマ字入力を Alt + カタカナひらがなローマ字キーで切り替える」
設定が明示されている host profile だけで使う fallback とし、global JIS layout は上級者向け
profile として扱う。Windows では dedicated `KC_HENKAN` / `KC_MUHENKAN` 単体を helperless
通常機能に採用しない。US sub keyboard interface と `0x87`-`0x98` route は、
Windows 解決策ではなく Linux / macOS など別 OS の確認用に残す。

2026-06-13 更新: Windows custom INF により、同じ USB composite device 内で
main keyboard を JIS 106/109、sub keyboard を US 101/102 として同時に保持できることを確認した。
現在の実験構成では、通常キーと `KC_LANG1` / `KC_LANG2` は US sub keyboard へ、
`KC_KANA`、変換 / 無変換、JIS 固有キーは JIS main keyboard へ送る
`jis_special_us_default` route を採用する。
したがって、Windows 向けの JIS / US 分離は Raw HID helper ではなく custom INF + dual keyboard
interface + compatible broker route (`hidloom-hidd` current owner、legacy `usbd` rollback owner) を source of truth にする。

標準 keyboard HID route を first target に戻す。Microsoft の
「Keyboard Japan - ImeOn / ImeOff implementation」は、ImeOn を Keyboard `LANG1`
(`0x90`) から `VK_IME_ON` (`0x16`) へ、ImeOff を Keyboard `LANG2` (`0x91`) から
`VK_IME_OFF` (`0x1A`) へ転送するものとして定義している。

`KC_LANG1` / `KC_LANG2` は既に ImeOn/ImeOff として使えている。descriptor は `0x00`-`0xFF` の
Keyboard/Keypad usage を許可済みなので、次は実際の press/release report が
`KC_HENKAN` / `KC_MUHENKAN` として host に届いているか、Windows が International4/5 を
変換 / 無変換として扱う条件があるかを USB / BLE の両方で切り分ける。

Microsoft の「Keyboard Input Overview」には、Windows が認識する scan code set として
Keyboard International4 (`0x8A`) -> Scan 1 Make `0x79`、Keyboard International5
(`0x8B`) -> Scan 1 Make `0x7B` が記載されている。つまり `0x8A` / `0x8B` は
Windows 側で未知の HID usage ではない。次の焦点は、Windows の keyboard layout / IME が
その scan code を `VK_CONVERT` / `VK_NONCONVERT` として扱う条件にある。

vendor-defined custom HID endpoint と Windows receiver は、helper アプリが必要になるため
通常利用の採用候補から外す。Raw HID multiplex は「Windows 側に任意 frame が届く」ことを
確認する診断用として残す。

2026-06-10 追加方針: Windows の global hardware keyboard layout を JIS / Japanese 側へ
切り替えると `KC_HENKAN` / `KC_MUHENKAN` は有効になった。したがって次は
global layout を変えるのではなく、USB composite 内に US sub 専用 keyboard interface を分け、
その device instance だけに JIS / JP 106-109 override を適用できるかを確認する。
`OverrideKeyboardType` / `OverrideKeyboardSubtype` は HID report から直接申告する値ではなく、
Windows 側の device instance / INF 設定として扱う。

2026-06-11 結論: `hid.usb2` / `/dev/hidg2` の US sub keyboard interface を追加し、
Windows では `MI_02` が `kbdhid` / Keyboard として列挙された。しかし `MI_02` keyboard child と
USB parent の `Device Parameters` に `OverrideKeyboardType=7` / `OverrideKeyboardSubtype=2` を入れても、
JP 側を boot keyboard にしても、全 keyboard report を `/dev/hidg2` へ流しても、
Windows は US 配列として動き、`KC_HENKAN` / `KC_MUHENKAN` は変換 / 無変換として効かなかった。
別 OS 検証用として、`logicd` は Keyboard/Keypad usage `0x87`-`0x98` を JP 側
`/dev/hidg2` へルートする。

## 背景

Windows の virtual-key code には IME 操作用の `VK_KANA`、`VK_IME_ON`、`VK_IME_OFF`、`VK_CONVERT`、`VK_NONCONVERT` がある。一方、US keyboard layout の標準 HID keyboard report から `INT4` / `INT5` / `LANG1` / `LANG2` を送っても、期待した IME 操作として扱われない場合がある。

Raw Input は、アプリが `RegisterRawInputDevices` で登録して `WM_INPUT` を受ける仕組みなので、custom HID report は Windows 側 receiver がないと実入力にならない。

## 目的

- helper アプリなしで `KC_HENKAN` / `KC_MUHENKAN` が使える条件を探す。
- 通常 keycode と IME 系 keycode は、まず既存 keyboard endpoint へ送る。
- USB / BLE descriptor、実 report bytes、Windows の keyboard layout / IME 設定のどこで止まるか切り分ける。
- custom HID receiver route は診断用に限定し、通常 route へ自動接続しない。

## 現状整理

| 項目 | 状況 | 判断 |
| --- | --- | --- |
| `KC_LANG1` / `KC_LANG2` | Microsoft の ImeOn/ImeOff ガイドで HID `0x90` / `0x91` から `VK_IME_ON` / `VK_IME_OFF` への転送が定義されている。実機でも ImeOn/ImeOff として使用可能 | 解決済み。変換 / 無変換の未解決範囲から外す |
| `KC_HENKAN` / `KC_MUHENKAN` | `logicd` の keycode table では `0x8A` / `0x8B`。Microsoft の Keyboard Input Overview では International4 / International5 が Windows の recognized scan code set に含まれる | Windows global JIS layout では効いたが、US layout / per-interface JP override / JP thin keyboard route では効かなかった。Windows helperless 通常 UX には採用しない |
| `Alt + ひらがな` / `Alt + 変換` | Microsoft IME 設定「かな入力/ローマ字入力を Alt + カタカナひらがなローマ字キーで切り替える」を ON にすると、`Alt + KC_KANA` と `Alt + KC_HENKAN` の両方でかな入力 / ローマ字入力の切替として動作した | host profile で当該設定を明示した時だけ fallback 候補にする。状態観測は Kana LED に依存しない |
| Host LED `Kana` bit | USB / BLE keyboard descriptor は LED Output usage `Kana` まで宣言済み。`logicd.host_led_output` も `kana` bit を扱える | 2026-06-13 の JIS main INF 構成で、Windows host lock state toggle に対する Kana bit `0x10` を `/dev/hidg0` で受信確認済み。2026-06-15 の追加観測では、IME かな入力を ON にした直後ではなく、その後に 1 key 入力すると Kana bit が反応する。Microsoft IME 内部状態との即時同期は未保証なので advisory state として扱う |
| JIS / Japanese keyboard identity | `config/default/config.json` の `device.hid_country_code` は現在 `0`。過去調査では configfs HID function が `country_code` / `bCountryCode` 属性を公開しない場合がある | Windows のハードウェアキーボードレイアウトを JIS / Japanese 側へ切り替えると、`KC_HENKAN` / `KC_MUHENKAN` が変換 / 無変換として有効になった。Kana LED は次の通常キー入力後に遅れて反映される場合がある |
| USB keyboard descriptor | Keyboard/Keypad usage `0x00`-`0xFF` を許可済み | descriptor 上は `0x8A` / `0x8B` を出せる |
| Dual keyboard interface | main `/dev/hidg0` と sub `/dev/hidg2` を別 keyboard instance として列挙する | Custom INF で main は JIS 106/109、sub は US 101/102 として認識成功。通常キーと `KC_LANG1` / `KC_LANG2` は US sub、`KC_KANA`、JIS 固有キー、変換 / 無変換は JIS main へ route する |
| BLE Report Map | Keyboard/Keypad usage `0x00`-`0xFF` を許可済み | descriptor 上は `0x8A` / `0x8B` を出せる |
| Raw HID multiplex | Windows test hostで`HENKAN` / `MUHENKAN`のpress / release受信表示まで確認済み | Windowsへ別経路のframeは届くが、helperアプリが必要なため通常利用では採用しない |

## 次に確認する方式

目的は、helper アプリなしで `KC_HENKAN` / `KC_MUHENKAN` が Windows の変換 / 無変換として届く条件を特定することだった。
2026-06-12 時点では Windows の通常 UX 方針は決定済みで、以下の手順は再現確認用として残す。

1. Pi 側で標準 USB keyboard report bytes を固定する。

   ```bash
   python3 script/send_standard_keyboard_report.py KC_HENKAN --dry-run
   python3 script/send_standard_keyboard_report.py KC_MUHENKAN --dry-run
   ```

   期待値:

   ```text
   KC_HENKAN   press=0100008a0000000000 release=010000000000000000
   KC_MUHENKAN press=0100008b0000000000 release=010000000000000000
   ```

   現在の `/dev/hidg0` は keyboard / mouse / consumer control の multi-report HID なので、
   live USB へ送る report は先頭に keyboard Report ID `0x01` を付ける。
   古い dedicated keyboard endpoint を直接見る時だけ `--no-report-id` を使う。
   `hidloom-hidd` / legacy `usbd` compatible USB HID report broker を有効にした構成では、通常 smoke は `--transport auto` のまま
   broker socket 経由で送り、direct write は `--transport direct --device /dev/hidg0` を明示した診断に限定する。

2. Windows 側では helper receiver を起動しない。入力欄またはメモ帳にフォーカスし、Microsoft IME を有効にしておく。

3. USB 接続で標準 keyboard report を送る。

   ```bash
   python3 script/send_standard_keyboard_report.py KC_HENKAN
   python3 script/send_standard_keyboard_report.py KC_MUHENKAN
   ```

   broker socket が有効なら `--transport auto` が broker 経由を選ぶ。socket が無い構成では従来通り
   Report ID 付き direct write になる。

   見ること:

   - 未確定文字列がある状態で `KC_HENKAN` が次候補 / 変換として働くか。
   - 未確定文字列がある状態で `KC_MUHENKAN` が無変換確定または非変換動作として働くか。
   - 未入力状態で何か visible な副作用があるか。

4. 同じ Windows host で keyboard layout / IME 設定を変えて差を見る。

   - Windows のハードウェア キーボード レイアウトが日本語キーボードか英語キーボードか。
   - Windows のデバイスインスタンス上、この USB gadget が Japanese keyboard として扱われているか。
   - `device.hid_country_code` / `bCountryCode`、USB product / serial、Windows registry layout override の組み合わせで挙動が変わるか。
   - Microsoft IME の「ハードウェア キーボードでかな入力を使う」が ON / OFF のどちらか。
   - Microsoft IME の「かな入力/ローマ字入力を Alt + カタカナひらがなローマ字キーで切り替える」が ON / OFF のどちらか。
   - 上記切替設定が ON の時、物理 `Alt + ひらがな` と USB gadget からの `Alt + KC_KANA` / `Alt + KC_HENKAN` / `Alt + KC_LANG1` の挙動差があるか。
   - Microsoft IME の「以前のバージョンの Microsoft IME を使う」等の compatibility 設定差。
   - `KC_LANG1` / `KC_LANG2` が同じ条件で引き続き ImeOn/ImeOff として効くか。

5. Kana LED output を確認する。

   - USB keyboard descriptor は LED usage `Num Lock`-`Kana` を Output Report として宣言している。
   - `logicd.host_led_output` は `kana` state を bit4 として decode できる。
   - 既定設定は `caps_lock` のみなので、かな状態を使う実験では `host_led_output.states.kana=true` を有効化する。
   - `Alt + KC_KANA` / `Alt + KC_HENKAN` / `Alt + KC_LANG1` や IME 設定 UI でかな入力 / ローマ字入力を切り替えた時に、host LED report の `kana` bit が変わるかを見る。
   - 2026-06-10 の USB 実機確認では、Caps Lock は `report=0x02` / `0x00` が返った一方、
     `Alt + KC_KANA` / `Alt + KC_LANG1` では Kana bit の変化は返らなかった。
   - 同日、Windows UI で手動かな入力 ON/OFF を行った場合も `report=0x00` のみで、
     Kana bit (`0x10`) は返らなかった。
   - 2026-06-15 の追加観測では、かな入力 ON 直後ではなく、その後に 1 key 入力すると
     Kana bit が反応する。したがって LED state は即時 state ではなく、遅延しうる advisory state として扱う。
   - Windows 側のハードウェアキーボードレイアウトを JIS / Japanese 側へ切り替えて再起動すると、
     `KC_HENKAN` / `KC_MUHENKAN` は変換 / 無変換として有効になった。
   - 同条件でも Kana bit は返らなかった。Caps key は Caps Lock LED ではなく IME / 全角半角系の動きになった。
   - `KC_KANA` / `KC_LANG3` / `KC_LANG4` / `KC_LANG5` を送った場合も、新しい LED report は返らず、
     Kana bit (`0x10`) は確認できなかった。

6. BLE でも同じ action を標準 keyboard report として試す。USB と BLE で差が出る場合は、
   Report Map / host pairing cache / Windows の Bluetooth HID path の差として扱う。

7. helper なしで `0x8A` / `0x8B` が変換 / 無変換にならない場合は、
   dedicated 変換 / 無変換 key の通常 route は見送り、IME control UI は `KC_LANG1` / `KC_LANG2`、
   必要に応じて `KC_SPC` / `KC_ENTER` / `KC_ESC` など host-compatible fallback を使う。

## US sub keyboard interface first slice

2026-06-11 に optional US sub keyboard interface の first slice を実装した。
default では live gadget を変えず、opt-in 時だけ US sub keyboard interface を追加する。

### 目的

- main keyboard は既存 US profile のまま残す。
- 追加 interface だけを Windows 側で JIS / JP 106-109 として扱えるか後で確認できる形にする。
- Windows helper アプリを通常利用の前提に戻さない。
- 既存 Raw HID / Vial / mouse / consumer の interface 番号と default 挙動を壊さない。

### first slice

1. optional US sub keyboard interface の descriptor 方針を固定した。
   - 実装名は `hid.usb2` / `/dev/hidg2`。
   - 8 byte keyboard input report は no Report ID の standard keyboard report にする。
   - LED Output usage は `Num Lock`-`Kana` まで宣言するが、Kana LED は advisory 扱いに留める。
   - 初期実験では `protocol=0` / `subclass=0` の non-boot keyboard にしたが、
     `Service=kbdhid` / `Class=Keyboard` として列挙されても `OverrideKeyboardType=7` /
     `OverrideKeyboardSubtype=2` が変換 / 無変換に効かなかった。
   - 次の実験では JP 側だけ `protocol=1` / `subclass=1` の boot keyboard に寄せる。
2. `setup_usb_gadget.sh` へ default-on 変更は入れない。
   - 追加する場合も opt-in env / config gate に限定する。
   - 既存の `windows_ime_custom_hid` vendor-defined Raw HID opt-in とは同時に有効化しない。
3. 静的テストを追加した。
   - default では `hid.usb2` が作られないこと。
   - opt-in 時の descriptor が Keyboard/Keypad usage `0x00`-`0xFF` と LED `0x01`-`0x05` を含むこと。
   - existing `hid.usb0` / `hid.usb1` の descriptor が変わらないこと。
   - US sub keyboard interface 用の report bytes が `KC_HENKAN=0x8A` / `KC_MUHENKAN=0x8B` を送れること。
4. 実機確認用 runbook を更新した。
   - Windows Device Manager で `MI_02` 相当の device instance path を控える。
   - その instance だけに `OverrideKeyboardType=7` / `OverrideKeyboardSubtype=2` を設定する。
   - main keyboard 側の US symbol layout が巻き込まれていないか確認する。
   - `KC_HENKAN` / `KC_MUHENKAN` / `KC_KANA` / `KC_LANG1` / `KC_LANG2` を US sub interface から送って反応を見る。
5. per-interface registry override が効いた場合だけ、extension INF で非常駐に設定を配る案へ進む。

### 2026-06-13 custom INF で確認済み

| 観点 | 結果 |
| --- | --- |
| Windows device instance | main keyboard と sub keyboard が別 instance として見える |
| custom INF binding | main `MI_00&Col01` は JIS 106/109、sub `MI_02` は US 101/102 として bind できる |
| main JIS layout | `KC_EQUAL` / `KC_LBRACKET` / `KC_QUOTE` などが JIS 記号として解釈される |
| sub US layout | 同じ usage が US 記号として解釈される |
| runtime route | `jis_special_us_default` で通常キーと `KC_LANG1` / `KC_LANG2` は sub、`KC_KANA`、JIS 固有キー、変換 / 無変換は main へ送る |
| Kana LED | JIS main で host Kana bit `0x10` を受信できる |

### 古い per-interface override 実験の結果

| 観点 | 期待 | NG の場合 |
| --- | --- | --- |
| Windows device instance | main keyboard と US sub keyboard が別 instance として見える | product_id / serial suffix で device identity 分離へ戻る |
| per-interface override | US sub keyboard 側だけ `OverrideKeyboardType=7` / `OverrideKeyboardSubtype=2` が効く | global layout 依存として扱い、通常運用には採用しない |
| main US layout | 既存 typing / symbol layout が変わらない | interface 分離案は中止 |
| 変換 / 無変換 | US sub interface から `0x8A` / `0x8B` が効く | dedicated key は fallback 扱いに戻す |
| Kana LED | 返れば advisory state として記録 | かな入力 ON 後の次キー入力で遅延反映される場合があるため、即時 hard dependency にはしない |

## フリック / 和文 Morse への意味

今回の `Alt + ひらがな` 観測と Kana LED output 候補は、フリック入力や和文 Morse の実装にとって大きい。

- helper アプリなしで host IME のかな入力 / ローマ字入力を切り替えられる可能性があるが、
  Windows では host profile 明示時の fallback に留める。
- host が Kana LED output を返すなら、keyboard 側が現在のかな入力状態を推定できる。追加観測では、かな入力 ON 直後ではなく、その後に 1 key 入力した時点で Kana bit が反応するため、即時同期ではなく遅延 advisory state として扱う。
- Windows のハードウェアキーボードレイアウトを JIS / Japanese 側へ切り替えると、
  `KC_HENKAN` / `KC_MUHENKAN` は有効になった。split keyboard identity を通常運用へ入れるなら、
  USB identity / registry override / product-id 分離まで含めて US profile と分ける。
- かな入力状態を観測できれば、フリック / 和文 Morse は「かな入力へ寄せる」「ローマ字入力へ戻す」「状態不明なら警告 / fallback」といった安全な UX を作れる。
- 一方で、Kana LED bit が Microsoft IME の内部状態と常に同期する保証は未確認なので、最初は advisory state として扱い、自動変換の hard dependency にはしない。

## 構成案

```text
logicd action resolver
  ├─ normal keyboard keycode -> USB/BLE keyboard endpoint
  ├─ IME keyboard keycode    -> USB/BLE keyboard endpoint
  ├─ mouse keycode           -> USB HID mouse endpoint
  └─ consumer keycode        -> USB/BLE consumer endpoint

diagnostic only:
  win_ime_control keycode -> Raw HID multiplex -> Windows display-only receiver
```

## 自動 route 対象候補

| action | 標準 HID で確認する usage |
| --- | --- |
| `KC_LANG1` | Keyboard LANG1 (`0x90`)。Microsoft の ImeOn HID usage。既に使用可能 |
| `KC_LANG2` | Keyboard LANG2 (`0x91`)。Microsoft の ImeOff HID usage。既に使用可能 |
| `KC_HENKAN` / `KC_HENK` | Keyboard International4 (`0x8A`) |
| `KC_MUHENKAN` / `KC_MHEN` | Keyboard International5 (`0x8B`) |
| `KC_KANA` | Keyboard International2 (`0x88`)。Kana Lock / Kana LED 実験のため、`jis_special_us_default` では JIS main `/dev/hidg0` へ送る |

実際の挙動は Windows の keyboard layout / IME 設定に依存する。Pi 側ではまず
標準 keyboard report の usage id と press/release が正しく出ることを固定する。

## Pi 側の実装方針

- USB gadget keyboard descriptor は Keyboard/Keypad usage `0x00`-`0xFF` を許可する。
- BLE HID Report Map も Keyboard/Keypad usage `0x00`-`0xFF` を許可する。
- `logicd` は `KC_HENKAN` / `KC_MUHENKAN` を標準 keyboard report の 6-key array に入れる。
- host LED output report の `kana` bit は bit4 として扱う。ただし既定の host LED output state は `caps_lock` のみなので、実験時に `kana` を明示有効化する。
- Windows helperless 通常 UX は `KC_LANG1` / `KC_LANG2` を ImeOn/ImeOff として優先する。
- `KC_HENKAN` / `KC_MUHENKAN` 単体は Windows global JIS layout profile 以外では通常 UX に採用しない。
- `Alt + KC_KANA` / `Alt + KC_HENKAN` は Microsoft IME の該当設定を host profile が明示した時だけ fallback 候補にする。
- touch flick / IME control UI では必要に応じて `KC_SPC` / `KC_ENTER` / `KC_ESC`
  など US keyboard compatible fallback も使う。

## Windows 側 receiver 方針

- 通常利用では使わない。
- 診断時だけ custom / Raw HID device を HID API で開き、report の command id、press/release、sequence id を表示する。
- `SendInput` / TSF / IME API は呼ばない。

## 副作用と対策

| リスク | 対策 |
| --- | --- |
| custom HID だけでは OS 標準 keyboard input にならない | 通常利用の候補から外し、診断用に限定する |
| 標準 HID usage が Windows US layout で無視される | 実 report bytes と Windows keyboard layout / IME 設定を分けて確認する |
| helper なしで変換 / 無変換が成立しない | `KC_SPC` / `KC_ENTER` など host-compatible fallback を IME control UI の第一候補にする |
| descriptor 変更で既存 Vial / keyboard / mouse が不安定になる | 既存 endpoint は変えず、新 interface を opt-in 追加する |
| press/release state が stuck する | sequence id、release timeout、output switch / reload clear を入れる |

## first slice

1. 設計と report schema を固定する。
2. USB gadget の custom HID interface を opt-in で生成する dry-run / descriptor text を追加する。
3. `logicd` 側に custom HID route の dry-run backend を追加する。
4. Windows receiver は最小 PoC として Raw Input / HID API で report を表示するだけにする。
5. PoC で受信できても通常利用には採用せず、標準 keyboard HID route の切り分けへ戻る。

## 2026-06-10 remote first slice progress

実機なしでできる first slice として、`daemon/logicd/windows_ime_custom_hid.py` を追加した。

- `KC_INT4` / `KC_INT5` / `KC_LANG1` / `KC_LANG2` / `KC_HENK` / `KC_MHEN` 系 action を custom HID 候補として分類する。
- explicit `host_profile="windows_us_custom_hid_ime"`、route enabled、receiver available が揃う時だけ `enabled=True` になる dry-run plan を返す。
- まだ `/dev/hidg*` は開かない。
- まだ USB gadget descriptor は変更しない。
- まだ Windows receiver は実装しない。
- 8 byte の vendor-defined report 候補を encode / decode できる。
- `script/test_windows_ime_custom_hid.py` で action 分類、blocked reason、press/release report、checksum error を固定した。

## 2026-06-10 remote descriptor dry-run progress

USB gadget の実 descriptor はまだ変更せず、`script/describe_windows_ime_custom_hid_descriptor.py` を追加した。
これは vendor-defined custom HID の診断用メモであり、現在の US sub keyboard interface
`hid.usb2` / `/dev/hidg2` とは別系統。

- future opt-in interface は `hid.usb4` / `/dev/hidg4` 候補にする。
- report length は 8 byte。
- vendor-defined usage page `0xFF70`、usage `0x01`、8 byte input report、8 byte output report の descriptor 候補を出力する。
- output report は将来の receiver/status handshake 用に予約し、first implementation は Pi -> host input report だけを前提にする。
- `script/test_windows_ime_custom_hid_descriptor.py` で function 名、device path、report length、descriptor shell literal、input/output report count を固定した。
- `setup_usb_gadget.sh` はまだ変更しない。

## 2026-06-10 USB / BT observation

ユーザー実機確認で、標準 USB keyboard report の `KC_HENKAN` / `KC_MUHENKAN`
と、BLE keyboard report の `KC_LANG1` / `KC_LANG2` が Windows 側で期待通り反応しないことを確認した。
helper アプリを通常利用の前提にしないため、標準 keyboard endpoint で反応しない理由を
改めて切り分ける。

一方で、標準 keyboard endpoint / BLE keyboard endpoint の descriptor は
International / Language 系 usage を host が descriptor 上で拒まないように、
keyboard 6-key array の logical maximum / usage maximum を `0xFF` まで許可する。
この descriptor 許可を helper なし route の前提にし、次は実 report bytes と
Windows 側 layout / IME 設定を分けて確認する。

## remaining tasks

| 項目 | 状態 |
| --- | --- |
| USB/BLE standard HID report bytes | `KC_LANG1` / `KC_LANG2` は `0x90` / `0x91`。`KC_HENKAN` / `KC_MUHENKAN` は `0x8A` / `0x8B` として標準 keyboard report に入る |
| Windows keyboard layout / IME setting dependency | Windows の global hardware keyboard layout を JIS / Japanese 側へ切り替えると `KC_HENKAN` / `KC_MUHENKAN` は変換 / 無変換として効く。US / 接続済み layout では効かない |
| JIS / Japanese keyboard identity dependency | Kana LED はかな入力 ON 後の次キー入力で遅延反映される場合がある。`MI_02` child / parent registry override と USB product string だけでは Windows の変換 / 無変換解釈は変わらなかった |
| Composite US sub keyboard interface | first slice 実装済み。`hid.usb2` / `/dev/hidg2` を opt-in で追加した。手動 registry override では効かなかったが、custom INF で main JIS / sub US の分離に成功したため、現在は `jis_special_us_default` route の実体として使う |
| Raw HID receiver PoC | 診断用として受信表示まで確認済み。通常利用には採用しない |
| SendInput / TSF injection | helper アプリが必要になるため通常利用では見送る |

## 採用判定

`do-not-adopt-for-normal-use` for Raw HID helper route.

custom / Raw HID receiver route は helper アプリが必要になるため通常利用には採用しない。
診断用の受信確認としては有用なので、display-only PoC として残す。
通常利用の Windows JIS / US 分離は custom INF + dual keyboard interface + `jis_special_us_default`
を採用する。

## 参考

- Microsoft Keyboard Japan - ImeOn / ImeOff implementation: `LANG1` (`0x90`) maps to `VK_IME_ON` (`0x16`), and `LANG2` (`0x91`) maps to `VK_IME_OFF` (`0x1A`).
- Microsoft Keyboard Input Overview: Windows recognized scan code set includes Keyboard International4 (`0x8A`) as Scan 1 Make `0x79`, and Keyboard International5 (`0x8B`) as Scan 1 Make `0x7B`.
- Microsoft Raw Input: application must register raw input devices before receiving `WM_INPUT`.
- Microsoft Virtual-Key Codes: `VK_KANA` / `VK_IME_ON` / `VK_IME_OFF` / `VK_CONVERT` / `VK_NONCONVERT` are defined as IME-related virtual keys.
- Microsoft SendInput: input injection is subject to UIPI and existing keyboard state can interfere with generated events.
