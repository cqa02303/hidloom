# Bluetooth multi-host operation UI design

作成日: 2026-06-01

この文書は Bluetooth paired host を複数扱う UI / operation の設計です。
2026-06-01 時点では実装へは進まず、host 一覧、active host、rename / forget / disconnect / reconnect の UI 境界、audit log、実機確認範囲を固定します。

## Goal

- paired / bonded / trusted host の一覧を read-only に分かりやすく表示する。
- active host と last connected host を区別する。
- rename / forget / disconnect のような危険操作を、誤操作しにくい UI にする。
- multi-host 切替を実装する前に、BlueZ / btd / logicd の owner 境界を固定する。

## Current baseline

- Bluetooth HID backend は btd が owner。
- HTTP System panel は Bluetooth status / host overview の read-only 表示を持つ。
- `last_connected_at` / `last_connected_source` は設計済み。
- Host profile は [feature/host-profile-design.md](../feature/host-profile-design.md) に分離済み。
- paired host reconnect / HID notify ready の実機確認は残っている。

## Host metadata

UI に出す候補:

| field | 意味 |
| --- | --- |
| `address` | BlueZ device address。primary key 候補。 |
| `alias` | user-visible host name。rename UI の対象候補。 |
| `name` | device provided name。read-only 候補。 |
| `paired` | BlueZ Paired。 |
| `bonded` | BlueZ Bonded。 |
| `trusted` | BlueZ Trusted。 |
| `connected` | BlueZ Connected。 |
| `notify_ready` | HID Input Report notify path が使えるか。 |
| `last_connected_at` | 最後に接続した時刻。 |
| `last_connected_source` | event source。 |
| `profile` | host profile metadata。read-only merge 候補。 |

## UI sections

Stable English labels for static checks:

- read-only host list
- active host
- last connected
- notify_ready
- host profile metadata is read-only merge

Stable Japanese boundary labels:

- HTTP から BlueZ を直接操作しない
- host profile metadata は read-only merge
- forget しても profile config を自動削除しない

### Read-only host list

- address / alias / connected / trusted / last connected を表示する。
- active host は badge で表示する。
- profile がある場合は profile label を併記する。
- connected でも notify_ready でない場合は warning を出す。

### Host detail

- BlueZ status detail を表示する。
- rename / forget / disconnect は detail panel 内の明示 action にする。
- destructive action は一覧 row から直接実行しない。

### Operation queue

複数 host 操作を同時に投げない。

- pairing mode start / stop
- disconnect
- forget
- rename
- reconnect request

これらは同時実行せず、UI 側は pending state を持つ候補。

## Operation boundaries

| operation | 初期扱い | confirmation |
| --- | --- | --- |
| rename alias | 後続候補。local label か BlueZ Alias かを分ける | 軽い確認 |
| forget host | destructive。bond が消える | 必須 |
| disconnect host | 一時切断 | 確認候補 |
| reconnect host | 実機確認後 | 失敗表示必須 |
| set trusted | 初期 UI では作らない | n/a |
| active host switch | btd / BlueZ の再接続実験後 | 必須 |

## Owner / data flow

| layer | owner |
| --- | --- |
| BlueZ device list / pair / forget / disconnect | `btd` / BlueZ manager |
| host metadata merge | HTTP status / system panel helper candidate |
| active output target | `logicd` output routing |
| HID notify readiness | `btd` GATT backend |
| host profile metadata | `logicd.host_profile_status` / profile config |
| UI action confirmation | `httpd` / frontend |

`httpd` は BlueZ を直接操作しない。
危険操作は btd / logicd の API 境界を通す。

## Audit / logging policy

- forget / disconnect / rename は audit log に残す。
- address は表示するが、必要なら UI では短縮表示にする。
- host alias の変更は old / new を記録する。
- failed operation は reason を status に残す。
- password や pairing secret は log に出さない。

## Safety policy

- destructive operation は confirmation 必須。
- paired host が 0 の場合は forget UI を disabled。
- current active host を forget する場合は追加 warning。
- output target が `bt` の時に active host を切る操作は warning。
- operation 中は pairable / discoverable state を勝手に変えない。
- host profile と host forget を混ぜない。profile 削除は別操作。

## Real-device checks

- iOS / Windows / Linux / Android で paired host list が安定して取れるか。
- connected と notify_ready の差分。
- disconnect 後の reconnect。
- forget 後の re-pair。
- btd restart 後の last_connected_at / active host 表示。
- HTTP UI 操作時の btd / logicd log。

## Static tests to add with implementation

設計 first slice では doc test だけを追加する。
実装へ進む場合は以下を追加する。

- host list payload が read-only fields と operation fields を分ける。
- destructive action には confirmation flag がある。
- active host forget warning が出る。
- HTTP route が BlueZ を直接操作しない。
- operation pending 中は二重操作しない。
- audit log に forget / disconnect / rename が残る。
- host profile metadata は read-only merge で、forget しても profile config を自動削除しない。

## Implementation gate

実装へ進める条件:

- paired host がある状態で reconnect / notify_ready / last_connected_at を観測できる。
- btd 側の host operation API 境界が決まっている。
- destructive action confirmation と audit log をテストで固定できる。
- host profile と BlueZ device operation の owner を分けられる。

実装しない条件:

- HTTP から BlueZ を直接操作する必要がある。
- active host / last connected / notify_ready を区別できない。
- forget と profile 削除を同じ操作にする必要がある。
- multi-host switch が keyboard output を不安定にする。
