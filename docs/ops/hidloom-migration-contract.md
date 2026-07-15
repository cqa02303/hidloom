# HIDloom Migration Contract

更新日: 2026-07-13

## 方針

software project識別子はHIDloomへ一括移行する。旧software名のbinary、service、package、
socket、status path、environment variable、Python import、Buildroot entrypointは提供しない。
互換aliasやfallbackも追加しない。

`cqa02303v5`はkeyboard hardware/device profileの名称としてのみ維持する。

## Canonical識別子

| 対象 | Canonical |
|---|---|
| Project / repository | `HIDloom` / `hidloom` |
| Python path API | `hidloom_paths` |
| Environment variables | `HIDLOOM_*` |
| Debian packages | `hidloom-*` |
| systemd services | `hidloom-*` |
| Binary / socket / status | `hidloom-*`, `/run/hidloom`, `/tmp/hidloom_*` |
| MCP server info | `hidloom-keyboard` |
| BLE D-Bus / manufacturer | `/org/hidloom/btd`, `HIDloom` |
| system config drop-in | `90-hidloom-*` |
| project-owned schema | `hidloom.*` |
| Buildroot external tree | `build/buildroot/hidloom-external` |
| Hardware profile | `cqa02303v5` |

## 共有データ

- `/mnt/p3/keymap.json`、`device_profile.json`、board profile、Vial definitionはRaspberry Pi OSとBuildrootで共有する。
- keymap schema、Vial UID、matrix座標、layer数、keycode表は名称移行だけでは変更しない。
- `/mnt/p3`は永続データpathであり、software namespaceではないため維持する。
- VID/PID、USB product identityはhardware profileとして扱う。`config/public-usb-identity.json`で
  `development_compatibility`と`public_formal`を分離し、pid.codes merge前は後者を生成・適用しない。
- 名称移行だけではVial UIDを変更しない。公開profileも同一layout UIDを維持し、USB/Vial表示名とserialだけを
  canonical HIDloom値へ切り替える。

## 移行ゲート

1. 現行software範囲で禁止名称の内容・pathがゼロである。
2. package、systemd、native tools、Buildroot assetの参照がHIDloom名で閉じている。
3. canonical環境変数以外を受理するfallbackがない。
4. native buildと静的testが通る。
5. 同じrevisionからM6 imageを再生成できる。
6. 次回`-02`実機testはclean M6 imageだけを対象とする。

## 検証

```bash
python3 tools/hidloom_name_audit.py
python3 script/test_hidloom_identity.py
python3 script/test_hidloom_runtime_environment.py
python3 script/test_buildroot_fast_boot_assets.py
```
