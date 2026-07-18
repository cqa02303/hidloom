# Contributing to HIDloom

Thank you for improving HIDloom. The project supports a Raspberry Pi OS runtime and a parallel offline Buildroot
appliance. Changes should preserve the shared device profile and keymap data unless a migration is included.

## Before opening a change

- Use HIDloom for the software project name and `cqa02303v5` only for the hardware/device profile.
- Use only the documented `HIDLOOM_*` environment variables; do not add retired compatibility aliases.
- Do not add credentials, private addresses, personal paths, device logs, or private repository history.
- Keep Raspberry Pi OS as the normal development path; evaluate every runtime feature for Buildroot inclusion.
- Avoid changing USB VID/PID, Vial UID, persisted schema, package IDs, service IDs, or socket paths without a migration plan.

## Development checks

Run focused tests for the files changed, then the same bounded gate required for a public pull request:

```bash
for manifest in tools/*/Cargo.toml; do
  cargo fetch --locked --manifest-path "$manifest"
done
python3 script/public_pr_gate.py
git diff --check
```

The required `validate` check prioritizes source hygiene, privacy, licensing, public export integrity, and smoke tests
for the core HID, Vial, USB, JIS, and OLED paths. The `extended` check runs the canonical Python regression suite and
locked Rust tests after a change reaches `main`, on manual dispatch, and when a GitHub Release is published. Before
preparing a release, run the extended checks locally as well:

```bash
python3 script/test_validation_suite.py
for manifest in tools/*/Cargo.toml; do
  cargo test --locked --manifest-path "$manifest"
done
```

The individual public preparation entrypoints remain available for focused diagnosis:

```bash
python3 script/test_docs_links.py --public-export-manifest config/public-export.json
python3 script/test_hidloom_identity.py
python3 script/test_hidloom_runtime_environment.py
python3 script/test_local_environment_hygiene.py
python3 script/test_public_export.py
python3 script/test_public_community_health.py
python3 script/test_public_export_bundle.py
python3 script/test_source_syntax_hygiene.py
python3 script/test_development_residue_hygiene.py
python3 script/test_generated_binary_hygiene.py
python3 script/test_workspace_debris_hygiene.py
python3 script/test_third_party_inventory.py
git diff --check
```

Copy `.env.example` to an ignored `.env` only when local device access is needed. Keep the file mode at `0600`, never
commit its values, and run `python3 tools/local_environment_hygiene.py` before release preparation.
If the audit reports retired keys, run `make local-environment-migration-plan` first. Applying the key-only rewrite
requires `LOCAL_ENV_MIGRATION_CONFIRM=REWRITE-LOCAL-ENV-KEYS`; it uses atomic replace and intentionally creates no
secret-bearing backup.
Run `make workspace-debris-hygiene` before preparing an export. `make workspace-debris-clean` removes only disposable
cache, bytecode, and OS/editor temporary files; it preserves build outputs, virtual environments, backups, and operator state.

Rust and native daemon changes should also run their adjacent tests and cross-build on a development host. Do not run
slow compilation on a Raspberry Pi when the documented cross-build path is available.

Every executable Rust crate below `tools/*/` must commit its sibling `Cargo.lock`. Production, package, and cross-build
paths must use Cargo's `--locked` mode so a fresh public checkout cannot resolve a dependency graph that differs from the
reviewed source.

Every tracked `*.sh` entrypoint must retain its executable bit. Invoke Python modules explicitly with `python3` when
their Git mode is intentionally non-executable.

## Hardware changes

Document tests that require a real device separately from tests that can run in CI. A hardware report should include
the device profile, package or image version, commands used, pass/fail result, and rollback state. Never publish a
private device address or credential.

## Pull requests

- Keep each pull request focused and explain compatibility impact.
- Add or update tests for behavioral changes.
- Update user documentation, public export rules, and Buildroot preparation when applicable.
- State whether real-device testing is complete or still required.
- Do not include generated release images or local build artifacts in source commits.

## License

By submitting a contribution, you agree that it may be distributed under the repository's
[`GPL-3.0-or-later`](LICENSE) license. Only submit work that you have the right to contribute, and preserve applicable
third-party attribution and license notices. Contributors retain copyright in their contributions; HIDloom does not
require copyright assignment. See [`AUTHORS.md`](AUTHORS.md) for the public notice policy.
