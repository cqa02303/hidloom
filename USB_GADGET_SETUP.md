# HIDloom USB Gadget Reference

HIDloomをRaspberry Pi Zero 2 W上のUSB HID composite gadgetとして動かすための構成資料です。
導入全体は[`FRESH_INSTALL.md`](FRESH_INSTALL.md)を先に参照してください。

## Development USB identity

現在の`config/default/config.json`にある`0x1d6b:0x0105`は、既存実機との互換確認と開発rehearsalだけに使う暫定値です。
`0x1d6b`はLinux FoundationのVIDであり、HIDloomの公開製品IDとして割り当てられたものではありません。

公開Releaseではこの組み合わせを正式IDとして使用しません。pid.codesの`0x1209`配下でPIDを取得し、public profile、
USB descriptor test、Windows driver、Vial identityを同時に更新するまで、release readinessの
`pid_codes_migration_required`を解除しないでください。

申請候補は`0x1209:0x484C`です。`config/public-usb-identity.json`では`candidate-unassigned`として管理し、
pid.codesでmergeされるまでruntime descriptorへ設定しません。申請直前に公式repositoryを再取得して候補pathが
未使用であることを確認し、申請draftを生成します。`site` / `source`として記載するpublic repositoryの
initial sourceとPublic CIがGitHub上で参照できる状態になってから申請PRを提出します。

```bash
git clone --depth=1 https://github.com/pidcodes/pidcodes.github.com.git /tmp/pid-codes
python3 tools/pid_codes_application.py \
  --upstream-checkout /tmp/pid-codes \
  --output /tmp/hidloom-pid-codes-application
```

`--output`は`--upstream-checkout`なしでは実行できません。canonical originへ作用するGit URL rewriteがなく、checkoutに未commit/untracked差分がなく、
`HEAD`がcanonical originの`origin/HEAD`およびonline remote `HEAD`と一致し、commit・確認日・候補/owner pathの結果が
`config/public-usb-identity.json`のavailability evidenceと完全一致する場合だけ申請draftを生成します。
生成物は提出前review用であり、runtimeへ候補VID/PIDを適用しません。

## Identity profiles

`config/public-usb-identity.json`は現在のruntimeと公開版を別profileとして管理します。

| Profile | Purpose | Current activation |
|---|---|---|
| `development_compatibility` | 現行実機、Windows device cache、Vial定義との互換維持 | active、public Release禁止 |
| `public_formal` | 割当後の公開descriptorとVial表示名 | pid.codes mergeまでblocked |

公開版の確定値はmanufacturer `HIDloom`、product `HIDloom Keyboard`、serial
`vial:f64c2b3c:hidloom`、Vial name `HIDloom Keyboard (cqa02303v5)`です。Vial UID
`4850729948911185980`は同一layout identityとして維持します。上流Vial GUIはserial magicをsubstringで判定するため、
このsuffix付きserialでも検出契約を満たします。

次のcommandは両profileと現行config/Vial定義の一致を検査し、公開profileのplanだけを表示します。

```bash
python3 tools/public_usb_identity.py
```

`--output`はruntimeへ適用せず、USB device JSON、Vial identity、`usb-identity.env`をrepository外へ生成するだけです。
現在の`candidate-unassigned`状態で`public_formal --output`を指定するとfail closedします。pid.codes merge後も、
allocation evidence、profile status、release許可を同じcontractで更新するまで生成できません。

生成した`usb-identity.env`の固定設置先は`/etc/hidloom/usb-identity.env`です。
`hidloom-usb-gadget.service`と`btd.service`が同じfileをoptionalに読み、USB descriptorとBLE Device Information
ServiceのPnP IDを同じprofileへ揃えます。fileがない場合はdevelopment compatibility既定値を維持します。
割当後の正式profileを手動確認するときだけ、USB管理経路を失わないrollback手段を確保して次を実行します。

```bash
sudo install -D -m 0644 <profile-bundle>/usb-identity.env /etc/hidloom/usb-identity.env
sudo systemctl restart btd.service
sudo systemctl restart hidloom-usb-gadget.service
```

rollbackはfileを削除して両serviceを再起動します。USBとBLEの片方だけへVID/PIDを設定してはいけません。

## Sources of truth

| Path | Purpose |
|---|---|
| `config/public-usb-identity.json` | private互換/public正式profile、Vial identity、pid.codes割当状態 |
| `config/default/config.json` | development VID/PID、descriptor string、HID country code、optional interface設定 |
| `tools/public_usb_identity.py` | profile完全性検査と割当guard付きbundle生成 |
| `/etc/hidloom/usb-identity.env` | USB gadgetとBLE PnP IDが共有するprofile環境file |
| `setup_usb_gadget.sh` | shell/native backendを選ぶrepository root wrapper |
| `system/install/setup_usb_gadget.sh` | configfsを構築するportable shell backend |
| `bin/hidloom-usb-gadget-fast` | package/install時にbuildされる高速native backend |
| `system/systemd/hidloom-usb-gadget.service` | boot時のgadget owner |

descriptor値をこの文書へ複製して変更せず、上記sourceと対応する回帰testを同じ変更で更新します。

## HID interfaces

| Device | Availability | Role |
|---|---|---|
| `/dev/hidg0` | required | report ID 1 keyboard、report ID 2 mouse、report ID 3 consumer control |
| `/dev/hidg1` | required | 32-byte Raw HID input/output used by Vial |
| `/dev/hidg2` | optional | independent US sub keyboard when `settings.us_sub_keyboard.enabled=true` |
| `/dev/hidg4` | optional | vendor-defined Windows IME interface when `settings.windows_ime_custom_hid.enabled=true` |

optional interfaceを有効化できないUDCでは既存gadgetを壊さずpreflightで停止します。interface番号を別用途へ流用せず、
Windows側identityとrouteを変更する場合はJP main、US sub、Raw HID/Vialをまとめて確認してください。

## Apply on the target

標準運用では同じversionの`hidloom-core`とdevice profile packageをinstallし、profileを適用します。checkoutからの
手動実行はrecoveryまたは開発用途に限定します。

```bash
sudo systemctl restart hidloom-usb-gadget.service
systemctl status hidloom-usb-gadget.service --no-pager
ls -l /dev/hidg0 /dev/hidg1
test ! -e /dev/hidg2 || ls -l /dev/hidg2
test ! -e /dev/hidg4 || ls -l /dev/hidg4
```

systemdを使わない診断時だけ、target上のrepository rootでwrapperを直接実行します。

```bash
sudo ./setup_usb_gadget.sh
```

`HIDLOOM_USB_GADGET_SETUP_BACKEND=native`を指定した場合、wrapperは実行可能な
`bin/hidloom-usb-gadget-fast`がなければfail closedします。

## Verification

```bash
python3 script/test_usb_gadget_descriptor.py
python3 script/test_usb_gadget_fast_helper.py
systemctl is-active hidloom-usb-gadget.service hidloom-hidd.service
```

host側ではkeyboard/mouse/consumer、JP main、optional US sub、Raw HID/Vialのenumerationを確認します。
VID/PID、serial、product string、Vial UIDを変更した場合はWindowsの古いdevice cacheだけで判定せず、fresh enumerationと
Vial clientの双方を確認してください。

## Recovery

configfs再構成でUSB管理経路を失う可能性があります。remote-only作業ではgadget ownerを停止・再作成せず、別の管理経路または
既存Raspberry Pi OS microSDをrollback pathとして確保します。Buildroot M6は別microSDのoffline applianceとして扱います。
