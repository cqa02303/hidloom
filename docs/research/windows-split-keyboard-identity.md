# Windows split keyboard identity research

作成日: 2026-06-06

この文書は、同じ HIDloom codebase から出す USB HID keyboard を、
Windows host 側で US 配列として扱ってほしい場合と JP 配列として扱ってほしい場合に分けるための調査メモです。
private workspace reference *(omitted from public export)* の Windows split keyboard / JP 拡張候補へ紐づく判断材料として残します。
2026-06-06 時点で、Vial serial suffix の実機 smoke だけは
private workspace reference *(omitted from public export)* へ先行昇格しました。

2026-06-13 更新: Windows custom INF により、同じ USB composite device 内で
main keyboard を JIS 106/109、sub keyboard を US 101/102 として保持し、
`logicd` route `jis_special_us_default` で通常キーと JIS 固有キーを分離できることを確認した。
このため、Windows split keyboard identity + JP input extension は Wishlist の W3 から完了扱いへ移した。
詳細な VID/PID、INF、実入力、Kana LED の記録は
[windows-jis-keyboard-vid-pid.md](windows-jis-keyboard-vid-pid.md) を見る。

## 背景

現行運用では、日本語 Windows host に対して cqa02303v5 を US keyboard として認識させた上で、
`KC_LANG1` / `KC_LANG2` を IME on/off として使う。
これは Windows の日本語 IME 仕様と矛盾しない。

一方で、和文 Morse や touch flick の日本語入力を進めると、用途によっては host 側に
JP / 106-109 keyboard として扱ってほしい場面が出る。
そのため、以下を同時に満たす必要がある。

- US 認識で使いたい個体 / mode は、Windows の US layout override を維持する。
- JP 認識で使いたい個体 / mode は、Windows の JP layout override を維持する。
- 同じ codebase の複数 keyboard が、Windows 側で意図せず同一 device として混ざらない。
- Vial GUI の検出に必要な USB serial magic は壊さない。
- `KC_LANG1` / `KC_LANG2` は US layout profile でも抑止しない。

## HID / OS 調査結果

### `KC_LANG1` / `KC_LANG2`

`KC_LANG1` / `KC_LANG2` は配列そのものではなく IME control key として扱う。
Windows の日本語 keyboard 向け仕様では、HID Usage Page `0x07` の `Keyboard LANG1`
(`0x90`) が `ImeOn` / `VK_IME_ON`、`Keyboard LANG2` (`0x91`) が
`ImeOff` / `VK_IME_OFF` に対応する。

したがって `host_layout=us` と `ime_control=enabled` は分離する。
US 配列として認識させる profile でも、日本語 IME を使うなら `KC_LANG1` / `KC_LANG2` は
許可対象にする。

### `bCountryCode`

USB HID descriptor には `bCountryCode` があり、localized hardware の country code を表せる。
Japan は `15`、US は `33` などが定義されている。

ただしこれは keyboard layout を host OS に強制設定する命令ではない。
仕様上も「key caps の language を示せる」程度の位置づけで、OS ごとの扱いは保証されない。
そのため、Windows の US / JP 認識切替の主手段にはしない。

2026-06-07 に `config/default/config.json` の `device.hid_country_code` と `setup_usb_gadget.sh` の
条件付き適用 path を追加した。現行実機の configfs HID function では
`country_code` / `bCountryCode` 属性が公開されていないため、非 0 値を指定した場合は
warning を出して適用しない。対応 kernel / gadget function が属性を公開する場合だけ、
`hid.usb0` に指定値を書き込む。

### Extended Keyboard Attributes

HID Usage Tables 1.21 には `Keyboard Physical Layout` と
`Keyboard IETF Language Tag Index` がある。
`Keyboard Physical Layout` には `101 (e.g. US)`、`106 (DOS/V Japan)` が含まれる。

ただし `Keyboard Physical Layout` は印字文字ではなく物理 keyset layout の説明で、
host OS が layout 選択にどう使うかは保証されない。
実装する場合も Feature Report 追加が必要で、現行の boot keyboard report descriptor へ
単純に byte を足す話ではない。
このため、研究候補に留める。

## Windows device identity 方針

Windows は USB device / interface descriptor から device identity を作る。
layout override を安定して分けたい場合は、Windows が別 device instance として扱える
USB identity を用意する必要がある。

優先候補:

1. `product_id` を US / JP profile で分ける。
2. `product_name` を US / JP profile で分け、Device Manager / Vial GUI で見分けやすくする。
3. Vial serial magic を保った上で、serial suffix に個体 / mode を付ける。

`manufacturer` / `product_name` は表示には効くが、同一 device 判定の主役にはしない。
Windows の per-device registry override を分ける主手段は、`product_id` と serial suffix を候補にする。
USB composite device の PID は interface ごとではなく device 全体で1つなので、main US interface だけを
別 PID に逃がすことはできない。試す場合は composite 全体を `HIDLOOM_USB_PRODUCT_ID=0x0106` などで
別 device identity にする。

## Vial serial magic

Vial GUI の検出には USB serial string に Vial magic が必要。
上流実装や関連 firmware では `vial:f64c2b3c` を magic prefix として扱い、
後ろに suffix を付ける例がある。

候補:

```json
{
  "product_id": "0x0105",
  "product_name": "__HOSTNAME__-us",
  "serial_number": "vial:f64c2b3c:<keyboard-host>-us"
}
```

```json
{
  "product_id": "0x0106",
  "product_name": "__HOSTNAME__-jp",
  "serial_number": "vial:f64c2b3c:<keyboard-host>-jp"
}
```

未確認点:

- Vial desktop / Vial web / hidapi の各環境で suffix 付き serial を問題なく検出できるか。
- 現行 `viald` / `usbd` / Raw HID bridge に serial suffix 由来の副作用がないか。
- Windows が suffix 付き serial と `product_id` の組み合わせを、期待通り別 device instance として保持するか。

suffix 付き serial の Vial 検出 smoke は先行 TODO へ昇格済み。
この smoke では Windows registry override や `product_id` profile 化には進まず、
Vial desktop / Vial web / Raw HID bridge が suffix 付き serial を許容するかだけを確認する。

## Windows registry override

Windows では device instance ごとの `Device Parameters` に
`OverrideKeyboardType` / `OverrideKeyboardSubtype` を設定する方法が知られている。
Zenn の「Windows 11でJIS/US配列を共存させる」事例では、system layout を
「接続済みキーボードレイアウトを使用する」に戻し、対象 keyboard device instance path の
`Device Parameters` に `OverrideKeyboardType` / `OverrideKeyboardSubtype` を追加している。
概念上は次のように使う。

| 目的 | OverrideKeyboardType | OverrideKeyboardSubtype |
| --- | ---: | ---: |
| US 101/102 | `7` | `0` |
| JP 106/109 | `7` | `2` |

この override は主に symbol key の物理 layout 解釈に効く。
`KC_LANG1` / `KC_LANG2` の IME on/off とは分けて考える。

2026-06-10 時点の調査では、`OverrideKeyboardType` / `OverrideKeyboardSubtype` は
HID keyboard report descriptor から直接申告できる device capability ではなく、
Windows 側の device instance registry または INF / extension INF で設定する
host-side parameter として扱うのが安全。

Microsoft の HID keyboard stack では、`HIDCLASS.sys` が top-level collection ごとの
PDO を作り、keyboard collection に `KBDHID.sys` が載る。`KBDHID.sys` は HID usage を
scan code へ変換し、`KBDCLASS.sys` と keyboard layout が最終的な意味を決める。
このため、device 側でできることは次に限られる。

- USB / Bluetooth の identity を分け、Windows に別 device instance として保持させる。
- Keyboard top-level collection / USB interface を分け、per-interface override を試せる形にする。
- `bCountryCode` が使える環境では値を出す。ただし layout 強制手段としては扱わない。
- `Keyboard/Keypad` usage range と LED Output usage を descriptor 上で許可する。

一方で、device 側の標準 HID report だけで
`OverrideKeyboardType=7` / `OverrideKeyboardSubtype=2` を Windows registry に作らせる
根拠は見つかっていない。これを自動化するなら、helper 常駐アプリではなく、
対象 hardware ID / compatible ID に紐づく extension INF で `Device Parameters` を
付与する方式を別途検討する。

手動検証では、`build/generators/make_windows_keyboard_layout_override_reg.py` で
対象 device instance path から UTF-16 LE の `.reg` を生成し、値名の typo を避ける。
INF 化する場合は、`build/generators/make_windows_keyboard_layout_override_inf.py` で extension INF の
雛形を生成できる。ただし Windows の通常運用では INF driver package に catalog 署名が必要になるため、
署名なし INF を本命手段にしない。まず `.reg` で `MI_02` の override が効くことを確認し、
効いた場合だけ WDK / test signing / production signing のどれを使うか判断する。

## Composite split keyboard interface plan

期待する運用は、同じ USB 複合デバイス内で次を分けること。

| interface | 役割 | Windows 側で期待する扱い |
| --- | --- | --- |
| main keyboard | JIS 固有キー、変換 / 無変換、Kana LED 受信 | JIS / JP 106-109 override を個別適用 |
| US sub keyboard | 通常 typing / US symbol layout / `KC_LANG1` / `KC_LANG2` | 既存の US profile を維持 |

2026-06-11 時点の重要点は、layout override の適用範囲を keyboard interface ごとに分けられるかを確認することだった。
2026-06-11 の first slice では、live gadget の default は変えず、opt-in 時だけ次を有効にする。

1. `hid.usb2` を optional US sub keyboard interface として使う。
2. `hid.usb2` は Keyboard/Keypad usage page、usage range `0x00`-`0xFF`、LED Output usage `0x01`-`0x05`、
   no Report ID の 8 byte input report を持つ。
3. 初期実験では `hid.usb2` を `protocol=0` / `subclass=0` の non-boot keyboard とした。
   Windows では `Service=kbdhid` / `Class=Keyboard` として列挙され、
   `OverrideKeyboardType=7` / `OverrideKeyboardSubtype=2` も `MI_02` の `Device Parameters` に入ったが、
   `KC_HENKAN` / `KC_MUHENKAN` は効かなかった。
4. `hid.usb2` だけを `protocol=1` / `subclass=1` の boot keyboard に寄せても挙動は変わらなかった。
   `USB\...\MI_02` parent の `Device Parameters` に同じ override を入れても変換 / 無変換は効かなかった。
5. Windows Device Manager で `MI_02` が独立した HID keyboard device instance として見えることを確認した。
6. その instance の `Device Parameters` だけに `OverrideKeyboardType=7` / `OverrideKeyboardSubtype=2` を入れた。
   同じ値を `USB\...\MI_02` parent にも入れたが、`KC_HENKAN` / `KC_MUHENKAN` は有効にならなかった。
7. 最後に全 keyboard report を `/dev/hidg2` へ流しても Windows は US 配列として動いた。
   よって Windows での失敗原因は送信 endpoint ではなく、layout 判定 / registry override の適用範囲側にある。

`logicd` は別 OS 検証を続けられるよう、Keyboard/Keypad usage `0x87`-`0x98`
（International1-9 と Language1-9）を検出した時、main keyboard report へは出さず、
broker 経由で `KIND_US_SUB_KEYBOARD` として `/dev/hidg2` に切り替える。対応する all-zero release report も
JP 側へ送る。代表 usage は `KC_RO`、`KC_KANA`、`KC_JYEN`、`KC_HENKAN`、
`KC_MUHENKAN`、`KC_LANG1`-`KC_LANG9`。通常英数字は US 側に残す。
2026-06-11 の結果として、JP 側への送信は成立したが、Windows の per-interface registry override では
`0x8A` / `0x8B` を変換 / 無変換として有効化できなかった。Windows 向けの dedicated 変換 / 無変換は
global JIS layout 限定または fallback 扱いに戻す。

2026-06-13 の custom INF 実験では、JIS main / US sub の構成が成功した。

| interface | Windows binding | runtime role |
| --- | --- | --- |
| main `/dev/hidg0` / `MI_00&Col01` | JIS 106/109 | JIS 固有キー、変換 / 無変換、Kana LED 受信 |
| sub `/dev/hidg2` / `MI_02` | US 101/102 | 通常 typing、US symbol layout、`KC_LANG1` / `KC_LANG2` |

この構成では、Windows の手動 registry override ではなく、署名済み custom INF が
`KeyboardTypeOverride` / `KeyboardSubtypeOverride` を各 keyboard child に入れる。
実入力で main は JIS 記号、sub は US 記号として解釈されることを確認済み。

## 実装候補

JP / US identity の Windows 実験は 2026-06-13 に完了扱いへ移した。
Vial serial suffix smoke は先行実験 TODO として扱い済み。
JIS main keyboard と US sub keyboard を利用中に同居させる場合は、
[HID multi-report endpoint consolidation plan](../daemon/specs/hidd/usb-gadget-multi-report-plan.md) を前提にする。
まず `/dev/hidg0` へ keyboard / mouse / consumer control を multi-report として統合し、
Vial Raw HID の `/dev/hidg1` を維持したまま endpoint を空ける。
その後、空いた HID function に US sub keyboard を追加し、`KC_INT4` / `KC_INT5` / `KC_INT2`
などの JIS 固有キーだけを検証する。

全体実装へ進めるなら次の順に小さく進める。

1. Vial magic prefix を保った serial suffix の実機検出を確認する。
2. `/dev/hidg0` の US keyboard / mouse / consumer control multi-report 統合を実機 smoke まで固定する。
3. `config/default/config.json` の `device` を US / JP identity profile として切り替えられるようにする。
4. `setup_usb_gadget.sh` が profile ごとの `product_id` / `product_name` / `serial_number` を使えるようにする。
5. 空いた HID function に JP thin keyboard を追加する。first slice では `hid.usb2` / `/dev/hidg2` を使う。
6. Windows host で main keyboard と sub keyboard は別 device instance として認識され、custom INF で
   main JIS / sub US として bind できた。
7. `host_layout` と `ime_control` を分離し、US sub profile でも `KC_LANG1` / `KC_LANG2` を抑止しない policy を固定する。
8. 和文 Morse / touch flick の JP input extension と接続するか判断する。

2026-06-10 追記: `KC_HENKAN` / `KC_MUHENKAN` は Windows の global hardware keyboard layout を
JIS / Japanese 側へ切り替えると有効になった。一方、Kana LED bit は JIS 側でも返らなかった。
USB composite の US sub keyboard interface だけを JIS override へ寄せる実験では、
Windows の `MI_02` child / parent registry override、JP 側 boot keyboard 化、全キー JP 側 route の
いずれでも `KC_HENKAN` / `KC_MUHENKAN` は有効にならなかった。
別 OS では `0x87`-`0x98` の JP 側 route を使って継続確認する。

## 実装しない条件

- Vial detection が suffix 付き serial で不安定になる。
- Windows registry override の保持が USB port や composite interface の都合で不安定になる。
- `/dev/hidg0` multi-report 統合で keyboard / mouse / consumer / host LED のいずれかが不安定になる。
- `KC_LANG1` / `KC_LANG2` を layout 判定だけで抑止する必要が出る。
- host OS の keyboard layout を keyboard 側から強制変更することが前提になる。

## 参考

- Microsoft Learn: Keyboard Japan - ImeOn / ImeOff Implementation
  <https://learn.microsoft.com/windows-hardware/design/component-guidelines/keyboard-japan-ime>
- Microsoft Learn: Identifiers for USB Devices
  <https://learn.microsoft.com/windows-hardware/drivers/install/identifiers-for-usb-devices>
- Microsoft Learn: USB in Windows FAQ
  <https://learn.microsoft.com/windows-hardware/drivers/usbcon/usb-faq--introductory-level>
- Microsoft Learn: Developing Keyboard and Mouse HID Client Drivers
  <https://learn.microsoft.com/windows-hardware/drivers/hid/keyboard-and-mouse-hid-client-drivers>
- Microsoft Learn: Using an Extension INF File
  <https://learn.microsoft.com/windows-hardware/drivers/install/using-an-extension-inf-file>
- Microsoft Learn: INF AddReg Directive
  <https://learn.microsoft.com/windows-hardware/drivers/install/inf-addreg-directive>
- USB HID 1.11 descriptor `bCountryCode`
  <https://www.usb.org/sites/default/files/hid1_12.pdf>
- HID Usage Tables 1.21 Extended Keyboard Attributes
  <https://usb.org/sites/default/files/hut1_21_0.pdf>
- RMK keyboard device config: Vial serial magic prefix example
  <https://rmk.rs/docs/configuration/keyboard_device>
