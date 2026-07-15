# Ops Docs

作業手順、実機確認、テスト棚卸し、性能測定計画など運用文書を置きます。

まず見る文書:

- [real-device-experiment-workflow.md](real-device-experiment-workflow.md): 実機一時修正を戻し、正式変更だけを repository 経由で反映する標準手順
- [release-packaging-runbook.md](release-packaging-runbook.md): release bundle / Debian package の build、deploy、verify、rollback 手順
- [public-source-rebuild-runbook.md](public-source-rebuild-runbook.md): public sourceからsplit Debian packageとBuildroot M6 imageを再生成する手順
- [public-documentation-boundary.md](public-documentation-boundary.md): public sourceへ同期する現行文書とprivate運用資料の境界
- [hidloom-license-review-runbook.md](hidloom-license-review-runbook.md): Debian/Python evidenceとBuildroot legal-info収集手順
- [package-profile-split-plan.md](package-profile-split-plan.md): core package と device profile package の分離計画
- [buildroot-fast-boot-experiment.md](buildroot-fast-boot-experiment.md): Buildroot / fast boot を別 image で試すための段階計画と測定 marker
- [failure-patterns.md](failure-patterns.md): 再発しやすい実機失敗の検出、復旧、回帰確認メモ
- [usb-gadget-fast-path-policy.md](usb-gadget-fast-path-policy.md): native USB gadget fast path と shell fallback の使い分け
- [test-script-inventory.md](test-script-inventory.md): test script inventory
- [performance-tuning-plan.md](performance-tuning-plan.md): performance tuning plan
- [script-safety-metadata.md](script-safety-metadata.md): script safety metadata

完了済み roadmap、handoff、単発 smoke の記録は下の `文書一覧` から必要時だけ辿ります。

補助ディレクトリ:

- [kc-sh/README.md](kc-sh/README.md): `KC_SH0`-`KC_SH10`の専用runbookとruntime actionの入口

文書一覧:

- [codex-ssh-stdio-mcp-profile.md](codex-ssh-stdio-mcp-profile.md)
- [release-packaging-runbook.md](release-packaging-runbook.md)
- [public-documentation-boundary.md](public-documentation-boundary.md)
- [public-source-rebuild-runbook.md](public-source-rebuild-runbook.md)
- [hidloom-license-review-runbook.md](hidloom-license-review-runbook.md)
- [hidloom-migration-contract.md](hidloom-migration-contract.md)
- [hidloom-name-inventory.md](hidloom-name-inventory.md)
- [package-profile-split-plan.md](package-profile-split-plan.md)
- [keyboard-mcp-server.md](keyboard-mcp-server.md)
- [kc-sh-hid-text-cat-smoke.md](kc-sh-hid-text-cat-smoke.md)
- [performance-tuning-plan.md](performance-tuning-plan.md)
- [pty-terminal-mirror-smoke.md](pty-terminal-mirror-smoke.md)
- [real-device-experiment-workflow.md](real-device-experiment-workflow.md)
- [repository-hygiene-policy.md](repository-hygiene-policy.md)
- [hidloom-hidd-deep-test-plan.md](hidloom-hidd-deep-test-plan.md)
- [buildroot-fast-boot-experiment.md](buildroot-fast-boot-experiment.md)
- [failure-patterns.md](failure-patterns.md)
- [usb-gadget-fast-path-policy.md](usb-gadget-fast-path-policy.md)
- [script-safety-metadata.md](script-safety-metadata.md)
- [test-script-inventory.md](test-script-inventory.md)
- [windows-ime-custom-hid-real-device-runbook.md](windows-ime-custom-hid-real-device-runbook.md)
