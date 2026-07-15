# Boot / Debug / EEPROM action mapping design

作成日: 2026-06-01

この文書は QMK の bootloader / debug / EEPROM 系 action を Raspberry Pi 実装でどう扱うかの設計です。2026-06-01 時点では実装へは進まず、危険操作、代替動作、HTTP / OLED 表示、confirmation、audit log、テスト範囲を固定します。

## Goal

- QMK 互換名を見ても、Raspberry Pi 実装で意味が違うものを安全に扱う。
- reboot / shutdown / config reset / debug toggle を混同しない。
- destructive action は confirmation / local recovery / audit log を必須にする。
- EEPROM という概念を、Linux 上の config / runtime state / Vial storage と混ぜない。

## Candidate action classes

| class | examples | 初期扱い |
| --- | --- | --- |
| Bootloader | `QK_BOOT`, `RESET` | Pi では bootloader ではなく reboot / service action 候補。初期は no-op + warning |
| Debug | `DEBUG`, `DB_TOGG` | runtime debug flag / log level 候補 |
| EEPROM reset | `EEP_RST`, `EE_CLR` | destructive。初期は HTTP confirmation なしでは実行しない |
| System power | `KC_SYSTEM_POWER`, `KC_SYSTEM_SLEEP` | System control design 側と分ける |
| Local shutdown | `KC_SHUTDOWN` | 既存 action。QMK alias とは分ける |

## Policy

- `QK_BOOT` を Pi の bootloader mode として扱わない。
- `RESET` は曖昧なので alias として採用する場合は warning を出す。
- config reset は Vial / HTTP / runtime config のどれを消すかを明示する。
- EEPROM action は raw filesystem delete ではなく、定義済み reset scope だけを扱う。
- debug action は log verbosity / status flag に限定し、runtime state を壊さない。

## Reset scopes

候補:

| scope | 内容 |
| --- | --- |
| `runtime_only` | transient state clear。再起動なし |
| `keymap_runtime` | runtime remap / layer transient clear |
| `lighting_runtime` | LED runtime state clear |
| `vial_storage` | Vial compatible storage clear。危険 |
| `full_config` | config reset。初期対象外 |

## UI / feedback

- HTTP では destructive action に confirmation modal と audit log を必須にする。
- OLED では `Debug on` / `Reset blocked` のような短い alert だけ候補。
- keymap picker では unsafe action を Advanced / Dangerous group に分ける。
- Vial import で alias が来た時は local action に正規化する前に warning を残す候補。

## Safety policy

- destructive reset は default disabled。
- key press だけで full reset しない。
- local recovery path がない reset は実装しない。
- output switch / config reload 中の reset は拒否する候補。
- audit log には action name / scope / result を残す。

## Static tests to add with implementation

設計 first slice では doc test だけを追加する。実装へ進む場合は以下を追加する。

- `QK_BOOT` / `RESET` が Pi bootloader として実行されない。
- destructive reset は confirmation required。
- unknown reset scope は reject。
- debug toggle は runtime log/status だけを変更する。
- EEPROM alias は reset scope と明示対応する。
- audit log が残る。

## Implementation gate

実装へ進める条件:

- reset scope が固定できる。
- confirmation / audit log / recovery route がある。
- Vial storage と runtime config の owner が分かれている。

実装しない条件:

- key press だけで full config reset が必要になる。
- Pi bootloader 相当として `QK_BOOT` を扱う必要がある。
- reset scope を曖昧なまま実装する必要がある。
