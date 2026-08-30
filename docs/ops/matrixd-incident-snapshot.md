# matrixd Incident Snapshot Runbook

通常使用中のキー重複、固着、欠落を後から調べるための採取手順です。`matrixd`は通常時、
`/run/hidloom/matrixd-trace.jsonl`と`matrixd-trace.1.jsonl`だけへ構造traceを循環保存します。
各fileは4 MiB、合計は最大8 MiBで、root所有・`0600`です。保存先はRAMなのでmicroSDへの
常時writeはなく、再起動すると履歴は消えます。

traceはrealtime/monotonic timestamp、scan sequence、matrix row/col、raw/debounce遷移、
確定P/R、primary/tap送信結果だけを含みます。mapped keycode、文字列、HID payload、script内容、
credentialは記録しません。writer I/Oやqueue overflowはfail-openで、入力経路を停止せず
`/run/hidloom/matrixd-status.json`の`diagnostic_trace` counterへ残します。

## 連絡を受けた直後

deviceを再起動せず、device上に新しいsnapshot fileを作らないSSH read-only採取を先に行います。
`DEVICE`とlocal保存先は毎回実値・fresh pathへ置き換えます。

```bash
stamp=$(date -u +%Y%m%dT%H%M%SZ)
ssh pi@DEVICE 'sudo -n python3 /usr/lib/hidloom/tools/matrixd_diagnostics_snapshot.py --duration 30 --since "30 minutes ago" --output -' > "matrixd-incident-${stamp}.md"
chmod 600 "matrixd-incident-${stamp}.md"
```

remote側ではroot-only trace/status/journalを読み、既存socketへread-only接続して30秒captureします。
reportはSSH標準出力だけへ流れ、保存はlocal側のfresh fileです。同じpathへ再送・上書きしません。
採取後、reportの次を確認します。

- `package identity`、`boot ID`、`device_profile.json`が対象deviceと一致する。
- rotated/current traceの`invalid_lines=0`で、時系列がscan/monotonic順になっている。
- `diagnostic_trace.queue_dropped` / `io_errors`、`send_failures`、dispatchの`failed`有無。
- matrixd、logicd-core、hidd、outputd status、failed units、関連journalに再起動や異常がない。
- 症状時刻付近の同一row/colでraw反転、確定P/R、dispatch結果がどう並ぶか。

`KC_SH8`を押せる場合は同じprehistoryを取り込んだ後、既存どおり30秒captureし、
`/mnt/p3/matrixd-diagnostics/`へone-shotで`0600`保存します。自動永続snapshotは、誤検知ごとの
microSD writeとscan時負荷を避けるため行いません。

## 合否と次の切り分け

- trace上で余分な確定P/Rがある: matrix raw/debounce側を時刻・row/colで切り分ける。
- 確定P/Rは1組だがprimary送信が失敗/再試行: socket owner、service restart、counter、journalを調べる。
- matrix traceは正常だが最終出力だけ重複/欠落: logicd-core、hidd、outputd側のstatus/journalへ進む。
- `queue_dropped`または`io_errors`が増えている: trace欠落を明記し、その区間を完全証拠として扱わない。

採取自体はservice restart、profile apply、package変更、output target変更を行いません。実機更新や
rollbackは別途承認されたpackage/profile手順に従います。
