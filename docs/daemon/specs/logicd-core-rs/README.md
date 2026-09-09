# logicd-core-rs Detailed Spec

`logicd-core-rs` は `logicd` の boot-critical / latency-sensitive な処理を Rust へ移すための native core です。投入段階では Python `logicd` と責務が重なるため、owner、fallback、二重送出防止を最重要条件にします。

## 役割

- matrix event から最小限の key resolution / HID report 生成を低遅延で行う。
- boot early path で必要な keyboard input を Python 起動前に成立させる。
- Python `logicd` へ残る複雑な control / JSON / feature 処理との境界を維持する。
- 出力先固有の device owner にはならず、broker frame を `hidloom-outputd` へ渡す。

## 非役割

- 全 feature の即時 Rust 移植を前提にしない。
- HTTP UI、複雑な config 編集、Vial import は Python 側に残せる。
- HID endpoint の直接管理は `hidd` / `uidd` の責務とする。

## 所有するリソース

- service: `system/systemd/hidloom-logicd-core.service`
- 関連仕様: [m0-implementation-spec.md](m0-implementation-spec.md)
- 入力: matrix event、最小 keymap snapshot、runtime control subset
- 出力: `/tmp/hidloom_output_reports.sock` への broker frame、status / diagnostic
- 状態: pressed key resolution、minimal layer state、route state

## 実装時に守る条件

- Python `logicd` と同じ physical event を二重処理しない。
- Rust 側に移した state の owner を一意にする。
- 未対応 action は安全に Python path へ委譲するか no-op にする。暗黙に別 action に変換しない。
- fallback 時に stuck key を残さない。
- Rust 側の JSON loader は既存 config 互換を壊さない。複雑な JSON 解釈を持たせる場合は `logicd` の compatibility checklist と同じ項目を通す。
- legacy `LOGICD_USBD_HID_REPORT_BROKER` を通常運用の owner として復活させない。A/B 診断で使う場合は rollback 手順を先に記録する。
- native `logicd-core-rs -> hidloom-hidd` owner path と Python companion fan-out を同時 active にしない。
- 現行 native path は `logicd-core-rs -> hidloom-outputd -> hidloom-hidd` とし、USB / uinput / BT target owner を core に戻さない。
- Windows IME / custom HID の診断 route を通常 keyboard route の成功条件と混同しない。

## 入力・委譲の所有権

状態確認・操作順序・解除を実行ownerへ集約する判断は[ADR-0024](../../../policy/adr/0024-native-owner-transactions.md)に記録する。

keyboard profileではnative coreがlayer状態の正本を持つ。delegate protocol v2はowner epoch、keymap/layer revision、
event順序、入力source、押下時actionとlayer snapshotを運び、companionが返すlayer操作をACK単位で検証して反映する。
不正なsourceや同一batch内の所有権衝突、古いACKは一部だけ適用せず拒否する。companion待ちの未解決pressは有限queueで待たせ、
既にnativeで解決したkeyのrelease、control処理、guarded tapの解放期限は進める。layer/tapの既定時間は変えない。

明示的な入力sessionはcontrol streamの `source_open` → `source_event` / `source_ping` → `source_close` を使う。
source識別子はownerが発行するopaque値（nativeでは正整数、Pythonでは文字列）で、clientから他sourceを指定できない。
既定leaseは30秒。EOF・lease切れでは該当sourceの寄与だけを解除し、同座標の他sourceやphysical入力を保持する。
legacyな1イベントごとの4-byte matrix接続は従来の寿命を維持する。

guarded tapは実行ownerが現在のaction・revision・modifier/layer・idle・auto出力状態を同じ処理内で確認し、
専用sourceのpressと解放予約を行う。operation IDの再試行は重複実行しない。結果の `started` / `released` はownerの状態であり、
host applicationの受信証明ではない。通信停滞や切断の試験は実socketを隔離した回帰で確認する。

companion/observer接続とbroker配送はnonblockingにする。配送が詰まった場合は有限bufferで扱い、通常時のreport順序を維持する。
飽和時は最新のendpoint別状態へまとめて古い押下の復活を防ぎ、配送劣化をstatusに残す。未配送reportがある間はguarded tapを受理しない。

## 移植時に維持する互換性

- press / release pairing は Python `logicd` と一致する。
- output report は report ID / length / ordering が既存 route と一致する。
- output target 切替は `hidloom-outputd` control plane に委譲する。
- status field は UI / diagnostic が読める形を維持する。
- service restart 後に古い pressed state を復元しない。

## テスト観点

- Python path と Rust path の同一入力 A/B report 比較。
- 未対応 action 入力時の fallback / no-op。
- service restart、source disconnect、hidd disconnect。
- 実機 boot 直後の first key latency。

## 既知の課題

- M0 以降にどの feature を Rust owner にするかは、機能ごとに `logicd` 側の behavior-contract へ条件を追記してから移す。
