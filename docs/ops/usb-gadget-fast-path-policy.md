# USB Gadget Fast Path Policy

## Decision

Boot-critical, fixed USB gadget setup should use a small native helper
written in C or Rust. The existing `setup_usb_gadget.sh` remains the
development/fallback path for flexible profiles, diagnostics, and unusual
host experiments.

The first native helper target is the normal CQA02303v5 composite HID gadget:

- `/dev/hidg0`: keyboard + mouse + consumer multi-report
- `/dev/hidg1`: Raw HID / Vial
- optional `/dev/hidg2`: US sub keyboard when the default config enables it

The helper should configure configfs and bind the UDC with minimal external
processes. It should not absorb Python-control-plane behavior.

## Rationale

The USB gadget setup path is boot-critical and mostly fixed in production.
The current shell script is intentionally flexible, but boot pays for shell
startup, config parsing branches, many external command invocations, and
repeated text redirection. A native helper can make the common path faster and
more deterministic while preserving the shell script for cases that need
flexibility.

This is a better fit than splitting `logicd`'s HID state machine first:

- USB gadget setup directly affects host HID enumeration and `/dev/hidg*`
  readiness.
- The gadget descriptor tree is relatively fixed and maps cleanly to a native
  helper.
- The soft parts of the product should remain in Python/shell where they are
  easier to change.

## Keep Out Of The Native Helper

Do not move these soft or frequently changing responsibilities into the native
USB setup helper:

- keymap JSON interpretation
- action parsing, regular expressions, macros, text send, IME, PTY mirror
- HTTP/Vial/BT/touch/control-plane logic
- profile exploration and one-off host identity experiments
- broad JSON validation or documentation-like config generation

The helper may read a small set of environment variables needed for the boot
fast path, but complex selection belongs in the existing shell fallback.

## Rollout

Use an opt-in backend first:

```text
HIDLOOM_USB_GADGET_SETUP_BACKEND=native
```

The systemd unit should default to the proven shell path until the native
helper is measured on real hardware. After the helper consistently matches the
descriptor/function layout and improves readiness, the default can switch to
native with shell fallback retained.

## Verification

Each rollout step must include:

- source-level descriptor/function parity checks
- local build/checks
- real-device reboot timing from `journalctl -b -o short-monotonic`
- host-facing readiness checks for `/dev/hidg0`, `/dev/hidg1`, and optional
  `/dev/hidg2`
- documentation updates with measured effect
