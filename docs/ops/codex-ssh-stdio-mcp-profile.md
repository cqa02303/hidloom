# Codex SSH stdio MCP profile

このメモは、`<keyboard-host>` 上の Keyboard MCP server を Codex から SSH 経由の
stdio server として起動するための設定例です。

目的は、実機に HTTP MCP endpoint を公開せず、SSH login と remote user 権限だけを認証境界にして
read-only 診断を使えるようにすることです。

関連:

- MCP 機能一覧: [keyboard-mcp-server.md](keyboard-mcp-server.md)

## 前提

- SSH alias `<keyboard-host>` が local SSH config または local DNS で解決できる。
- remote checkout は `/home/USERNAME/hidloom`。
- remote user は `dev/mcp/keyboard/server.py --stdio` を実行できる。
- 実機側に Codex CLI を入れる必要はない。Codex CLI は desktop / local 側だけでよい。
- SSH key、IP address、token、password、`.env` の値は docs に書かない。

## 事前確認

Codex MCP に登録する前に、local shell から SSH 越しに server が起動できるか確認します。
`--tool` で read-only tool を 1 回実行できれば、stdio 起動の前提は満たしています。

```bash
ssh -o BatchMode=yes -o ConnectTimeout=5 <keyboard-host> \
  'cd /home/USERNAME/hidloom && python3 dev/mcp/keyboard/server.py --tool get_status'
```

実機側の runtime readiness も見たい場合:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=5 <keyboard-host> \
  'cd /home/USERNAME/hidloom && python3 dev/mcp/keyboard/server.py --tool get_development_snapshot --include-http-status --max-files 4 --max-changes 2'
```

## Profile 設定例

常時有効にすると Codex 起動時に毎回 SSH 接続を試すため、まずは profile file に分けるのを推奨します。
例では `~/.codex/keyboard-remote.config.toml` に置き、必要な時だけ
`codex --profile keyboard-remote` で使います。

```toml
[mcp_servers.keyboard_remote_01]
command = "ssh"
args = [
  "-o", "BatchMode=yes",
  "-o", "ConnectTimeout=5",
  "<keyboard-host>",
  "cd /home/USERNAME/hidloom && exec python3 dev/mcp/keyboard/server.py --stdio",
]
startup_timeout_sec = 15
tool_timeout_sec = 60
enabled = true
```

global `~/.codex/config.toml` に直接入れる場合も同じ形で動きますが、remote 接続が不要な通常作業では
profile 分離のほうが失敗時の noise が少なくなります。

## 確認手順

1. profile を指定して Codex CLI を起動する。
2. TUI では `/mcp` で `keyboard_remote_01` が見えることを確認する。
3. まず read-only の軽い tool だけを呼ぶ。

最初に見る tool:

- `get_status`
- `get_codex_mcp_status`
- `get_development_snapshot`
- `get_runtime_issue_summary`

## 採用しないこと

- 実機で MCP HTTP listener を開かない。
- SSH command に秘密情報を埋め込まない。
- `env` / `env_vars` で bearer token や password を渡さない。
- write-capable tool をこの remote server に追加しない。
- service restart、key send、keymap write、git pull / commit / push を MCP tool から実行しない。

## Troubleshooting

| 症状 | 確認 |
| --- | --- |
| Codex 起動時に MCP server が timeout する | `ssh -o BatchMode=yes -o ConnectTimeout=5 <keyboard-host> true` が通るか確認する |
| `<keyboard-host>` alias が名前解決できない | local `.env` の `HIDLOOM_DEVICE_01_SSH_TARGET` / `HIDLOOM_SSH_TARGET` や SSH config の numeric target で `get_real_device_access_summary` を先に実行する。docs には実 IP を書かず、alias は convenience name として扱う |
| server 起動直後に終了する | remote checkout path と `python3 dev/mcp/keyboard/server.py --tool get_status` を確認する |
| 実機 runtime JSON が読めない | `check_runtime_access` で `/mnt/p3/keymap.json` の権限を見る |
| dirty checkout が気になる | `get_repo_dirty_summary` と `get_selective_sync_plan` を先に見る |

この profile は、desktop-driven SSH を維持しながら Codex MCP の操作面だけを短くするためのものです。
device-side Codex CLI 導入判断は別項目として扱います。
