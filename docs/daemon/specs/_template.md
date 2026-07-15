# <daemon> Detailed Spec Template

## 役割

- この daemon が責任を持つことを書く。

## 非役割

- 他 daemon、kernel、host OS、UI が責任を持つことを書く。

## 所有するリソース

- socket:
- device:
- file:
- state:
- service:

## 起動順序

- 起動前提:
- 起動後に満たす状態:
- 依存先が未起動のとき:

## 入力

- source:
- format:
- ordering:
- invalid input:

## 出力

- destination:
- format:
- retry:
- backpressure:

## IPC / API

- endpoint:
- request:
- response:
- compatibility:

## 設定

- config file:
- environment:
- default:
- unknown field:

## 状態管理

- volatile state:
- persistent state:
- restart behavior:

## ログ / 診断

- normal log:
- error log:
- status:
- metrics:

## 異常系とリトライ

- missing dependency:
- broken socket:
- malformed payload:
- device removal:
- timeout:

## 終了処理

- signal:
- cleanup:
- safe output state:

## 実装時に守る条件

- [ ] 既存の observable behavior を壊していない。
- [ ] 依存 daemon が未起動でも停止理由がログに残る。
- [ ] status / socket / JSON field の互換性を壊していない。
- [ ] 実機 smoke で確認する項目が test-matrix に残っている。

## 移植時に維持する互換性

- protocol:
- timing:
- status:
- config:
- logs:

## テスト観点

- unit:
- integration:
- real device:
- fault injection:

## 既知の課題

- 未確定:
- 実機確認待ち:

