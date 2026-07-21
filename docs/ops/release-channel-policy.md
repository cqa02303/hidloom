# Release Channel Policy

HIDloomの開発、公開source同期、実機release candidate、正式binary公開を、pid.codesの待ち時間から
分離するための昇格方針です。pid.codes割当は`stable-public`だけを停止し、private開発、
`source-public`、`internal-rc`を停止しません。

正規の機械可読契約は[`config/release-channels.json`](../../config/release-channels.json)です。

## Channels

| channel | 公開範囲 | PID割当 | build provenance | 実機smoke | public binary upload |
|---|---|---:|---:|---:|---:|
| `source-public` | 監査済みsource | 不要 | 不要 | 不要 | 不可 |
| `internal-rc` | 内部package/image候補 | 不要 | 必須 | 必須 | 不可 |
| `stable-public` | turnkey package/image | 必須 | 必須 | 必須 | 可 |

現行`development_compatibility` USB identityは内部検証専用です。pid.codesで割り当てられる前の
`1209:484C`をruntimeへ適用せず、現行identityを含むbinaryをpublic Releaseへuploadしません。

## Source Publication

PID待ちを例外扱いせず、source公開channelの通常状態として検証します。

```bash
python3 tools/public_release_readiness.py . --channel source-public
python3 tools/public_sync_plan.py build/public-export --channel source-public
```

`source-public`はrepository source、documentation、license、SBOM、privacy、reference、manifestを
検証します。packageとimageの配布可能性は主張しません。

## Internal Release Candidate

内部RCは、exact source commit、package、M6 image、対応source、checksum、build provenance、
実機smokeを一つのimmutable candidateへ固定します。

```bash
python3 tools/public_release_readiness.py . \
  --channel internal-rc \
  --compliance-bundle build/artifacts/hidloom-buildroot-m6-compliance.tar.zst

tools/package/build_zero2w_keyboard_release.sh \
  --channel internal-rc \
  --output build/release-candidates/<version>-<source-sha> \
  --hardware-smoke-status pass \
  --usable-keyboard-seconds <seconds>

python3 tools/public_release_bundle.py \
  --verify build/release-candidates/<version>-<source-sha> \
  --require-channel-ready internal-rc
```

`internal-rc`の`ready=true`はPID割当を要求しませんが、build provenanceと対象profileの実機smokeを
要求します。`publish_public_release_bundle.py`はこのchannelを常に拒否します。候補directoryを
上書きせず、source commitとchecksumをcandidate identityとして保持します。

## Stable Promotion

pid.codes承認時に開発headを無条件でrelease対象にしません。直近の`internal-rc ready=true`候補を
選び、そのcandidate sourceへ正式USB identityだけを適用して再buildします。

```bash
tools/package/build_zero2w_keyboard_release.sh \
  --channel stable-public \
  --output build/stable-public/<version>

python3 tools/public_release_bundle.py \
  --verify build/stable-public/<version> \
  --require-channel-ready stable-public
```

正式identity適用後はWindows fresh enumeration、JP main / US sub、Raw HID / Vial、USB再接続、
再起動保持、package/M6最終smokeを行います。数か月分のprivate履歴を一括再試験するのではなく、
継続検証済みcandidateに対するidentity差分と最終smokeを確認します。

## Change Impact

| 変更範囲 | 必須確認 |
|---|---|
| docs、license、公開metadataのみ | `source-public`とcanonical自動テスト |
| HTTP/OLED editor、icon、表示定義 | package自動テスト、対象profileの画面smoke |
| daemon、keymap、SHn、systemd | `keyboard-ver1` package smoke |
| USB descriptor、HID routing、Vial、共有runtime、Buildroot overlay | package smokeとexact M6 full smoke |
| touch profile、kiosk、touch UI | `touch-waveshare-8.8` packageとtouch-ready smoke |
| public USB identity | Windows fresh enumerationを含む`stable-public`最終gate |

複数範囲へまたがる変更は必須確認を合算します。実機確認待ちでもsource同期と自動検証を止めず、
候補を`internal-rc ready=false`として保持し、必要な実機結果が揃った時点で同じexact sourceから
再生成します。

## Evidence

候補ごとに少なくとも次を保存します。

- source commit、source snapshot SHA-256、export manifest SHA-256
- package version、package/image SHA-256、Buildroot commit
- device profile、実機smoke結果、usable-keyboardまたはtouch-ready時間
- output targetを変更した場合の`auto`復帰状態
- `RELEASE_MANIFEST.json`、`SHA256SUMS`、対応source/compliance archive

正式公開は[`release-packaging-runbook.md`](release-packaging-runbook.md)、実機証跡は
private workspace reference *(omitted from public export)*を正とします。
