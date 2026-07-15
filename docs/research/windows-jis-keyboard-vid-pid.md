# Windows JIS keyboard VID/PID investigation

Date: 2026-06-12

## Summary

Windows does not appear to treat an arbitrary USB keyboard as JIS/106/109 only from
the USB HID keyboard usage. In the captured Windows sample, connected keyboard-like
devices used the Japanese input layout (`00000411`), but the keyboard device
type reported by `Win32_Keyboard` is still `101/102-key`.

Windows has a built-in list of known Japanese 106/109 HID keyboard hardware IDs in
`C:\Windows\INF\keyboard.inf`. Devices matching those IDs are installed using
`HID_106_Keyboard_Inst`, which writes:

```text
KeyboardTypeOverride    = 7
KeyboardSubtypeOverride = 2
```

For PS/2 Japanese 106/109 keyboard installation, the same INF also uses:

```text
OverrideKeyboardType       = 0x7
OverrideKeyboardSubtype    = 0x2
OverrideKeyboardIdentifier = "PCAT_106KEY"
LayerDriver JPN            = "kbd106.dll"
```

USB HID also has a `bCountryCode` field in the HID descriptor. The HID
specification defines this as the country code for localized hardware. For Japan,
the country code is decimal `15` / hex `0x0F`. This may help describe the hardware,
but on Windows the confirmed built-in JIS handling found here is through
`keyboard.inf` hardware ID matches and the keyboard type/subtype override values.

## Captured Windows sample

Command results from the test Windows environment showed these active keyboard
or keyboard-like devices:

```text
Win32_Keyboard:

Name        : 拡張 (101- または 102-key)
Description : HID キーボード デバイス
DeviceID    : HID\PENTABLET&COL04\...
Layout      : 00000411

Name        : 拡張 (101- または 102-key)
Description : Logitech USB Input Device
DeviceID    : USB\VID_046D&PID_C52B&MI_00\...
Layout      : 00000411

Name        : 拡張 (101- または 102-key)
Description : USB 入力デバイス
DeviceID    : USB\VID_1D6B&PID_0105&MI_00\...
Layout      : 00000411
```

Currently OK PnP keyboard instances included:

```text
HID\PENTABLET&COL04\...
HID\VID_046D&PID_C52B&MI_00\...
HID\VID_1D6B&PID_0105&MI_00\...
```

The checked HID keyboard registry entries did not contain
`KeyboardTypeOverride=7` or `KeyboardSubtypeOverride=2`. Therefore, the devices
represented by this sample were not installed as Windows
Japanese 106/109 HID keyboards.

## Windows built-in 106/109 HID matches

The following hardware IDs were found in `C:\Windows\INF\keyboard.inf` using
`HID_106_Keyboard_Inst`:

```text
HID\VID_044E&PID_1104
HID\VID_03EE&PID_5609&MI_00
HID\VID_0430&PID_0002&MI_00
HID\VID_0430&PID_000A&MI_00
HID\VID_0430&PID_000B
HID\VID_0430&PID_0082
HID\VID_0430&PID_0083&MI_00
HID\VID_04C5&PID_1020&MI_00
HID\VID_04C5&PID_1018&Col01
HID\VID_04C5&PID_1022&MI_00&Col01
HID\VID_06D5&PID_4000
HID\VID_060B&PID_2101&MI_00
HID\VID_060B&PID_5903
HID\VID_060B&PID_6003&MI_00
HID\VID_060B&PID_1006&MI_00
HID\VID_045E&PID_005C&MI_00
HID\VID_045E&PID_0061&MI_00
HID\VID_045E&PID_0065&MI_00
HID\VID_045E&PID_0071&MI_00
HID\VID_045E&PID_0073&MI_00
HID\{00001124-0000-1000-8000-00805f9b34fb}_VID&0001045e_PID&007f&Col01
HID\VID_045E&PID_0089&MI_00
HID\VID_045E&PID_008B&MI_00
HID\{00001124-0000-1000-8000-00805f9b34fb}_VID&0002045e_PID&009A&Col01
HID\VID_045E&PID_009E&MI_00
HID\VID_045E&PID_00AD&MI_00
HID\VID_045E&PID_00AF&MI_00
HID\VID_045E&PID_00B1&MI_00
HID\VID_045E&PID_00B5&MI_00
HID\VID_045E&PID_00BC&MI_00
HID\VID_045E&PID_00DC&MI_00
HID\VID_045E&PID_00DE&MI_00
HID\VID_045E&PID_00E0&MI_00
HID\VID_045E&PID_00E4&MI_00
HID\VID_045E&PID_00F2&MI_00
HID\VID_045E&PID_00FA&MI_00
HID\VID_045E&PID_00FD&MI_00
HID\{00001124-0000-1000-8000-00805f9b34fb}_VID&0002045e_PID&0704&Col01
HID\VID_045E&PID_0716
HID\{00001124-0000-1000-8000-00805f9b34fb}_VID&0002045e_PID&0706&Col01
HID\VID_045E&PID_0718
HID\VID_045E&PID_071E&MI_00
HID\VID_045E&PID_0731&MI_00
HID\VID_045E&PID_0733&MI_00
HID\VID_045E&PID_0735&MI_00
HID\VID_045E&PID_0746&MI_00
HID\VID_045E&PID_074C&MI_00
HID\VID_045E&PID_0751&MI_00
HID\VID_045E&PID_0753&MI_00
HID\{00001124-0000-1000-8000-00805f9b34fb}_VID&0002045e_PID&0763&Col01
HID\VID_0409&PID_0014&MI_00
HID\VID_0409&PID_0019
HID\VID_0409&PID_0025
HID\VID_0409&PID_0034&COL01
HID\VID_0409&PID_0094&COL01
HID\VID_0409&PID_0095
HID\VID_0409&PID_003F&MI_00&Col01
HID\VID_0409&PID_004F&MI_00&Col01
```

## Notes for firmware work

For a custom USB keyboard that should behave as a Japanese keyboard on Windows,
there are three practical paths to consider:

1. Use a VID/PID/hardware ID that already matches Windows `keyboard.inf` JIS
   entries, only if legally and operationally appropriate.
2. Provide a vendor INF that matches the device hardware ID and installs it with
   equivalent 106/109 keyboard override registry values.
3. Set HID `bCountryCode` to Japan (`0x0F`) and verify on the target Windows
   versions, but do not rely on this alone unless tested.

The safest project-specific conclusion is: for the tested custom VID/PID values,
Windows did not automatically apply JIS/106/109
keyboard overrides.

## 2026-06-12 follow-up: JIS main + US sub experiment

The reverse experiment from the previous JP sub-keyboard attempt was prepared on a
`cqa02303v5` device profile:

- Main USB keyboard interface: `/dev/hidg0`, Windows instance
  `HID\VID_1D6B&PID_0105&MI_00&Col01\...`
- Sub USB keyboard interface: `/dev/hidg2`, Windows instance
  `HID\VID_1D6B&PID_0105&MI_02\...`
- USB product string during the experiment identified a temporary 106 JP keyboard profile.
- USB serial string during the experiment:
  `vial:f64c2b3c:jis-main-us-sub`

The Pi was temporarily started with:

```bash
sudo env \
  HIDLOOM_USB_KEYBOARD_IDENTITY_STRINGS=jp_106 \
  HIDLOOM_USB_US_SUB_KEYBOARD=1 \
  HIDLOOM_US_SUB_KEYBOARD_IDENTITY_STRING=US101 \
  HIDLOOM_USB_SERIAL_SUFFIX=jis-main-us-sub \
  HIDLOOM_USB_HID_COUNTRY_CODE=15 \
  ./setup_usb_gadget.sh
```

The running kernel did not expose configfs `country_code` / `bCountryCode`, so
`HIDLOOM_USB_HID_COUNTRY_CODE=15` was requested but not applied by configfs.
Interface strings were also not accepted by this HID gadget function. The useful
part of the experiment is therefore Windows registry override on the separated
keyboard instances.

For this follow-up, use the INF-style HID values on the device key itself:

```text
KeyboardTypeOverride    = 7
KeyboardSubtypeOverride = 2  # JP 106/109 main
KeyboardSubtypeOverride = 0  # US 101/102 sub
```

This differs from the older `Device Parameters\OverrideKeyboardType` /
`Device Parameters\OverrideKeyboardSubtype` experiment. A non-elevated registry write
was denied by Windows permissions, so an administrator-import file was generated locally:

```text
windows-jis-main-us-sub-current.reg
```

Generated `.reg` files contain machine-specific HID instance paths and are
ignored. The reusable template is kept at:

```text
windows-driver/hidloom-keyboard-layout-override-template.reg
```

Use the template only as a manual experiment fallback. The preferred route is
the custom INF package, which applies the same keyboard type/subtype values at
driver binding time.

After importing the `.reg` as administrator, disconnect/reconnect the USB gadget
or disable/enable both keyboard devices before judging key behavior.

## 2026-06-12 follow-up: successful built-in JIS VID/PID candidate

The post-install registry override approach did not make the current
`VID_1D6B&PID_0105` cqa02303v5 keyboard behave as JIS. The useful path was to make
Windows select a built-in `keyboard.inf` Japanese keyboard match during initial
enumeration.

The best candidate found in this experiment is:

```text
VID_03EE&PID_5609
keyboard.inf entry: HID\VID_03ee&PID_5609&MI_00
Windows model: Mitsumi Japanese USB Keyboard
```

With `HIDLOOM_USB_KEYBOARD_ONLY_TEST=1`, Windows enumerated the keyboard interface
as:

```text
Status       : OK
Class        : Keyboard
FriendlyName : Mitsumi Japanese USB Keyboard
InstanceId   : HID\VID_03EE&PID_5609&MI_00\...
```

The vendor-defined raw HID interface also stayed healthy:

```text
Status       : OK
Class        : HIDClass
FriendlyName : HID 準拠ベンダー定義デバイス
InstanceId   : HID\VID_03EE&PID_5609&MI_01\...
```

Manual typing confirmation: JIS.

The same VID/PID was then tested with the normal multi-report keyboard interface
enabled again, using:

```bash
sudo env \
  HIDLOOM_USB_VENDOR_ID=0x03EE \
  HIDLOOM_USB_PRODUCT_ID=0x5609 \
  HIDLOOM_USB_SERIAL_SUFFIX=jis-known-03ee-5609-multi \
  HIDLOOM_USB_KEYBOARD_IDENTITY_STRINGS=jp_106 \
  ./setup_usb_gadget.sh
```

Windows reported all active children as OK:

```text
HID\VID_03EE&PID_5609&MI_00&COL01  Keyboard  HID キーボード デバイス
HID\VID_03EE&PID_5609&MI_00&COL02  Mouse     HID 準拠マウス
HID\VID_03EE&PID_5609&MI_00&COL03  HIDClass  HID 準拠コンシューマー制御デバイス
HID\VID_03EE&PID_5609&MI_01        HIDClass  HID 準拠ベンダー定義デバイス
```

`Win32_Keyboard` reported the keyboard layout as Japanese:

```text
DeviceID : HID\VID_03EE&PID_5609&MI_00&COL01\...
Layout   : 00000411
```

This is better than the earlier `VID_0409&PID_0014` test. `0409:0014` produced
JIS keyboard behavior, but Windows mis-bound the raw HID interface as a NEC
keyboard/mouse related device and left an error device. `03EE:5609` kept both the
keyboard side and the raw HID side OK.

Current conclusion: `VID_03EE&PID_5609` is the strongest Windows built-in JIS
candidate found so far. If this is used beyond local testing, confirm the legal
and product implications of presenting a third-party VID/PID. The clean product
path remains either an assigned project VID/PID plus a project INF, or a
separate Windows-side installer that applies the equivalent JIS keyboard
override at install time.

## 2026-06-12 follow-up: custom INF experiment

A project INF experiment was started for the original cqa02303v5 VID/PID:

```text
VID_1D6B&PID_0105
Keyboard hardware ID: HID\VID_1D6B&PID_0105&MI_00&Col01
INF: windows-driver/hidloom-jis-keyboard.inf
Installed as: oem*.inf
```

The INF matches both of these IDs:

```text
HID\VID_1D6B&PID_0105&MI_00&COL01
HID\VID_1D6B&PID_0105&MI_00
```

It reuses Windows' in-box `keyboard.inf` Japanese HID install section through
`Include=keyboard.inf` and `Needs=HID_106_Keyboard_Inst.*`.

Unsigned INF installation failed first, as expected:

```text
Failed to add driver package: third-party INF does not contain digital signature information.
```

For this local experiment, a self-signed test certificate was created, trusted in
LocalMachine Root and TrustedPublisher, and used to sign a catalog generated by
PowerShell `New-FileCatalog`. That was enough for `pnputil` on the test host:

```text
Published Name: oem*.inf
Updated device: HID\VID_1D6B&PID_0105&MI_00&Col01\...
```

After reconnecting the device as the original `1D6B:0105` gadget with serial
suffix `inf-jis-test`, Windows reported:

```text
Status       : OK
Class        : Keyboard
FriendlyName : CQA02303v5 Japanese 106/109 USB Keyboard
InstanceId   : HID\VID_1D6B&PID_0105&MI_00&COL01\...

DriverInfPath    : oem*.inf
MatchingDeviceId : HID\VID_1D6B&PID_0105&MI_00&Col01
Layout           : 00000411
```

The INF wrote the JIS override values under the device instance's
`Device Parameters` key:

```text
KeyboardTypeOverride    : 7
KeyboardSubtypeOverride : 2
```

All composite children stayed healthy:

```text
Keyboard  CQA02303v5 Japanese 106/109 USB Keyboard  OK
Mouse     HID 準拠マウス                               OK
HIDClass  HID 準拠コンシューマー制御デバイス           OK
HIDClass  HID 準拠ベンダー定義デバイス                 OK
USB       USB Composite Device                         OK
```

Current conclusion: the custom INF route is technically viable on the tested Windows
version. The remaining productization questions are proper driver package
signing, whether a real assigned VID/PID should replace the Linux Foundation
test VID/PID, and whether the installer should include stale-device cleanup or
device re-enumeration steps.

## 2026-06-12 follow-up: split JIS main + US sub experiment

The custom INF was extended to bind two keyboard interfaces differently:

```text
Main keyboard: HID\VID_1D6B&PID_0105&MI_00&Col01 -> JIS 106/109
Sub keyboard:  HID\VID_1D6B&PID_0105&MI_02       -> US 101/102
```

The device was started with:

```bash
sudo env \
  HIDLOOM_USB_SERIAL_SUFFIX=jis-main-us-sub-inf \
  HIDLOOM_USB_KEYBOARD_IDENTITY_STRINGS=jp_106 \
  HIDLOOM_USB_US_SUB_KEYBOARD=1 \
  HIDLOOM_US_SUB_KEYBOARD_IDENTITY_STRING=US101 \
  ./setup_usb_gadget.sh
```

The gadget exposed:

```text
/dev/hidg0  main keyboard + mouse + consumer multi-report
/dev/hidg1  raw HID
/dev/hidg2  sub boot keyboard
```

The updated signed test INF was installed as `oem*.inf`. Windows then reported
both keyboard children as OK and bound them to the same INF:

```text
CQA02303v5 Japanese 106/109 USB Keyboard
  InstanceId       : HID\VID_1D6B&PID_0105&MI_00&COL01\...
  DriverInfPath    : oem*.inf
  MatchingDeviceId : HID\VID_1D6B&PID_0105&MI_00&Col01
  KeyboardTypeOverride    : 7
  KeyboardSubtypeOverride : 2

CQA02303v5 US 101/102 Sub Keyboard
  InstanceId       : HID\VID_1D6B&PID_0105&MI_02\...
  DriverInfPath    : oem*.inf
  MatchingDeviceId : HID\VID_1D6B&PID_0105&MI_02
  KeyboardTypeOverride    : 7
  KeyboardSubtypeOverride : 0
```

Current conclusion: the Windows driver binding/registry part of JIS main + US
sub separation is successful. The remaining check is behavioral: send or type
through the sub keyboard path and verify that Windows interprets that keyboard
as US while the main keyboard remains JIS.

Behavioral confirmation was then performed by sending the same HID keyboard
usage sequence through `/dev/hidg0` and `/dev/hidg2` into the Windows text input
field.

Main `/dev/hidg0` output:

```text
main^@[:－＾
```

This matches JIS interpretation for the tested HID usages, for example:

```text
KC_EQUAL    -> ^
KC_LBRACKET -> @
KC_QUOTE    -> :
```

Sub `/dev/hidg2` output, after forcing IME off with `KC_MUHENKAN`:

```text
sub=[]'`-=
```

This matches US interpretation for the tested HID usages:

```text
KC_EQUAL    -> =
KC_LBRACKET -> [
KC_RBRACKET -> ]
KC_QUOTE    -> '
KC_GRAVE    -> `
KC_MINUS    -> -
```

Final conclusion for this experiment: JIS main + US sub separation works on the
tested Windows version with the custom INF route.

## 2026-06-13 follow-up: runtime routing policy

The runtime routing policy was updated after the split-keyboard experiment:

```text
Normal keyboard usages     -> US sub keyboard (/dev/hidg2)
Henkan / Muhenkan          -> JIS main keyboard (/dev/hidg0)
JIS-only keys such as RO/Yen -> JIS main keyboard (/dev/hidg0)
Eisu / Hiragana            -> US sub keyboard (/dev/hidg2)
Kana                       -> JIS main keyboard (/dev/hidg0)
```

Implementation details:

```text
config/default/config.json:
  settings.usb_split_keyboard.enabled = true
  settings.usb_split_keyboard.route   = "jis_special_us_default"
  settings.usbd_hid_report_broker      = true

daemon/logicd/config_runtime.py:
  route "jis_special_us_default"
    default reports -> KIND_US_SUB_KEYBOARD -> /dev/hidg2
    selected JIS-special reports -> KIND_KEYBOARD -> /dev/hidg0
```

The selected JIS-main usages are:

```text
0x87 KC_RO
0x89 KC_JYEN
0x8A KC_HENKAN
0x8B KC_MUHENKAN
0x8C KC_INT6
0x8D KC_INT7
0x8E KC_INT8
0x8F KC_INT9
```

`KC_KANA` / `0x88` was moved into the JIS-main route after the Kana LED output
report follow-up, so Kana Lock experiments use the same interface that receives
the host Kana LED bit. `KC_LANG1` / `KC_LANG2` remain on the US-sub route for
ImeOn/ImeOff.

The device was updated and restarted with the normal serial
`vial:f64c2b3c`. Runtime status after restart:

```text
/dev/hidg0  present
/dev/hidg1  present
/dev/hidg2  present
usbd HID report broker socket: /tmp/usbd_hid_reports.sock
logicd route: jis_special_us_default
```

Windows still bound both keyboard interfaces through the split INF:

```text
Main: oem*.inf, HID\VID_1D6B&PID_0105&MI_00&Col01, subtype 2
Sub:  oem*.inf, HID\VID_1D6B&PID_0105&MI_02,       subtype 0
```

## 2026-06-13 follow-up: Kana LED output report

The JIS main keyboard can receive the host Kana LED state. `kana` was enabled in
`settings.host_led_output.states`, then Windows Caps/Kana lock states were
toggled from the host side while `logicd` was reading LED output reports from
`/dev/hidg0`.

Observed `logicd` logs:

```text
host LED output report=0x02 changed={'caps_lock': True}
host LED output report=0x12 changed={'kana': True}
host LED output report=0x02 changed={'kana': False}
host LED output report=0x00 changed={'caps_lock': False, 'kana': False, 'num_lock': False, 'scroll_lock': False}
```

Interpretation:

```text
bit1 / 0x02 = Caps Lock
bit4 / 0x10 = Kana
0x12        = Caps Lock + Kana
```

Conclusion: with the JIS-bound main interface, Windows does send the Kana LED
bit back to the gadget. This can be used as the host-side Kana/KanaLock signal
for OLED/LED status. A later 2026-06-15 observation found that after toggling
Microsoft IME kana input, the Kana LED bit and Host lock LEDs display can update
after the next normal key input. Treat Kana as a delayed advisory host state,
not as an immediate source of truth for IME mode.
