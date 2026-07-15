# kicad

KiCad の回路図・基板データを置くディレクトリです。

- 基板はキーボード裏面から見た座標で作成しています
- 他のデータと整合性を確認する際には左右反転して扱ってください

KiCad から生成した解析結果や中間 report は `build/build/generated/` に置きます。
実行時に読む設定は `conf/` に置き、KiCad 由来でも再生成できるものは runtime config と分けます。
project名の CSV BOM と Fabrication Toolkit JSON は再生成物なので追跡せず、配布時だけ release artifact へ収録します。
