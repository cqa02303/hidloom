# hidloom-hidd Deep Test Plan

作成日: 2026-06-19

この文書は、`hidloom-hidd` native HID report broker M0 を
Python `usbd` の代替 owner として昇格できるかを判断した時の深いテスト計画である。
2026-06-21 現在は default owner promotion 済みで、今後は broker / core route 変更時の
regression runbook として扱う。
実装仕様は [../daemon/specs/hidd/m0-implementation-spec.md](../daemon/specs/hidd/m0-implementation-spec.md)、
実機チェック項目は private workspace reference *(omitted from public export)* を参照する。

## 現在地

2026-06-21 時点で確認済み:

- `<keyboard-host>` に Rust toolchain を導入済み。
- `tools/hidloom_hidd/build.sh` により ARM64 `bin/hidloom-hidd` を build 済み。
- temp endpoint を使う `script/test_hidloom_hidd_tool.py` は実機上で通過済み。
- `hidloom-hidd.service` は default USB HID owner として enabled / active。
  Python `usbd.service` は通常 inactive で、rollback / A/B 診断用に残す。
- `/tmp/usbd_hid_reports.sock`、`/dev/hidg0`、`/dev/hidg1`、`/dev/hidg2` の smoke は通過済み。
  Raw HID / Vial bridge も `hidloom-hidd` 側へ移管済み。

まだ確認していないこと:

- 長めの実入力 soak。
- broker / core route を変更した後の host-side regression。

## 方針

テストは安全な順に 6 段階で進める。
各段階は rollback 条件を満たしたら helper で Python `usbd` owner へ戻し、確認後に native owner へ restore する。

| Phase | 対象 | 実機 | 目的 |
| --- | --- | --- | --- |
| P0 | Static / fixture | 不要 | frame 互換と文書・unit の整合を固定する |
| P1 | Process / socket / temp endpoint | 不要または実機任意 | long-running daemon と status の基本動作を確認する |
| P2 | Real endpoint safe smoke | 必要 | 実 `/dev/hidg0` / `/dev/hidg2` へ副作用の少ない report を流す |
| P3 | Host-visible functional | 必要 | keyboard / mouse / consumer / US-sub が host で期待通り見えることを確認する |
| P4 | Fault injection / recovery | 必要 | replug、restart、stuck-key、malformed burst に耐えることを確認する |
| P5 | Boot promotion rehearsal | 必要 | boot owner 昇格時の時刻・rollback・運用観測を確認する |

## 共通前提

対象 device:

- 第一候補: `<keyboard-host>`
- 比較候補: `<keyboard-host>` は gadget / broker timing には使えるが、matrixd が light profile で inactive の場合は full input timing には使わない。

事前確認:

```bash
systemctl is-active hidloom-usb-gadget.service hidloom-hidd.service hidloom-logicd-core.service logicd-companion.service matrixd.service
systemctl is-active usbd.service || true
systemctl is-enabled hidloom-hidd.service hidloom-logicd-core.service || true
ls -l /dev/hidg0 /dev/hidg1 /dev/hidg2
test -x bin/hidloom-hidd
python3 script/test_hidloom_hidd_tool.py
```

rollback rehearsal:

```bash
python3 tools/logicd_core_owner_recovery.py --apply
python3 tools/logicd_core_native_owner_restore.py --apply
systemctl is-active hidloom-hidd.service hidloom-logicd-core.service logicd-companion.service matrixd.service
systemctl is-active usbd.service || true
```

停止条件:

- host 側に stuck key / stuck button が残る。
- `write_errors` が増え続ける。
- `/tmp/usbd_hid_reports.sock` owner が不明になる。
- `usbd.service` と `hidloom-hidd.service` が同時に broker socket を持つ。
- `logicd` / `matrixd` が再起動ループに入る。

## P0 Static / Fixture

目的:

- Python `usbd` broker frame との byte parity を固定する。
- systemd owner selection が二重 owner を作らないことを固定する。
- ドキュメントと test inventory が実装状態と一致していることを確認する。

実行:

```bash
cargo fmt --manifest-path tools/hidloom_hidd/Cargo.toml -- --check
make -C tools/hidloom_hidd clean all
python3 script/test_hidloom_hidd_tool.py
python3 script/test_usbd_hid_report_broker.py
python3 script/test_logicd_usbd_report_broker_backend.py
python3 script/test_install_account_portability.py
python3 script/test_power_shed_boot.py
python3 script/test_docs_links.py
python3 script/test_docs_reorg.py
```

追加したい regression:

- valid frame 全 kind の exact report bytes。
- invalid magic / version / checksum / reserved / payload length / unknown kind。
- keyboard dedup on/off。
- release merge same key / different key / consumer flush / mouse flush。
- mouse motion saturation and coalesce。
- status write failure を HID path failure にしないこと。

合格条件:

- warning なしで build できる。
- temp endpoint output が Python broker adapter と一致する。
- `hidloom-hidd.service` が `Conflicts=usbd.service` を持つ。

## P1 Process / Socket / Temp Endpoint

目的:

- `hidloom-hidd` が long-running daemon として live status を更新する。
- socket unlink / rebind / mode / finite run が安定する。
- endpoint file が通常 file / FIFO 相当でも report 単位で壊れない。

実行例:

```bash
tmp=$(mktemp -d)
USBD_HID_REPORT_SOCKET="$tmp/usbd_hid_reports.sock" \
USBD_HID_REPORT_PATH="$tmp/hidg0" \
USBD_US_SUB_HID_REPORT_PATH="$tmp/hidg2" \
HIDD_STATUS_PATH="$tmp/hidd-status.json" \
tools/hidloom_hidd/target/release/hidloom-hidd --frames 4
```

確認項目:

- startup status と frame 後 status が分かれる。
- `frames_received` と kind 別 counter が一致する。
- invalid frame は `invalid_frames` のみ増え、endpoint bytes は増えない。
- `--frames N` は N datagram で自然終了し、socket file を削除する。
- long-running mode を `SIGTERM` で止めても次回 bind に stale socket が残らない。

合格条件:

- 100 回程度の start / send / exit loop で失敗しない。
- status JSON が常に parse 可能。

## P2 Real Endpoint Safe Smoke

目的:

- 実 `/dev/hidg0` / `/dev/hidg2` に open / write できることを確認する。
- host-visible な文字入力や click を避け、null report で transport だけを確認する。

手順:

1. Python `usbd.service` を停止する。
2. alternate socket または canonical socket で `hidloom-hidd` を起動する。
3. keyboard null report と US-sub null report を送る。
4. status counter と `write_errors=0` を確認する。
5. 必要に応じて rollback / restore helper で owner 往復を確認する。

合格条件:

- `hidg0.open=true`、`hidg2.open=true`。
- `frames_received>=2`。
- `keyboard_reports>=1`、`us_sub_keyboard_reports>=1`。
- `write_errors=0`、`dropped_reports=0`。
- 復帰後 `hidloom-hidd.service` / `hidloom-logicd-core.service` /
  `logicd-companion.service` / `matrixd.service` が active、`usbd.service` は inactive。

## P3 Host-visible Functional

目的:

- host から見える実入力が Python `usbd` owner と同じであることを確認する。
- 日本語入力や modifier の事故を避けるため、最初は安全な text editor / test page を使う。

テストセット:

| Route | 入力 | 期待 |
| --- | --- | --- |
| main keyboard | `KC_A` press/release | focused safe editor に `a` |
| modifier | `KC_LSFT` + `KC_A` | `A`。release 後 modifier が残らない |
| US sub keyboard | `KC_LANG1` / `KC_LANG2` route または US-sub test key | Windows で US sub keyboard として report が出る |
| consumer | volume up/down または safe media key | host が Consumer Control として受ける。連打後 stuck しない |
| mouse motion | small dx/dy | cursor が小さく動き、keyboard route に影響しない |
| mouse button | click down/up | button release が残らない |
| mixed | keyboard while mouse motion burst | keyboard が遅延・欠落しない |

測定:

- host 側の入力結果。
- `/run/hidloom/hidd-status.json` counter。
- `journalctl -u hidloom-hidd -u hidloom-outputd -u hidloom-logicd-core -u logicd-companion -u matrixd -u hidloom-usb-gadget`。
- 必要なら `tools/boot_marker_baseline.py` と `tools/perf_baseline.py`。

合格条件:

- Python `usbd` owner と visible behavior が一致する。
- key / button release が host に残らない。
- `invalid_frames=0`、`write_errors=0`。

## P4 Fault Injection / Recovery

目的:

- 実運用で起きやすい fault に対して、壊れたままにならないことを確認する。

項目:

| Fault | 手順 | 合格条件 |
| --- | --- | --- |
| malformed burst | invalid frame を 1000 件送る | daemon 継続、endpoint write なし、`invalid_frames=1000` |
| writer burst | keyboard / mouse / consumer frame を高頻度送信 | CPU が張り付き続けず、counter と host behavior が説明可能 |
| service restart | report 送信中に `systemctl restart hidloom-hidd` | socket 復帰、stuck key なし |
| logicd restart | key report 後に `systemctl restart logicd` | release / null report recovery が効く |
| USB replug | host cable を抜き差し | endpoint reopen または clear failure status。復帰後 report 送信可 |
| endpoint missing | gadget setup 前後または service ordering 変化 | daemon が落ち続けず status に error を出す |
| disk/status failure | status path を書けない場所へ向ける | HID write path は継続 |

注意:

- held-key crash は safe host input target でだけ実施する。
- 破壊的・手作業 rollback が必要な fault は、観測者が host 側を見られる時に限定する。

合格条件:

- fault 後に Python `usbd` owner へ戻せる。
- failed unit が残らない。
- host 側の stuck key / stuck button が残らない。

## P5 Boot Promotion Rehearsal

目的:

- `hidloom-hidd` を default boot owner にした時、Python `usbd` baseline より input-to-HID readiness が改善するかを測る。
- rollback / restore が単純であることを確認する。

比較対象:

- Baseline A: historical Python `usbd.service` owner。
- Candidate B: current `hidloom-hidd.service` owner、Python `usbd.service` broker disabled/stopped。

測定 marker:

| Marker | 取得元 |
| --- | --- |
| USB gadget configured | `journalctl -u hidloom-usb-gadget` |
| `/dev/hidg0` / `/dev/hidg2` present | boot journal / helper |
| broker socket listening | `hidloom-hidd` status / journal |
| logicd sockets listening | `logicd` boot marker |
| matrixd connected | `matrixd` journal |
| first host-visible key accepted | host-side watcher or manual timestamp |

手順:

1. Baseline A を最低 3 boot 取る。
2. Candidate B を最低 3 boot 取る。
3. kernel/userspace variance と marker variance を分ける。
4. average だけでなく best / worst / p50 相当を残す。
5. Candidate B のまま validation と host-visible smoke を実行する。
6. rollback helper で Baseline A へ戻し、restore helper で Candidate B へ戻せることを確認する。

昇格条件:

- broker socket readiness が Python `usbd` baseline より明確に早い。
- host-visible input behavior が P3 と同等。
- P4 の critical fault が通る。
- `/api/status` または read-only diagnostic で owner を判別できる。
- helper で Python `usbd.service` owner へ戻し、native owner へ戻す手順が 1 分以内に完了する。

## 追加実装が必要になり得るテスト

深いテスト中に不足が出た場合、先に regression を追加してから修正する。

優先候補:

- `script/test_hidloom_hidd_tool.py` に invalid frame matrix を追加する。
- mouse coalesce の timestamp-free deterministic test を追加する。
- endpoint reopen / write error を mock endpoint で再現する unit test を追加する。
- status write failure test を追加する。
- service owner static test に `Conflicts=usbd.service` と native default owner を固定する。
- boot marker collection helper に `hidloom-hidd` owner marker を追加する。

## 記録テンプレート

```text
Date:
Device:
Git commit:
Owner: python-usbd / hidloom-hidd
Host OS:
Power source:
Boot sample count:

Markers:
- gadget configured:
- broker listening:
- logicd sockets:
- matrixd connected:
- first host-visible input:

Smoke:
- keyboard:
- modifier:
- consumer:
- mouse:
- US sub:

Fault:
- malformed burst:
- restart:
- replug:
- held-key recovery:

Result:
- pass/fail:
- rollback performed:
- follow-up:
```

## 完了判定

`hidloom-hidd` の default boot owner 昇格は完了済み。今後この計画を使う場合は、
broker / core route 変更時の regression checklist として扱い、残る failure が
「観測済みで rollback / restore 手順が明確」なものだけになっていることを確認する。
