# HTTP static assets

HTTP UI の静的 asset 配置ルールです。

Web iconは`tools/generate_hidloom_icons.py`で生成するHIDloom固有のloom/matrix markです。
PNG / ICOを手で置換せず、generatorを更新して`script/test_hidloom_icon_assets.py`で再現性を確認します。

## 基本方針

- JS は DOM 生成、API 呼び出し、状態更新、イベント処理を担当する。
- 恒久的な見た目は CSS asset に置く。
- `document.createElement("style")` のような inline style injection は原則使わない。
- 一時的な座標、色 preview、canvas 風の動的値だけは JS の `style` property 利用を許容する。
- 新しい UI panel を追加したら、JS と CSS を機能単位で分ける。

## CSS 構成

| file | role |
|---|---|
| `keyboard.css` | 全体 layout、共通 component、既存 keyboard / system / script / lighting の大枠 |
| `interaction_panel.css` | Interaction panel 本体。現在は既存の追加 CSS を読み込む aggregator も兼ねる |
| `status_panel.css` | System status の追加表示。Bluetooth host overview など |
| `remap_quick_keys.css` | remap popup の pinned / recent / docs guide |
| `lighting_panel.css` | Lighting tab の direct-frame metrics / role preview |
| `oled_panel.css` | OLED tab の用途別icon list、pixel grid、icon preview、Ready layout editor |
| `apple_design.css` | 共通の視覚・操作基盤。system typography、translucent shell、press feedback、dark / reduced-motion / reduced-transparency / high-contrast対応 |

現在 `index.html` では `keyboard.css` と `interaction_panel.css` を読み込み、
`interaction_panel.css` が feature CSS を `@import` しています。
最後に `apple_design.css` を読み込み、feature固有のDOMや挙動を変えずに共通design tokenとinteraction feedbackを適用します。
タブ操作は `tabs.js` でARIA stateと左右矢印/Home/Endキーを同期し、処理中・完了・失敗のstatusはlive regionとして即時に伝えます。
将来的には `index.html` の `<head>` に feature CSS を直接 link してもよいですが、
その場合も CSS の責務分離は維持します。

## 謝辞

Web UIの視覚設計、操作時のフィードバック、モーション、アクセシビリティの見直しでは、
Emil Kowalski氏が公開している
[Apple Design SKILL.md](https://github.com/emilkowalski/skills/blob/main/skills/apple-design/SKILL.md)
を参考にさせていただきました。Web向けに整理された有益なデザイン原則を公開してくださったことに感謝します。

この資料は設計上の参考資料であり、HIDloomのruntime依存関係や配布物には含まれません。

## JS 構成

| file | role |
|---|---|
| `status_panel.js` | `/api/status` polling、System panel 更新、Bluetooth host overview DOM 更新 |
| `lighting_panel.js` | Lighting API、effect selector、direct-frame metrics、role preview DOM 更新 |
| `remap_quick_keys.js` | remap popup の pinned / recent localStorage helper |
| `remap_panel.js` | remap popup 本体、keycode group rendering、search/filter |
| `interaction_panel.js` | Interaction setting editor / summary / builder |
| `oled_panel.js` | OLED iconを実表示順のDaemon status / Output mode / Otherに分けて編集（左クリック点灯・右クリック消去）、Ready行編集、browser preview、`/api/oled`保存 |

## 回帰テスト

CSS / JS の責務が崩れないよう、次の静的テストで確認します。

```bash
python3 script/test_http_system_status.py
python3 script/test_http_lighting_api.py
python3 script/test_http_ui_assets.py
python3 script/test_oled_customization.py
python3 script/test_oled_pointer_editing.py
```

確認していること:

- status / lighting / remap quick access の恒久 style が CSS asset 側にある。
- JS に `document.createElement("style")` による inline style injection がない。
- `interaction_panel.css` から feature CSS を読み込んでいる。
- OLED icon catalogが実際のdaemon/output表示定義と順序を共有し、全iconを重複なく分類する。
- OLED pixel通常描画はcell DOMだけを更新し、pointer release、cancel、window blur、非表示化でdrag状態を解除する。release後の`buttons=0` hoverでは描画しない。
