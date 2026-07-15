# Repository Hygiene Policy

更新日: 2026-07-14

## 目的

private主開発repositoryとclean public exportの双方で、workspaceの一時状態、build生成物、
実機操作結果、重複した旧資料をtracked sourceへ混入させず、Linuxで作成したpathを
Windows/macOSのcase-insensitive filesystemでも安全にcheckoutできる状態に保つ。
text contentと実行modeもGit clone前後で変質しないcanonical形式へ固定する。

## 追跡境界

- 判定対象はGit indexのtracked fileとする。
- git metadataを持たないclean public exportでは`PUBLIC_EXPORT_MANIFEST.json`をinventoryとして使う。
- `build/artifacts/`にあるlocal Buildroot outputやrelease candidateは追跡せず、必要な配布物はGitHub Releaseへ置く。
- 空directory維持用の`.gitkeep`は追跡せず、必要なdirectoryはconsumerが実行時に作成する。
- `docs/archive/`は整理済みのprivate履歴資料として保持するが、public exportからは除外する。
- `case/*.f3d`と`kicad/**/*.kicad_pcb`は大容量でも編集可能なhardware sourceとして明示許可する。
- `.f3d`、`.ico`、`.png`だけをbinary形式として明示し、それ以外はUTF-8 textとして検査する。
- 空fileはPython package markerの`daemon/i2cd/__init__.py`と`daemon/logicd/__init__.py`だけを許可する。

## 自動ゲート

`config/repository-hygiene.json`をsingle source of truthとし、
`tools/repository_hygiene.py`が次を拒否する。

- cache、build、package、temporary directory配下のtracked file
- `.gitkeep` placeholder
- backup、log、compiled object、package、disk image、release archive
- `codex_tasks/{inbox,running,done,failed}/`の`.sample`以外の実行状態
- 1 MiBを超える未承認file
- 1 byte以上で内容が完全一致し、用途とpath集合を明示許可していない重複file
- 64 MiBを超えるtracked tree
- repository外を指すsymlink
- NFCでないUnicode path、Windows禁止文字・予約device名、末尾dot/space
- NFC/casefold後に同じdirectory/fileとなるpath衝突
- 180 UTF-16 unitを超えるrelative path、255 unitを超えるcomponent
- UTF-8以外のtext、BOM、CR/CRLF、final LF欠落、行末space/tab
- package marker例外以外の空file
- `#!` shebangを持たないtracked executable

`.gitattributes`は全textを`text=auto eol=lf`とし、明示binary 3形式だけを`binary`に固定する。

exact duplicateの例外はglobではなく完全なpath集合と理由を記録する。独立配布するBuildroot packageの
license/hash、self-containedなboard profile、KiCad projectだけを許可し、第三のcopy追加、path欠落、
内容の分岐で例外がstaleになった状態を拒否する。空package markerはduplicate検査ではなく専用のempty file
例外で扱う。

検査とfixture regressionは次で実行する。

```bash
make repository-hygiene
```

private `Repository hygiene` workflowは全push / pull requestで軽量gateを実行する。
`public-export-check`、private側public export workflow、public CI、public sync workflowも
このgateを通らないtreeを公開経路へ流さない。

## Source syntax gate

content形式がcanonicalでも構文が壊れたsourceを公開しないため、`tools/source_syntax_hygiene.py`は
Git indexまたはpublic manifestの全pathを棚卸しし、Python、JSON、TOML、YAML、shell、
JavaScript、SVGを各parserで検査する。PyYAML、Node、`sh` / `bash`が欠ける環境は検査省略ではなく
failureとする。PowerShellとplaceholderを含むsystemd templateはこのgateの対象外とし、専用testで扱う。

```bash
make source-syntax-hygiene
```

7形式それぞれのmalformed fixture、Git metadataのないmanifest fallback、bytecode cacheを残さないことを
回帰testで固定し、canonical suite、public export、public CI、public syncの全経路へ接続する。

## Development residue gate

構文上は正しくても開発途中の状態や機械置換の残骸を公開しないため、
`tools/development_residue_hygiene.py`はGit indexまたはpublic manifestの全textを走査する。

- unresolved merge conflict marker
- Pythonの同一`or` operand、literal dict key、環境名collection、production codeの隣接同一文
- Pythonの`breakpoint`、`pdb` / `ipdb` trace hook
- shellの同一変数への自己fallback、同一行の重複環境代入、xtrace
- JavaScriptの`console.log` / `console.debug` / `console.trace`と`debugger`
- Rustの`dbg!` / `todo!` / `unimplemented!`

```bash
make development-residue-hygiene
```

fixtureはGit indexとGit metadataのないmanifest inventoryの双方を検査し、公開readiness、
canonical suite、private export/sync workflow、standalone public CIへ同じgateを接続する。
一般的なTODO文言や意図した反復dataは一律禁止せず、実行残渣として判定できる構造だけを拒否する。

## Ignored workspace debris gate

Git indexがcleanでも、過去の直接実行がsource directoryへ`__pycache__`やtool cacheを残すことがある。
`tools/workspace_debris_hygiene.py`はrepository全体を無制限に削除せず、source領域の次の状態だけを
disposableとして検査する。

- Python bytecodeと`__pycache__`
- pytest、mypy、ruff、tox、nox、Hypothesis、notebook cache
- coverage、OS metadata、editor swap/temporary file

`--clean`はdisposableな通常file/directoryだけを削除する。Git tracked content、symlink、backup、log、
nested environment fileはreview findingとして残し、内容を読まない。root `.env`、credential local file、
`build/`、`bin/`、Rust `target/`、native `.build/`、virtual environment、`demo/assets/`、Windows package、
Codex mailboxはoperator/build stateとして走査から除外する。ignored inventoryを集計するときは、Gitの
quotePath表示を実pathと誤認しないようNUL区切りを使う。

```bash
make workspace-debris-hygiene
make workspace-debris-clean
```

fixtureはtracked debris、symlink、backup、nested environment fileを自動削除しないこと、外部symlinkを
辿らないこと、秘密値を出力しないこと、preserved rootをbyte一致で維持することを固定する。

## 2026-07-14 baseline cleanup

- exact duplicateを含む`kicad/OLD/` 15 filesを削除した。
- `codex_tasks/done/`の実機preflight結果2 filesを削除し、sample schemaだけを残した。
- 参照されない`config/default/config.json.bak2`を削除した。
- `kicad/OLD/**`はsource treeから消えたため、public exportの個別除外も削除した。
- `build/artifacts/`、`demo/assets/`、`codex_tasks/{inbox,running,done,failed}/`の6個の`.gitkeep`を削除した。
  build/demo/mailbox helperが必要なdirectoryを作り、Gitはruntime output全体をignoreする。
- tracked text 23 filesの末尾空白またはfinal LF欠落を正規化し、KiCad generatorも同じcanonical出力へ修正した。
- source領域に残っていたPython/pytest cache 10 directoryを限定cleanupし、Buildroot/Rust outputとvenvを保持した。
- project名のKiCad CSV BOM / Fabrication Toolkit JSON 4件と、親READMEで代替できるproject内README 2件を削除した。
  2個のnative helper用`.gitignore`はrootの`tools/*/.build/`へ統合し、局所copyを削除した。
- non-empty exact duplicate検査を1 MiB以上から1 byte以上へ拡張し、独立consumerが必要とする10組だけを
  exact path-setで許可した。

## 失敗時の扱い

- build/image/packageは`build/artifacts/`へ移し、source commitへ追加しない。
- 実機のtask/resultはlocal mailboxまたは運用証跡へ保存し、sample化・sanitizeしない限り追跡しない。
- legitimate sourceがsize gateへ達した場合は、用途と再配布条件を監査してからallowlistを変更する。
- 重複資料はcanonical sourceを一つ決め、別名copyを追加しない。独立consumerが同一payloadを必要とする場合だけ、
  完全なpath集合と理由を追加し、第三のcopyをglobで許可しない。
- caseだけが異なるpathは片方へ統合し、Windowsでcheckout不能な名前をallowlistで回避しない。
- long pathは意味を失わない短いdirectory/file名へ変更し、利用者へ`core.longpaths`を必須にしない。
- text例外をallowlistへ積まずUTF-8/LFへ変換し、Markdown hard breakはlistや段落として明示する。
- 新しいbinary形式が必要な場合は再配布条件と用途を確認し、configと`.gitattributes`を同じ変更で更新する。
