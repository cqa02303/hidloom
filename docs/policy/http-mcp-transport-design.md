# HTTP MCP transport design

Date: 2026-06-13

このメモは、Keyboard MCP server を将来 HTTP transport で公開する必要が出た場合の設計境界を固定します。
現時点では HTTP MCP endpoint は作りません。

関連:

- MCP server: [../ops/keyboard-mcp-server.md](../ops/keyboard-mcp-server.md)
- SSH stdio profile: [../ops/codex-ssh-stdio-mcp-profile.md](../ops/codex-ssh-stdio-mcp-profile.md)

## Decision

現時点の採用 transport は `stdio` だけです。

HTTP MCP transport は、複数 client から同じ MCP server を共有する必要が出るまで実装しません。
remote 実機で使う場合も、まずは SSH stdio を使います。

## Why HTTP is deferred

Keyboard MCP は read-only でも次の情報を返します。

- checkout 状態
- runtime path 権限
- service / socket / HID state
- HTTP UI/API health
- Bluetooth host metadata summary
- journal excerpt

これらは LAN に出す診断面としては広いので、stdio / SSH の OS user 境界で十分な間は HTTP 化しません。

## Required design before implementation

HTTP MCP を作る前に、少なくとも以下を文書化します。

| Area | Required decision |
| --- | --- |
| Transport | Streamable HTTP only. No ad-hoc JSON endpoint. |
| Bind address | Start with loopback only. LAN bind requires a separate approval note. |
| TLS | Required outside loopback. |
| Auth | Bearer token for local/private first slice, OAuth only if multi-user remote access is needed. |
| Token storage | Token values stay out of repo docs and `.env` examples. Use env var names only. |
| Scopes | Split read-only diagnostics from any future write-capable surface. |
| Tool allowlist | Expose only explicitly listed read-only tools. |
| Logs | Do not log bearer tokens, Authorization headers, passwords, Bluetooth addresses, or full runtime JSON. |
| Rate limit | Add bounded request size and tool timeout. |
| Disable path | A documented config flag or service disable path must exist before enabling. |

## Initial tool allowlist

If a loopback-only HTTP MCP first slice is ever implemented, start with these tools:

- `get_status`
- `get_usb_split_status`
- `get_codex_mcp_status`
- `get_http_status_summary`
- `get_interface_snapshot`
- `get_runtime_issue_summary`

Do not expose by default:

- `collect_journal_excerpt`
- `get_repo_dirty_summary`
- `get_development_snapshot`
- any future write-capable tool

Those tools can reveal broader local state and should require a narrower reason before HTTP exposure.

## Auth sketch

Bearer-token first slice:

```toml
[mcp_servers.keyboard_http_loopback]
url = "http://127.0.0.1:PORT/mcp"
bearer_token_env_var = "KEYBOARD_MCP_TOKEN"
enabled_tools = [
  "get_status",
  "get_usb_split_status",
  "get_codex_mcp_status",
  "get_http_status_summary",
  "get_interface_snapshot",
  "get_runtime_issue_summary",
]
```

Token value rules:

- `KEYBOARD_MCP_TOKEN` value is local-only.
- Docs may mention the env var name, not the token.
- Logs must redact `Authorization` and configured token env names.

OAuth is deferred until there is a real multi-user client. If OAuth is added, define resource identifier,
audience, scopes, callback URL, token lifetime, and revocation path before implementation.

## Write-capable tools

Write-capable operations must not be added to this HTTP surface. If future work needs key sending,
keymap writes, service restart, pairing, forget, output switching, or git mutation, create a separate
server or profile with:

- explicit dry-run output,
- confirmation behavior,
- rollback note,
- narrower allowlist,
- separate auth scope.

## Current next action

Keep using stdio and SSH stdio. Revisit HTTP MCP only after a concrete client requires shared network access.
