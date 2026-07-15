# KC_SH Ops

`KC_SH0`-`KC_SH10` の実機運用メモを置きます。
通常の editable script と、`logicd` が特別扱いする runtime action を分けて記録します。

## Documents

- [sh7-pty-terminal-mirror.md](sh7-pty-terminal-mirror.md): `KC_SH7` PTY terminal mirror の操作、Ctrl-C、timing、復旧手順。

## Placement

このディレクトリは `docs/ops/` 配下の補助ディレクトリです。
`docs/ops/README.md` の `文書一覧` は同階層の `.md` だけを列挙するため、
KC_SH 専用の詳細文書は `docs/ops/pty-terminal-mirror-smoke.md` などの上位 ops 文書から辿ります。

今後 `logicd` が特別扱いする `KC_SHn` runtime action を増やす場合は、このディレクトリに
個別 runbook を追加します。通常の editable script / metadata の説明は既存の ops 文書に残します。

## Scope

- `KC_SHn.sh` の編集 UI / script metadata は [script-safety-metadata.md](../script-safety-metadata.md) を参照します。
- `KC_SHn` の `hid_text` smoke は [../kc-sh-hid-text-cat-smoke.md](../kc-sh-hid-text-cat-smoke.md) を参照します。
- `KC_SH7` は通常 script ではなく、`logicd` の PTY mirror start handler が優先されます。
