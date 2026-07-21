# HTTP UI internationalization design

更新日: 2026-07-20

## 目的

HIDloom HTTP UIの表示文言をbrowserの優先言語に合わせ、利用者が手動で上書きできるようにします。
保存データ、keycode、API schema、daemon messageは翻訳せず、UI chrome、説明、操作結果だけを翻訳対象にします。

## 実装

初回調査では日本語を含む文言が`index.html`に177件、JavaScript assetに約600件あります。
文言は静的HTML、DOM生成、status更新、error、confirm、title/ARIAへ分散しているため、一括置換は行いません。

`daemon/http/static/i18n.js`を追加し、次を実装しました。

- `?lang=ja` / `?lang=en` / `?lang=auto`を最優先する。
- 手動選択を`localStorage`の`hidloom-ui-language`へ保存する。
- `navigator.languages`を先頭から評価し、`ja-JP`のような地域tagを`ja`へ正規化する。
- 対応言語がない場合は英語へfallbackする。
- 選択言語に合わせて`html.lang`を更新する。
- `data-i18n`、`data-i18n-title`、`data-i18n-aria-label`を同じ辞書から更新する。
- 動的DOM用に`window.hidloomI18n.t()`と`apply()`を公開する。
- 既存moduleが生成する動的文言は、`MutationObserver`を使う移行bridgeで翻訳する。
- `confirm`、`prompt`、`alert`に渡される既存の日本語操作文も同じbridgeで翻訳する。
- 新規UIは意味単位の翻訳keyを使い、移行bridgeへ新たな文言を増やさない。

## 言語解決順序

1. URL query `lang`
2. 利用者が選択して保存した言語
3. `navigator.languages` / `navigator.language`
4. 英語

URL overrideは一時的なvisual smokeに使い、自動では保存しません。UI selectorを操作した場合だけ保存します。

## 翻訳キー

キーは画面ではなく意味で分類します。

```text
actions.save
actions.reload
tabs.keyboard
system.detail
settings.authentication.title
errors.layoutFetch
```

文中の可変値は`{name}`形式にし、HTMLを辞書へ入れません。keycode、service名、JSON field名は翻訳しません。

## 移行方針

共通header、tabs、System表示切替は意味単位のkeyへ移行済みです。Keyboard / Keymap、
Settings、Lighting、OLED、Scripts、Interactionの既存動的文言は移行bridgeで英語表示し、
機能改修時に順次意味単位のkeyへ置き換えます。静的HTMLとJavaScript文字列の未翻訳監査、
実browserによる日本語・英語DOM smokeを回帰testに含めます。

英語の長いlabelによるoverflow、mobile tab scroll、keyboard操作、ARIA、
`prefers-reduced-motion`はUI変更時に確認します。

## 非対象

- `/api/*` response schemaと保存JSON
- QMK/Vial keycodeとprotocol identifier
- systemd service名、journal本文
- 利用者が入力したscript、定型文、key label
- daemon内部の診断message

API errorを画面表示するときは安定したerror codeがあるものだけUI側で翻訳し、未知のmessageは原文を補足として残します。

## 検証

- browser言語`ja-JP`、`en-US`、未対応言語のfallback
- `?lang=`が保存値より優先されること
- manual selectorの永続化
- `html.lang`、text、title、ARIA labelの同期
- 翻訳後もtabの左右/Home/End操作が維持されること
- CSPやnetwork接続なしで初期化できること
