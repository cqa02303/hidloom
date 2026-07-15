# config/default/script/ — KC_SH0 ～ KC_SH10 に対応するシェルスクリプト置き場

## 概要

`KC_SH0` ～ `KC_SH10` キーが押されると、logicd が対応する `.sh` スクリプトを
子プロセスとして実行します。スクリプトの exit code は i2cd に JSON で通知されます。

Vial GUI では、任意名の `SCRIPT(...)` action や Vial macro 機能ではなく、
`KC_SH0` ～ `KC_SH10` の custom keycode として割り当てます。
Vial GUI の Macros タブは本プロジェクトでは未対応です。

## スクリプトの配置

| 優先順位 | パス                         | 説明                   |
|----------|------------------------------|------------------------|
| 1        | `/mnt/p3/script/KC_SHn.sh`  | SD カード P3 パーティション（本番） |
| 2        | `config/default/script/KC_SHn.sh`     | リポジトリ内フォールバック（開発用）|

`config/default/config.json` の `settings.script_dir` でディレクトリを変更できます。
デフォルト（未設定時）は `/mnt/p3/script` → `config/default/script/` の順でフォールバックします。

## スクリプト内の repository root 解決

`logicd` / `logicd-companion` から実行される時は、環境変数 `HIDLOOM_REPO_ROOT`
が渡されます。package-managed deployment ではこの値は `/usr/lib/hidloom`
です。

`KC_SH7.sh` と `KC_SH8.sh` は manual fallback として単体実行される可能性が
あるため、`HIDLOOM_REPO_ROOT` が無い場合は次の順で tool root を探します。

1. `/usr/lib/hidloom` の package root
2. `config/default/script/` 配置から見た repository root
3. `/usr/lib/hidloom` fallback

実機側 checkout を退避した後でも、default script が `/home/pi/hidloom`
や `/home/USERNAME/hidloom` に戻らないことを前提にします。

## ファイル命名規則

```
KC_SH0.sh  … KC_SH0 キーに対応（安全な no-op）
KC_SH1.sh  … KC_SH1 キーに対応
   ︙
KC_SH7.sh  … PTY Mirror M0（sessiond を user 権限で必要時起動して開始）
KC_SH10.sh … KC_SH10 キーに対応（再起動）
```

## 表示ラベルのメタデータ

HTTP 画面で表示する `KC_SHn` のラベルは、スクリプト内の `@label`
メタデータから読み取られます。

```sh
#!/bin/sh
# @label 表示名
```

説明コメントの位置や内容を変えても表示名が崩れないよう、表示用途の文字列は
通常コメントとは分けて `# @label ...` で記述してください。

## 通知フロー

```
[キー押下]
    ↓
logicd: asyncio.create_subprocess_exec("/bin/sh", "KC_SHn.sh")
    ↓ (プロセス終了)
logicd → i2cd : {"t":"script_exit","name":"KC_SHn","code":<exit_code>}
    ↓
i2cd: ログ出力と OLED alert 表示
```

## exit code 規則（推奨）

| exit code | 意味                  |
|-----------|-----------------------|
| 0         | 成功                  |
| 1–126     | スクリプト定義のエラー |
| 127       | スクリプトファイルが見つからない |
| -1        | 実行中に予期しない例外 |

## サンプル

`KC_SH0.sh` はスクリプトエディタで最初に表示されるため、安全な no-op にしています。
再起動スクリプトは `KC_SH10.sh` に置いています。

`KC_SH1.sh` 以降に使用例のコメントを記載しています。
実際の用途に合わせて各スクリプトを書き換えてください。
