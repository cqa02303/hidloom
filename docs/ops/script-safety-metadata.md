# Script safety metadata

更新日: 2026-05-25

KC_SH script editor で reboot / shutdown などの危険操作を見落とさないための
metadata と保守的な自動検出の仕様です。

## Metadata format

script のコメント行に次を置けます。

```sh
# @danger reboot
# @danger shutdown
# @confirm このscriptは本体を再起動します。実行しますか？
# @pin
# @hidden
```

| metadata | 意味 |
| --- | --- |
| `# @danger <name>` | script が危険操作を含むことを明示する |
| `# @confirm <message>` | 実行前確認に出す文言 |
| `# @pin` | 将来 UI で上位表示する候補 |
| `# @hidden` | 将来 default では隠す候補 |

## Conservative auto detection

metadata がない script でも、次のコマンド候補は危険扱いにします。

- `reboot`
- `systemctl reboot`
- `shutdown`
- `poweroff`
- `halt`
- `systemctl poweroff` / `systemctl halt`
- root を対象にした `rm -rf /` 系

誤検出は許容します。危険操作を見落とすより、安全側に倒します。

## 実装状況

- `script_metadata.py` に side-effect free な parser / detector を追加済み。
- `script/test_script_metadata.py` で metadata、自動検出、`@pin` / `@hidden` を検証済み。
- HTTP frontend では `extra_key_groups.js` の後段 patch で、script editor の内容を解析し、危険候補を警告表示する。
- `checkRunScriptContent()` は既存の確認に加え、危険候補を検出した時に追加確認を出す。

## 残課題

- backend の `/api/scripts` と `/api/scripts/{KC_SHn}` に `safety` field を返す。
- runtime script と fallback script の両方で backend 側 metadata を集約する。
- 危険 script の通常 run が backend 経由になった場合、API 側でも確認 token なし実行を拒否する。
- script 一覧で `@pin` / `@hidden` を正式に使う UI を追加する。
