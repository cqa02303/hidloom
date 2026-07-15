# Windows host enumeration summary

Date: 2026-06-13

このメモは、Windows host 側の keyboard enumeration をruntime / driver診断から参照しやすい形に
整理した summary です。machine-specific なfull instance suffixは共有docsへ記録せず、再現に必要な
場合だけlocal-onlyの実験ログへ保存します。

関連:

- Windows IME routing: [../input/windows-us-custom-hid-ime-routing-design.md](../input/windows-us-custom-hid-ime-routing-design.md)
- Windows JIS VID/PID research: [../research/windows-jis-keyboard-vid-pid.md](../research/windows-jis-keyboard-vid-pid.md)
- Keyboard MCP route view: [../ops/keyboard-mcp-server.md](../ops/keyboard-mcp-server.md#get_usb_split_status)

## Confirmed summary

| Item | Current result |
| --- | --- |
| Device | `cqa02303v5` device profileのUSB composite gadget |
| Main keyboard path | `/dev/hidg0` |
| Sub keyboard path | `/dev/hidg2` |
| Main Windows binding | JIS 106/109 by custom INF |
| Sub Windows binding | US 101/102 by custom INF |
| Main role | JIS-specific keys, `KC_KANA`, `KC_HENKAN`, `KC_MUHENKAN`, Kana LED receive |
| Sub role | Normal typing, US symbol layout, `KC_LANG1` / `KC_LANG2` route |
| Runtime route | `jis_special_us_default` |
| Helper app | Not required for normal JIS / US split typing |
| Raw HID receiver | Diagnostic only, not normal UX |

## Known validated behavior

- Windows sees main and sub keyboard children as separate device instances.
- The custom INF can bind main `MI_00&Col01` as JIS 106/109.
- The custom INF can bind sub `MI_02` as US 101/102.
- Main route interprets tested symbol usages as JIS symbols.
- Sub route interprets tested symbol usages as US symbols.
- `KC_HENKAN` / `KC_MUHENKAN` route to main JIS.
- JIS-only keys such as RO / Yen route to main JIS.
- Normal keyboard usages route to sub US.
- JIS main can receive the host Kana LED bit `0x10`.

## Host enumeration fields to capture

Use a Windows administrator or normal PowerShell session as appropriate. Do not paste full
machine-specific instance suffixes into shared docs unless needed for a narrow experiment.

PowerShell shape:

```powershell
Get-PnpDevice -Class Keyboard |
  Where-Object InstanceId -like 'HID\\VID_1D6B&PID_0105*' |
  Select-Object Status, Class, FriendlyName, InstanceId

Get-PnpDeviceProperty -InstanceId '<instance-id>' |
  Where-Object KeyName -match 'MatchingDeviceId|Driver|InfPath|KeyboardType|KeyboardSubtype|Override'
```

Record these normalized fields:

| Field | Example / expected value |
| --- | --- |
| `main.instance_prefix` | `HID\VID_1D6B&PID_0105&MI_00&Col01` |
| `main.inf` | split custom INF package, for example `oem*.inf` |
| `main.keyboard_type` | JIS / 106/109 equivalent |
| `main.keyboard_subtype` | `2` |
| `sub.instance_prefix` | `HID\VID_1D6B&PID_0105&MI_02` |
| `sub.inf` | same split custom INF package |
| `sub.keyboard_type` | US / 101/102 equivalent |
| `sub.keyboard_subtype` | `0` |
| `kana_led_observed` | `true` if main receives bit `0x10` |

## Remaining productization gaps

- INF signing / distribution remains a productization decision.
- Stale device cleanup remains a manual Windows maintenance concern.
- Full machine-specific PnP instance IDs should stay out of shared docs unless a
  reproduction requires them.

## MCP implication

The MCP server should keep exposing route and readiness summaries, not Windows driver
mutation tools. Windows driver install, stale device cleanup, INF signing, and registry
changes remain explicit host-side procedures.
