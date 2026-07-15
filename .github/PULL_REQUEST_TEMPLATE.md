# Pull Request

## Summary

Describe the user-visible problem and the focused change that solves it.

## Compatibility

- Raspberry Pi OS impact:
- Buildroot inclusion decision and dependency/startup-size impact:
- Keymap, Vial, USB identity, package/service/socket, or persisted-schema impact:
- Rollback path:

## Validation

List the exact commands, target environment, and pass/fail results.

- [ ] I ran focused tests for the changed behavior.
- [ ] I ran the applicable public export and documentation checks.
- [ ] I recorded generated-artifact or cross-build verification when applicable.

## Hardware Validation

- [ ] Real-device testing is not required, or I recorded the device profile, version, commands, results, and rollback state.
- [ ] Any output target changed during testing was restored to its normal state.

## Publication Checklist

- [ ] No credentials, private addresses, personal paths, serials, key material, or unredacted logs are included.
- [ ] No generated release images, packages, caches, backups, or local build artifacts are committed.
- [ ] Documentation, public export rules, and Buildroot preparation are updated where applicable.
- [ ] New or redistributed third-party material has compatible license and attribution evidence.
- [ ] Security-sensitive details follow `SECURITY.md` instead of a public issue or pull request.
