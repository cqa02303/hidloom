# script

開発・検証用スクリプトを置くフォルダです。実機確認用のプレビュー、Vial/VialRGB
検証、HTTP API 検証、logicd のローカル回帰テストを含みます。

実機の daemon socket へ直接イベントを流す手動操作ツールは `tools/` に置きます。
例: `tools/matrix_action_runtime.py`

`script/` に残す非 test helper は、install 補助、systemd unit から直接呼ばれる helper、
既存の Vial/VialRGB / HID live smoke、host 手順から直接呼ぶ互換入口に限ります。repo 生成物の
更新 helper は `build/generators/` へ移動済みです。棚卸し表は
[`docs/ops/test-script-inventory.md`](../docs/ops/test-script-inventory.md) を参照してください。

## Validation

まとめて確認する場合はリポジトリルートで次を実行します。

```bash
python3 script/test_validation_suite.py
```

suite entrypoint は `script/suite_runner.py` の共通 runner を使います。
新しい suite を増やす場合は、対象 test list と suite 名だけを持たせます。
実機向け suite は `sudo` や `tools/` helper を含むため、専用 runner で失敗を集計します。
`test_real_device_keyboard_suite.py` は native owner (`hidloom-logicd-core.service`) が active の場合、
旧 Python-owner の matrix/key_events 直結 smoke を既定で skip します。Python-owner rollback 中に
それらも確認する場合は `--include-python-owner-smoke` を付けます。

```bash
python3 script/test_real_device_keyboard_suite.py
python3 script/test_real_device_touch_panel_suite.py
```

個別に実行できる代表的なテスト:

| スクリプト | 確認内容 |
|------------|----------|
| `test_logicd_joystick.py` | アナログスティックの設定抽出、しきい値、マウス変換、`ctrl_events.sock` 統合 |
| `test_logicd_encoder.py` | matrix-backed encoder のデコード |
| `test_logicd_ctrl_validation.py` | logicd ctrl JSON の入力検証 |
| `test_logicd_lighting_keys.py` | Lighting 系 custom keycode |
| `test_logicd_ledd_semantic_roles_snapshot.py` | logicd-companion が ledd semantic role 定義を snapshot push すること |
| `test_http_lighting_api.py` | HTTP Lighting API |
| `test_http_lighting_layer_overlays.py` | HTTP layer overlay color UI helper |
| `test_http_layout_controls.py` | HTTP layout の joystick / encoder metadata が keymap 定義に追従すること |
| `test_http_remap_keycode_coverage.py` | HTTP remap 候補が `config/default/keycodes.json` の内部キーコードを補完表示できること |
| `test_unimplemented_keycodes_doc.py` | 未実装 keycode 管理ファイルが docs 入口から参照されていること |
| `test_docs_links.py` | repository Markdown の `.md` link が実在 path を指していること |
| `test_script_directory_resolution.py` | logicd と HTTP UI の `KC_SHn.sh` 探索優先順位 |
| `test_vial_protocol_local.py` | hardware なしの Vial protocol dispatch |
| `test_vialrgb_ledd.py` | ledd VialRGB effect / 不正 message 処理 |
| `test_led_life_game_effect.py` | LED Life Game effect の純粋ロジック / metadata |
| `test_usbd_hid_report_broker.py` | usbd USB HID report broker の frame codec / current profile adapter |
| `test_usbd_validation.py` | usbd Raw HID bridge と opt-in local socket の入力検証 |
| `test_logicd_usbd_report_broker_backend.py` | logicd opt-in broker backend が canonical payload を usbd socket へ送ること |
| `test_hidloom_hidd_tool.py` | native `hidloom-hidd` broker の frame 互換、endpoint mapping、live status 更新 |
| `test_hidloom_uidd_tool.py` | native `hidloom-uidd` の keyboard report -> Linux EV_KEY 差分変換、unsupported frame、dry-run status schema |
| `test_hidloom_outputd_tool.py` | native `hidloom-outputd` の usb/uinput/bt forwarding、切替時release、`outputd -> uidd`の`pi` / Enter往復 |
| `test_native_outputd_ctrl.py` | logicd-companion の output switch が native `hidloom-outputd` ctrl target へ変換されること |
| `test_hid_release_roll_analyzer.py` | hidd NDJSON から release flush 直後の next press 候補を抽出する helper |
| `test_buildroot_m1_compare_tool.py` | Raspberry Pi OS baseline と Buildroot M1 marker 比較 helper |
| `test_buildroot_compliance_bundle.py` | M6 legal-info、固定Buildroot source、Bootlin component source/licenseの決定的bundleと改ざん拒否 |
| `test_rust_lockfile_policy.py` | 全Rust実行crateのtracked lockfileとproduction buildの`--locked`強制 |
| `test_pid_codes_application.py` | pid.codes候補の予約範囲、申請draft、再確認、公式merge前の適用禁止 |
| `test_public_usb_identity.py` | private互換/public正式USB・Vial identityの分離、現行値照合、割当前bundle生成拒否 |
| `test_public_export.py` | 全tracked pathのpublic/private/generated分類、生成物exact set、privacy/license/reference/docsを含む決定的clean export |
| `test_vial_protocol.py` | Vial Raw HID protocol |
| `test_vialrgb_protocol.py` | VialRGB protocol |

`test_vial_protocol.py` / `test_vialrgb_protocol.py` / `test_vialrgb_persistence.py` などは
実機 daemon socket が必要な live smoke です。ローカル回帰では
`test_validation_suite.py` と `test_vial_protocol_local.py` を使います。
matrix event を直接送る実機 smoke は、成功・失敗に関わらず release event を送って
`logicd` の pressed state を残さないことを `test_real_device_smoke_cleanup.py` で固定します。

アナログスティックだけを確認する場合:

```bash
python3 script/test_logicd_joystick.py
```

成功時は `ok: analog joystick handling is coherent` を出力します。

## 生成物

KiCad / matrix 解析で再生成できる JSON や report は `build/generated/` に置きます。
出力仕様は [`build/generated/README.md`](../build/generated/README.md) を参照してください。

`build/generators/mkvial.py` は KLE 配置 (`config/default/keyboard-layout.json`) を先に読み、
KiCad 解析結果の matrix 交点を KLE slot 順へ割り当てます。
自動割り当てだけでは表現できない slot は、コード内の特例ではなく
`config/default/vial-layout-overrides.json` に `slot_overrides` / `virtual_slots` として明示します。
生成後は `build/generated/vial_generation_report.txt` の未割当欄を確認してください。

## 非 test helper の置き場

| 区分 | 置き場 | 方針 |
| --- | --- | --- |
| 生成 helper | `build/generators/` | KiCad / Vial / Windows INF / REG など、tracked data や配布物を生成するもの |
| 実機操作・計測 helper | `tools/` | daemon socket、sudo、runtime state、manual smoke に近いもの |
| MCP integration | `dev/mcp/` | Codex / MCP client から使う read-only / future write-capable server |
| install / systemd 直呼び | `script/` | 既存 service / install path の入口として安定させるもの |
| regression / suite | `script/test_*.py`, `script/*_suite.py` | 当面維持 |

新規 helper はこの表に従って置きます。既存の `script/` live smoke は docs と実機手順の参照が多いため、
daemon directory 移動前にはまとめて動かしません。
