# build/

生成物と生成用ツールを置く領域です。

| ディレクトリ | 役割 |
| --- | --- |
| [`generated/`](generated/README.md) | KiCad / matrix / Vial 生成で再作成できる tracked data と report |
| `generators/` | KiCad 解析、Vial 生成、Windows INF / REG 生成などの generator script |
| [`buildroot/`](buildroot/README.md) | Buildroot fast boot 実験用の external tree / rootfs overlay |
| `artifacts/` | 実行時に自動作成する一時生成物。directory全体をgit管理しない |

実行時に daemon が読む初期設定は [`../config/default/`](../config/default/README.md) に置きます。
generator を追加する場合は `build/generators/` に置き、出力先を `build/generated/` または `build/artifacts/`
のどちらにするかを明示してください。
