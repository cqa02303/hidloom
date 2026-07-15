# daemon

Runtime daemon implementations live here. Each daemon owns one process boundary and keeps its detailed usage notes in its own README.

## Daemons

| daemon | role |
|---|---|
| [`matrixd`](matrixd/README.md) | GPIO matrix scan daemon |
| [`logicd`](logicd/README.md) | companion control plane for keymap, layer state, macro, status, and advanced actions |
| [`i2cd`](i2cd/README.md) | OLED display and light I2C-side status daemon |
| [`ledd`](ledd/README.md) | serial LED animation and VialRGB daemon |
| [`usbd`](usbd/README.md) | legacy USB HID report broker / rollback daemon |
| [`sessiond`](sessiond/README.md) | PTY terminal mirror and session output policy daemon |
| [`viald`](viald/README.md) | Vial protocol bridge daemon |
| [`http`](http/README.md) | HTTPS Web UI and API daemon |
| [`btd`](btd/README.md) | Bluetooth HID daemon |
| [`spid`](spid/README.md) | SPI pointing-device daemon |

## Notes

- Native Rust runtime daemons currently live under [`../tools/`](../tools/): `logicd_core_rs`,
  `hidloom_outputd`, `hidloom_hidd`, and `hidloom_uidd`. Their systemd units live under
  [`../system/systemd/`](../system/systemd/).
- Systemd unit sources live under [`../system/systemd/`](../system/systemd/).
- Default runtime configuration lives under [`../config/default/`](../config/default/).
- Board wiring profiles live under [`../config/boards/`](../config/boards/).
- Performance/runtime profiles live under [`../config/profiles/`](../config/profiles/).
