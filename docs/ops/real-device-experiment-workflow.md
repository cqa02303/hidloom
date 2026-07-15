# Real-device experiment workflow

この手順は、実機で一時的な修正を試したあと、checkout を clean に戻し、
正式な変更だけを repository 経由で反映するための標準運用です。

## Principle

実験用の一時修正は成果物ではなく観測手段として扱います。
実験結果だけを記録し、正式な修正は local repository で実装、test、commit、push します。
実機は clean checkout のまま `git pull --ff-only` で最新化します。

この方針により、実機 checkout が常に main に追従する場所になり、
pull 前の preserve / cleanup 判断が大きく減ります。

## Standard flow

1. 実験前に現在地を確認する。

   ```bash
   cd /home/USERNAME/hidloom
   git status --short --branch
   python3 dev/mcp/keyboard/server.py --tool get_development_snapshot --max-files 40
   ```

2. 実験で checkout を触る場合は、任意で保険の stash を作る。

   ```bash
   git stash push -u -m "experiment before <topic> <date>"
   ```

   これは正式変更の保存場所ではなく、誤って必要な観測状態を失った時の保険です。

3. 実機上で一時修正して、挙動を見る。

   ここでの変更は原則として commit しません。
   必要な観測結果、log、スクリーンショット、差分の意味だけを記録します。

4. 実験が終わったら、実機 checkout を元の clean state に戻す。

   破壊的操作なので、実行前に `git status --short --branch` と観測メモの有無を確認します。

   ```bash
   git reset --hard HEAD
   git clean -fd
   ```

   stash を使った場合、必要なら中身だけ確認します。

   ```bash
   git stash list
   git stash show --stat --name-status 'stash@{0}'
   ```

5. 観測結果をもとに、desktop/local repository で正式実装する。

   正式実装は通常の source edit、test、docs 更新として扱います。

6. local repository で commit / push する。

   ```bash
   git status --short --branch
   python3 script/test_mcp_keyboard_server.py
   git diff --check
   git commit -m "<message>"
   git push
   ```

7. 実機は clean checkout のまま pull する。

   ```bash
   cd /home/USERNAME/hidloom
   git pull --ff-only
   python3 dev/mcp/keyboard/server.py --tool get_development_snapshot --max-files 40
   ```

## When to preserve instead

一時修正を戻さず preserve するのは例外です。
次の条件を満たす場合だけ、stash や backup を残して別途判断します。

- 実験中にしか再現できない runtime state があり、結果記録だけでは足りない。
- 実機固有の設定ファイルや認証情報に近いものを含み、local repository へ直接持ち込めない。
- reset / clean すると物理再操作が大きく増える。

それ以外は、stash を正式な変更管理に使わず、clean checkout に戻します。

## MCP helpers

関連する read-only MCP tools:

- `get_development_snapshot`: 実験前後の全体状態を見る。
- `get_pull_readiness_summary`: pull 前の blocker を確認する。
- `get_checkout_cleanup_candidates`: dirty checkout が残った時に分類する。
- `get_manual_cleanup_verification_plan`: cleanup / pull 前の最終 gate を見る。
- `get_temporary_change_restore_plan_summary`: stash の確認と手動 restore command 例を見る。
- `get_real_device_experiment_workflow_summary`: 実験変更を記録して戻すべきか、clean pull へ進めるかをまとめて見る。

MCP tools は reset / clean / stash apply / stash drop / pull を実行しません。
状態変更は operator が shell で明示的に実行します。

## Do not do

- 実験差分をそのまま実機 checkout に残したまま、次の `git pull` へ進まない。
- stash を正式な実装差分の置き場にしない。
- 実機でたまたま動いた差分を、確認なしに local repository へ丸ごと移植しない。
- read-only MCP server に write-capable cleanup / restore tool を混ぜない。
