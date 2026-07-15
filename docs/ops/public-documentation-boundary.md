# Public Documentation Boundary

HIDloomのpublic repositoryには、利用、開発、再現build、architecture、hardware、protocol、
package、release、license、securityに必要な現行文書だけを同期します。

## 公開する文書

- install、configuration、runtime、daemon、IPC、Vial、HID、hardwareの現行仕様
- Raspberry Pi OS packageとBuildroot imageの再現build / verification手順
- contributor向けtest inventory、repository hygiene、failure recovery
- license、third-party inventory、asset provenance、security / support boundary
- 実装判断に必要なarchitecture、design、research資料

## private workspaceだけに置く文書

- 日々の`CURRENT_STATUS`、`TODO`、`WISHLIST`、docs整理進捗
- private実機の個別結果、内部archive、日付付きdesign review
- public repository作成前のmigration workset、sync credential / deploy key運用
- private build hostやagent task mailboxなど、内部開発環境固有の判断と手順
- operator向けworkflow、次回作業入口、host別handoff、完了済みの日付付きprogress / status / audit

公開対象のMarkdown filenameには`*-handoff.md`、`*-next-start.md`、
`*-(progress|status|audit)-YYYY-MM-DD.md`を許可しません。恒久的な仕様や再現手順は内容に合う
timelessな名前へ整理し、一時的な引継ぎや証跡はprivate workspaceへ残します。
`workflow-runbook.md`と完了済みrepository layout inventoryも内部運用資料として扱います。

除外対象は`config/public-export.json.exclude_globs`を正とします。schema v2ではGit indexの全pathが
public source、同fieldで明示したprivate-only、既定generated outputのいずれかに分類され、どれにも
一致しないpathはexport前に停止します。公開文書から除外対象への相対linkは、
labelを保持しない汎用の`private workspace reference`表記へ変換し、`PUBLIC_DOCUMENTATION_AUDIT.json`へ記録します。
private linkだけで構成されるlist/table行はpublic indexから削除します。
JSONと`PUBLIC_DOCUMENTATION_AUDIT.md`の両方に変換・削除の明細を残します。
明細は公開source側のpathとlineだけを記録し、除外先のprivate path名や原文は再公開しません。
除外対象ではない未知のtargetや、公開対象なのに欠落したtargetはblockerです。
`private_documentation_path` scannerと`script/test_public_documentation_audit.py`は、同型文書が
公開対象へ再混入した場合にexportを失敗させます。

公開root `README.md`からMarkdown linkを辿り、全`docs/**/*.md`へ到達できることも同じ監査で確認します。
directory linkは配下`README.md`へ解決し、code fence内の例示linkはnavigationとして扱いません。
`PUBLIC_DOCUMENTATION_AUDIT.json`は実treeから再計算した文書数、到達数、孤立pathを記録し、
release readinessはmanifest hashだけでなくこのsemantic inventoryも再検証します。

## 確認

```bash
python3 script/test_public_documentation_audit.py
python3 tools/public_export.py /tmp/hidloom-public-export --draft --force
python3 /tmp/hidloom-public-export/script/test_docs_links.py
python3 /tmp/hidloom-public-export/tools/public_release_readiness.py \
  /tmp/hidloom-public-export --allow-pending-pid
```

この公開可能確認はclean HEADから実行します。編集中に`--draft --allow-dirty-source`で生成できるtreeは
文書変換の局所確認専用で、release readinessには合格しません。

`PUBLIC_DOCUMENTATION_AUDIT.json.summary.broken_links`と`orphaned_documents`がともに`0`でなければ公開しません。
