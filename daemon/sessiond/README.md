# sessiond

`sessiond` は、PTY terminal mirror M0 のための local session daemon です。
M0 では user 権限 shell を PTY 上で起動し、`logicd` からの入力 routing と
PTY output mirror の接続点になることを目指します。

現在の実装範囲:

- JSON Lines socket protocol helper
- PTY key input helper
- row-level ANSI diff helper
- local PTY process wrapper
- minimal sessiond socket server
- `tools/sessiond_ctl.py` による start / status / stop
- `logicd` client helper
- `KC_SH7` による logicd runtime start
- PTY output から WSL command wrapper text plan への変換
- `source=pty_terminal_mirror` loop guard 付き synthetic HID tap dispatch

まだ未実装:

- OLED debug status line
- systemd service
- 実機 Windows Terminal mirror smoke

## Manual M0 socket smoke

別 terminal で `sessiond` を起動します。

```bash
PYTHONPATH=daemon:. python3 -m sessiond.sessiond --socket /tmp/sessiond.sock
```

別 terminal から start / status / stop を確認します。

```bash
python3 tools/sessiond_ctl.py --socket /tmp/sessiond.sock start --shell /bin/sh --columns 120 --rows 35
python3 tools/sessiond_ctl.py --socket /tmp/sessiond.sock status
python3 tools/sessiond_ctl.py --socket /tmp/sessiond.sock stop --reason manual_smoke
```

`KC_SH7.sh` は同じ `tools/sessiond_ctl.py start` を呼びます。
通常 key path では logicd の `KC_SH7` start handler が優先されます。
M0 の実機 smoke では、`sessiond` が起動済みで、Windows Terminal が focus 済みであることを operator が確認します。

現在の `KC_SH7` 実機運用、text editor profile、timing、`Ctrl-C` output flush、
`usbd` broker 復旧手順は [docs/ops/kc-sh/sh7-pty-terminal-mirror.md](../../docs/ops/kc-sh/sh7-pty-terminal-mirror.md)
にまとめます。

## Tests

```bash
python3 script/test_pty_mirror_remote_suite.py
```

個別に見る場合:

```bash
python3 script/test_sessiond_protocol.py
python3 script/test_sessiond_pty_mirror.py
python3 script/test_sessiond_pty_session.py
python3 script/test_sessiond_socket.py
python3 script/test_sessiond_ctl.py
python3 script/test_logicd_sessiond_client.py
python3 script/test_logicd_pty_mirror_runtime.py
python3 script/test_logicd_sessiond_pty_mirror_integration.py
```
