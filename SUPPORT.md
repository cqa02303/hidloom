# HIDloom Support

## Community support

Use public GitHub issues for reproducible bugs, documentation defects, portability problems, and focused feature
requests. Search existing issues first and provide the smallest safe reproduction possible.

Public issues must not contain credentials, private keys, unredacted logs, private addresses, personal paths, or
embargoed vulnerability details. Follow [`SECURITY.md`](SECURITY.md) for security reports.

## Supported scope

- source builds from the public repository;
- the documented Raspberry Pi OS package workflow;
- the documented offline Buildroot appliance profile;
- `cqa02303v5` device profile behavior;
- Vial/keymap compatibility and documented migration paths.

## Best-effort scope

- custom boards and wiring;
- unsupported distributions or SBCs;
- locally modified images, services, or USB descriptors;
- third-party peripherals and host-specific driver behavior.

There is no guaranteed response time, warranty, remote administration service, or obligation to support private
deployments. Hardware safety, backups, rollback media, and compliance with local rules remain the operator's
responsibility.

## Useful issue information

- HIDloom revision, package version, or image checksum;
- device profile and host operating system;
- expected and actual behavior;
- minimal reproduction and relevant sanitized logs;
- whether Raspberry Pi OS, Buildroot, or both are affected;
- rollback result and whether the keyboard remains usable.
