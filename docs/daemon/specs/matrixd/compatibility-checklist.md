# matrixd Compatibility Checklist

## Board / Coordinate

- [ ] 既存 board profile の row / column 対応が変わっていない。
- [ ] `docs/hardware/keyswitch-matrix-map.md` と logical coordinate が一致する。
- [ ] 未定義 pin / 未定義 coordinate を event にしない。
- [ ] 左右分割や role 差分がある場合、profile ごとの期待値を記録した。

## Event

- [ ] press / release ordering が保持される。
- [ ] 同一 transition から重複 event が出ない。
- [ ] 起動直後の初期 state が安全側である。
- [ ] logicd 未接続時の event 処理方針が決まっている。

## Timing

- [ ] scan interval の変更が debounce threshold と整合している。
- [ ] scan latency の測定値を比較できる。
- [ ] CPU 負荷を上げた状態でも missed input がない。
- [ ] service restart 後に scan が再開する。
- [ ] high-brightness LED effect 中の idle key event count を確認した。
- [ ] `daemon/matrixd/matrixd` を x86_64 local build artifact で上書きしていない。

## Native / Rewrite

- [ ] C 実装の observable event と新実装の event を比較した。
- [ ] GPIO 初期化順を変えた場合、実機で ghost / stuck がない。
- [ ] diagnostic log の最小情報が残っている。
- [ ] debounce commit timing と event delivery failure の扱いが既存と一致する。
