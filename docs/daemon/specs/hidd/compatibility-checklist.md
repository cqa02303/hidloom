# hidd Compatibility Checklist

## Descriptor / Report

- [ ] descriptor と report length が一致する。
- [ ] report ID の意味を変更していない。
- [ ] keyboard boot protocol 相当の期待を壊していない。
- [ ] consumer / system / mouse / custom HID の report を混同していない。
- [ ] default descriptor profile で既存 interface 数と Vial Raw HID report length が変わっていない。
- [ ] descriptor 追加は opt-in で、host compatibility matrix がある。

## Startup / Restart

- [ ] endpoint 未準備時の失敗理由がログに残る。
- [ ] 起動直後に zero / clear state になる。
- [ ] restart 後に stuck key が残らない。
- [ ] logicd 未起動でも hidd の起動可否が仕様通りである。

## Source Ownership

- [ ] Python path と native path が同時に同じ report を送らない。
- [ ] legacy `usbd` broker path を通常運用へ再有効化していない。
- [ ] source 切断時の cleanup が決まっている。
- [ ] malformed payload を endpoint に流さない。
- [ ] short write / EPIPE / permission error を区別できる。

## Host Compatibility

- [ ] Linux host で enumeration と input を確認した。
- [ ] Windows host で enumeration と input を確認した、または実機確認待ちに記録した。
- [ ] report descriptor 変更時は host cache / reconnect 手順を残した。
