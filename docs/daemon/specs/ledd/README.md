# ledd Detailed Spec

`ledd` は LED strip、VialRGB effect、semantic LED role、direct frame を扱う daemon です。LED failure が入力経路に影響しないこと、runtime effect と direct frame の所有権が混ざらないことを重視します。

## 役割

- LED strip を初期化し、effect / role / direct frame を描画する。
- logicd などからの state change を visual feedback に変換する。
- VialRGB 互換 effect を実行する。

## 非役割

- key action の解決は行わない。
- lighting 設定 UI は `httpd`、protocol 互換は `viald` と分担する。

## 所有するリソース

- 実装: `daemon/ledd/`
- direct-frame socket: [direct-frame-socket-plan.md](direct-frame-socket-plan.md)
- direct-frame fallback: [direct-frame-fallback.md](direct-frame-fallback.md)
- early startup: [early-startup-plan.md](early-startup-plan.md)
- 入力: lighting config、logicd state、direct frame socket
- 出力: LED strip frame、diagnostic log

## 実装時に守る条件

- direct frame owner と effect owner を同時に active にしない。
- LED device missing 時に入力 daemon を巻き込まない。
- shutdown 時に安全な LED state へ戻す方針を守る。
- effect timing 変更時は CPU 負荷と frame drop を確認する。
- splash 系 high-brightness guard を見た目だけで解除しない。matrix idle ghost input の過去事例があるため、brightness 変更時は入力 stability smoke も通す。
- LED effect / direct frame は matrix / logicd input path より低優先とする。

## テスト観点

- direct frame socket。
- semantic role mapping。
- device missing。
- shutdown / restart。
- high-brightness effect 中の matrix idle smoke。

## 関連文書

- [direct-frame-socket-plan.md](direct-frame-socket-plan.md): `LDF1` packet、socket path、producer / ledd responsibility。
- [direct-frame-fallback.md](direct-frame-fallback.md): `keep_last_frame` / `off` / `restore_default` policy。
- [early-startup-plan.md](early-startup-plan.md): startup effect、`logicd-companion` との起動順序、semantic snapshot 同期。
- [../../../lighting/vialrgb-protocol.md](../../../lighting/vialrgb-protocol.md): VialRGB protocol / effect catalog。
