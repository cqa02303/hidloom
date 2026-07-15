# InteractionEngine UI/API Plan

作成日: 2026-05-19

`settings.interaction` を HTTP UI / API から編集可能にするための計画メモです。

## 背景

現在の interaction 設定は:

```text
config/default/config.json
```

を直接編集している。

対象:

- tapping_term
- combo_term
- tap_dance_term
- hold_on_other_key_press
- combos
- tap_dances
- key_overrides

既に runtime 側には:

```text
daemon/logicd/interaction_config.py
```

の validation が存在する。

## 目標

```text
HTTP UI
    ↓
interaction validation
    ↓
config save
    ↓
logicd reload
```

## 実装方針

### Phase 1

まずは JSON textarea editor を追加する。

理由:

- 実装が軽い
- validation を流用しやすい
- interaction schema がまだ変化中
- UI を固定化しなくてよい

## API案

### GET

```text
GET /api/interaction
```

返すもの:

```json
{
  "interaction": {...},
  "warnings": []
}
```

### PUT

```text
PUT /api/interaction
```

body:

```json
{
  "interaction": {...}
}
```

返すもの:

```json
{
  "result": "ok",
  "warnings": []
}
```

validation failure:

```json
{
  "result": "error",
  "msg": "..."
}
```

## validation flow

使用:

```text
daemon/logicd/interaction_config.py
```

validation policy:

- invalid combo は reject
- invalid tap dance は reject
- invalid row/col は reject
- unknown action は warning または reject

## runtime reload

保存後:

```bash
systemctl reload logicd-companion
```

touch-panel legacy profileではactiveな`logicd.service`へfallbackする。HTTP APIと
`tools/interaction_physical_runtime.py`はactive unitを判定してreloadする。または:

```text
ctrl socket reload command
```

を送る。

## UI候補

### 最初

- textarea
- save button
- validation result panel

### 将来

- combo visual editor
- tap dance editor
- key override builder
- action autocomplete
- matrix position picker

## 今後の拡張

将来的には:

```text
shared_action_defs.py
```

を使って:

- wrapper action autocomplete
- layer action picker
- BT action picker
- RGB action picker

も可能。
