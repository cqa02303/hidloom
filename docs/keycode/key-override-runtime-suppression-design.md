# Key Override runtime suppression design

作成日: 2026-06-01

この文書は Key Override の suppress / replacement / priority をより厳密にするための設計です。
2026-06-05 に runtime suppression first slice、replacement action allowlist、cross-clear follow-up を実装済みです。
physical trigger suppression、replacement event、modifier state、Mod-Morph / Caps Word / Repeat Key との優先順位、テスト範囲を固定します。

## Goal

- Key Override 発火時に元 key が host へ漏れないようにする。
- replacement press / release の対応を明確にする。
- modifier / one-shot / layer / combo / tap dance / mod-morph と衝突しない優先順位を固定する。
- stuck key を避ける。

## Current baseline

- Key Override は InteractionEngine 系の stateful feature として扱われている。
- Interaction inspector は Key Override の設定 warning を表示できる。
- Mod-Morph / Grave Escape design では Key Override との conflict candidate を持つ。
- `InteractionEngine` は explicit Key Override を Mod-Morph より先に解決する。
- Key Override 発火時は host に出ている trigger action を `key_override` source で一時 release し、replacement release 後に物理 press が残っていれば restore press する。
- `settings.interaction.key_overrides[].replacement` は layer / system / script / connectivity action を validation で reject する。
- output switch / reload / emergency release では active replacement を release し、suppressed trigger を restore しない clear 境界を固定済み。

## Priority candidate

候補:

1. physical matrix press / release
2. combo / tap dance / tap-hold resolution
3. explicit Key Override
4. Mod-Morph / Grave Escape
5. Caps Word / Repeat Key history update
6. output dispatch

方針:

- explicit Key Override は Mod-Morph より優先候補。
- replacement 後の action が repeatable なら Repeat Key history に入る候補。
- suppressed source action は Repeat Key history に入れない。

## Suppression model

State:

```text
override_active[source_key] = replacement_action
override_suppressed_triggers[source_key] = [trigger_action]
```

press:

- condition が満たされたら source action press を出さず、replacement press を出す。
- active mapping を保存する。
- host へ出ている trigger action は replacement press の前に一時 release する。

release:

- press 時に override された key の release は replacement release として扱う。
- release 時点で condition が変わっていても、press 時の replacement を使う。
- replacement release 後、trigger の物理 press が残っていれば trigger action を restore press する。
- trigger が replacement 中に物理 release された場合は restore しない。

## Safety policy

- press / release の pair を必ず保持する。
- output switch / reload / emergency release では、host-visible held interaction action を release してから transient state を clear し、suppressed trigger は restore しない。
- replacement が layer / system / script / connectivity action の場合は validation で reject する。
- suppression state は保存しない。

## UI / inspector policy

- inspector は duplicate trigger / same key / Mod-Morph conflict を warning。
- runtime status は active override count だけ表示候補。action 名は必要最小限。
- save payload に active override state を混ぜない。

## Static tests

実装済み:

- press 時 condition で replacement press。
- release 時 condition が外れても replacement release。
- suppressed source action が host に出ない。
- trigger modifier が replacement report へ漏れないよう、replacement press 前に release し、replacement release 後に restore する。
- trigger が先に物理 release された場合は restore しない。
- Repeat Key history は replacement action を保持し、trigger restore press では上書きしない。
- Mod-Morph より Key Override が優先。
- replacement action allowlist は layer / system / script / connectivity action を reject し、通常 key action、modifier wrapper、MORSE action は許可する。
- output switch / reload / emergency release の cross-clear は replacement release と後続 physical release no-op を固定する。

後続候補:

- 実機で stuck-key recovery に不足が見つかった場合だけ追加する。

## Implementation gate

runtime suppression first slice の達成条件:

- press/release pair owner が決まっている。
- replacement action allowlist は Key Override 専用 validation で固定する。
- priority が InteractionEngine tests で固定できる。

実装しない条件:

- release 時に条件を再評価しないと成立しない。
- suppressed source action を一度 host に出す必要がある。
