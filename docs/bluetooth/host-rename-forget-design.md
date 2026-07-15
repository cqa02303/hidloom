# Bluetooth host rename / per-host forget design

Updated: 2026-06-10

This document fixes the implementation boundary for per-host Bluetooth display names and per-host forget.
The current System panel already has a read-only Bluetooth host overview, and `/api/bluetooth/forget` already removes all paired devices.
Per-host rename and forget add user-editable metadata and a destructive operation, so they must not be mixed with the read-only status path or the last-connected writer.

## Goals

- Keep host rename as local UI metadata first.
- Keep per-host forget as an explicit destructive operation with confirmation, CSRF, audit log, and refresh behavior.
- Reuse `/mnt/p3/bluetooth_hosts.json` without moving keymap, Vial, or host profile state into it.
- Use Bluetooth address as the stable key for the first slice.
- Keep BlueZ alias writes out of the first slice.

## Non-goals

- Do not write BlueZ `Alias` in the first slice.
- Do not implement reconnect priority, preferred host, or multi-host operation UI here.
- Do not change the existing all-device `/api/bluetooth/forget` behavior.
- Do not make HTTP status polling mutate metadata.
- Do not infer host OS or host profile from rename data.

## Metadata owner

Store user-visible host metadata in:

```text
/mnt/p3/bluetooth_hosts.json
```

Initial shape:

```json
{
  "version": 1,
  "hosts": {
    "AA:BB:CC:DD:EE:FF": {
      "display_name": "Desk iPhone",
      "last_seen_name": "iPhone",
      "last_connected_at": "2026-05-28T12:34:56+09:00",
      "last_connected_source": "btd_notify_ready"
    }
  }
}
```

Rules:

- `display_name` is the local rename field.
- `last_seen_name`, `last_connected_at`, and `last_connected_source` remain btd-owned observational metadata.
- HTTP rename writes only `display_name`.
- btd last-connected writer must not overwrite `display_name`.
- Atomic write is required: write temp file in the same directory, fsync when available, then rename.
- Missing or corrupt JSON falls back to read-only BlueZ names and does not block `/api/status`.

2026-06-10 groundwork:

- `update_bluetooth_host_observation_metadata()` writes only `last_seen_name`, `last_connected_at`, and `last_connected_source`.
- The writer preserves local `display_name` and supports `dry_run=true` fixture checks.
- `/api/status.bluetooth.devices[]` exposes `last_seen_name` from local metadata when present.
- The actual event source for reconnect / HID notify ready remains a real-device decision.

## Stable key

Use normalized Bluetooth address, uppercase colon-separated, as the first-slice key.

Reasoning:

- It is already present in `/api/status.bluetooth.devices[]`.
- It matches the last-connected metadata schema.
- It is easier to audit than a BlueZ object path.
- Stored metadata without a current BlueZ device can be shown as stale only in a later maintenance view.

Out of scope for the first slice:

- BlueZ object path as primary identity.
- Host-generated friendly-name identity.
- USB identity or host profile identity.

## Rename API

Candidate route:

```text
POST /api/bluetooth/hosts/{address}/rename
```

2026-06-09 first slice:

- `POST /api/bluetooth/hosts/{address}/rename` is implemented as local metadata only.
- It writes `/mnt/p3/bluetooth_hosts.json` atomically and updates only `hosts[address].display_name`.
- `/api/status.bluetooth.devices[]` merges `display_name` with `display_name_source=local_metadata`.
- The route uses the existing CSRF middleware, emits `bluetooth_host_rename` audit, and returns a status refresh hint.
- It does not change BlueZ `Alias`, pairing/bond state, host profile metadata, or last-connected writer fields.

Request:

```json
{
  "display_name": "Desk iPhone"
}
```

Validation:

- `address` must normalize to a Bluetooth MAC address.
- `display_name` length: 1-48 visible characters after trim.
- Reject control characters, newlines, path separators, and leading/trailing invisible whitespace.
- Empty string clears local rename only if the UI sends `clear=true`; otherwise reject.
- Duplicate display names are allowed but shown with address suffix in the UI.

Response:

```json
{
  "ok": true,
  "address": "AA:BB:CC:DD:EE:FF",
  "display_name": "Desk iPhone",
  "source": "local_metadata"
}
```

HTTP responsibilities:

- Validate request.
- Apply CSRF and normal auth guards.
- Write local metadata atomically.
- Audit `bluetooth_host_rename` with address and result, not raw unbounded display text.
- Return a status-refresh hint.

btd responsibilities:

- None for local rename in the first slice.
- Continue writing observational last-connected fields without touching `display_name`.

## Per-host forget API

Candidate route:

```text
POST /api/bluetooth/hosts/{address}/forget
```

Request:

```json
{
  "confirm_address": "AA:BB:CC:DD:EE:FF",
  "confirm_name": "Desk iPhone"
}
```

Required guard:

- CSRF token.
- Auth.
- Confirmed address must match the route address.
- Confirmation UI must show display name, last seen BlueZ name, raw address, paired/connected state, and a destructive label.
- Connected host must be allowed only after the same confirmation; the UI should warn that input may disconnect.

2026-06-10 first guard:

- `POST /api/bluetooth/hosts/{address}/forget` is wired as a non-destructive dry-run guard.
- The route validates `confirm_address`, emits `bluetooth_host_forget` audit, refreshes Bluetooth status, and returns `connected_warning`.
- The returned command plan contains exactly one address: `{"t":"BT","action":"BT_FORGET_HOST","address":"AA:BB:CC:DD:EE:FF"}`.
- Non-dry-run execution is rejected until real-device single-address removal has been verified.
- Metadata is preserved during dry-run.

Operation boundary:

- HTTP sends a single-host forget command to btd.
- btd uses BlueZ / bluetoothctl to remove only that address.
- HTTP does not shell out to `bluetoothctl remove` directly.
- On success, metadata for that address is either removed or marked `forgotten_at`; first slice removes it to avoid stale active display.
- On failure, metadata remains unchanged.

Audit:

- `bluetooth_host_forget`
- address
- result
- paired / connected snapshot if available
- error code category, not raw command output

## System panel UI

Host row display order:

1. connected hosts first
2. last connected descending when known
3. paired hosts by display name
4. raw address as final tie-breaker

Row fields:

- display label: local `display_name` if present, otherwise BlueZ `Name`, otherwise address.
- secondary label: address and `last_connected_at` if known.
- rename action enabled for paired hosts and metadata-only rows that still have an address.
- forget action enabled only for currently paired BlueZ devices.
- zero paired hosts shows disabled rename / forget actions and no destructive prompt.

The first UI slice should be conservative:

- rename can be inline or modal.
- per-host forget must be modal with explicit address confirmation.
- after operation, immediately refresh `/api/status`.
- show failure inline on the host row.

## Interaction with existing features

| Feature | Boundary |
| --- | --- |
| Bluetooth host overview | remains read-only except explicit rename / forget routes |
| all-device forget | keeps existing route and behavior |
| last connected writer | writes observational fields only, never `display_name` |
| host profile | can read active address later, but does not own rename data |
| multi-host UI | uses the same address identity later, but priority policy is separate |
| BlueZ Alias | not written in first slice |

## Static tests

Add static tests before implementation for:

- design doc has local metadata / BlueZ Alias non-goal / Bluetooth address identity.
- rename validation rejects invalid address, control characters, empty name without clear, and overlong name.
- metadata write preserves `last_connected_at` and only changes `display_name`.
- per-host forget helper sends one address, not all-device forget.
- CSRF / audit route names are wired.
- UI guard includes destructive confirmation and raw address.
- status refresh hint is returned after rename / forget.
- corrupt metadata fallback keeps `/api/status` usable.

## Real-device checks

Implementation is not blocked by real hardware for the static pieces above.
Before enabling per-host forget in normal UI, verify on a paired host:

1. rename does not change BlueZ `Alias`.
2. per-host forget removes only the selected address.
3. connected host forget disconnects and clears active display safely.
4. failed BlueZ remove leaves metadata unchanged.
5. all-device forget still works.
