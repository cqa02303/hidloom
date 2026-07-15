# HIDloom Name Inventory

更新日: 2026-07-13

## 命名境界

- `HIDloom`: software projectと表示名。
- `hidloom`: repository、CLI、package、service、filesystem namespace。
- `HIDLOOM_*`: runtime/build environment variable。
- `cqa02303v5`: keyboard hardware/device profile。
- `/mnt/p3`: Raspberry Pi OSとBuildrootで共有する永続データpath。

## 完了条件

現行software範囲では旧project名、旧prefix、旧Python importを許可しない。
履歴資料、KiCad hardware source、Windows hardware driver、完了済みCodex task記録、
canonical GitHub ownerを保持するpublication policyだけを監査除外とし、実行可能source、
その他のbuild asset、現行docsには除外を設けない。

機械監査は`tools/hidloom_name_audit.py`を正本とする。禁止patternまたは禁止pathを検出した場合は
CIを失敗させる。hardware名`cqa02303v5`単体とcanonical GitHub owner URLは許可するが、
owner由来tokenをsoftware suffix/prefix、D-Bus path、schema、表示名へ転用することは許可しない。

## 移行結果

- Python importは`hidloom_paths`へ一本化し、compatibility shimを削除した。
- native binary、systemd unit、Debian package、Buildroot external treeを`hidloom-*`へ移行した。
- runtime pathを`/run/hidloom`と`/tmp/hidloom_*`へ移行した。
- environment variableを`HIDLOOM_*`へ移行し、fallback aliasを削除した。
- Buildroot M1-M6 defconfigとoverlayをHIDloom namespaceへ移行した。
- MCP `serverInfo`を`hidloom-keyboard`、BLE D-Bus object pathを`/org/hidloom/btd`、
  Device Information manufacturerを`HIDloom`へ移行した。
- systemd/journald drop-in、共有schema、Buildroot credential saltからowner由来のsoftware tokenを除去した。
- `cqa02303v5`はdevice profileとhardware資料だけに維持した。

詳細な移行境界は[`hidloom-migration-contract.md`](hidloom-migration-contract.md)を参照する。
